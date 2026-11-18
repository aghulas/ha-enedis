"""Polls the source, decrypts, parses and imports. A bad file never stops the others."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    DecryptError,
    IndexValue,
    Publication,
    R6xParseError,
    WrongKeyError,
    localize,
    open_publication,
    parse,
    parse_filename,
)
from .const import (
    DEFAULT_NO_FILE_DAYS,
    DOMAIN,
    POINT_RETENTION,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
)
from .energy import hour_values, merge, newest, prune
from .sources import Source, SourceError, SourceFile
from .stats import async_import_hours

_LOGGER = logging.getLogger(__name__)

ERROR_WRONG_KEY = "wrong_key"
ERROR_UNDECRYPTABLE = "undecryptable"
ERROR_UNREADABLE = "unreadable"


@dataclass(slots=True)
class EnedisData:
    """What entities and diagnostics read. Persisted, so it survives a restart."""

    last_file: datetime | None = None
    files_processed: int = 0
    last_point: dict[str, datetime] = field(default_factory=dict)  # per PRM, UTC
    natures: dict[str, dict[str, int]] = field(default_factory=dict)  # per PRM, last curve file
    indexes: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)  # per PRM
    errors: dict[str, int] = field(default_factory=dict)  # problems seen during the last poll


def index_key(index: IndexValue) -> str:
    """Stable identity of an index series: quantity, grid, calendar, then time class or dial."""
    parts = (
        index.grandeur_metier,
        index.grandeur_physique,
        index.grid,
        index.calendar_id,
        index.class_id or index.dial,
    )
    return "|".join(part or "" for part in parts)


class EnedisCoordinator(DataUpdateCoordinator[EnedisData]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source: Source,
        key: bytes | None,
        prms: set[str] | None = None,
        no_file_days: int = DEFAULT_NO_FILE_DAYS,
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=UPDATE_INTERVAL
        )
        self._source = source
        self._key = key
        self._prms = prms or None
        self._no_file_after = timedelta(days=no_file_days)
        self._entry_id = entry.entry_id
        self._since = dt_util.utcnow()
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._processed: dict[str, str] = {}
        self._points: dict[str, dict[str, list[int]]] = {}
        self._state = EnedisData()
        self._loaded = False

    async def _async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self._processed = stored.get("processed", {})
        self._points = stored.get("points", {})
        if stored.get("since"):
            self._since = datetime.fromisoformat(stored["since"])
        last_file = stored.get("last_file")
        self._state = EnedisData(
            last_file=datetime.fromisoformat(last_file) if last_file else None,
            files_processed=stored.get("files_processed", 0),
            last_point={
                prm: datetime.fromisoformat(text)
                for prm, text in stored.get("last_point", {}).items()
            },
            natures=stored.get("natures", {}),
            indexes=stored.get("indexes", {}),
        )
        self._loaded = True

    async def _async_save(self) -> None:
        state = self._state
        await self._store.async_save(
            {
                "processed": self._processed,
                "points": self._points,
                "since": self._since.isoformat(),
                "last_file": state.last_file.isoformat() if state.last_file else None,
                "files_processed": state.files_processed,
                "last_point": {prm: when.isoformat() for prm, when in state.last_point.items()},
                "natures": state.natures,
                "indexes": state.indexes,
            }
        )

    async def _async_update_data(self) -> EnedisData:
        if not self._loaded:
            await self._async_load()
            await self._async_save()  # remembers since when files are expected
        try:
            files = await self.hass.async_add_executor_job(self._source.poll, set(self._processed))
        except SourceError as err:
            raise UpdateFailed(str(err)) from err

        def created(file: SourceFile) -> datetime:
            info = parse_filename(file.name)
            return info.created if info else datetime.max

        errors: dict[str, int] = {}
        touched: dict[str, set[int]] = {}
        changed = False
        for file in sorted(files, key=created):
            changed |= await self._async_process(file, errors, touched)

        for series, hours in touched.items():
            prm, _, metier = series.partition("|")
            values = hour_values(self._points[series], hours)
            await async_import_hours(self.hass, prm, metier == "PROD", values)
        for buffer in self._points.values():
            # Relative to the newest point, not to today: files may be imported long after.
            prune(buffer, newest(buffer) - POINT_RETENTION)
        if changed:
            await self._async_save()

        state = self._state
        self._state = EnedisData(
            last_file=state.last_file,
            files_processed=state.files_processed,
            last_point=state.last_point,
            natures=state.natures,
            indexes=state.indexes,
            errors=errors,
        )
        self._update_issues(errors)
        return self._state

    def _update_issues(self, errors: dict[str, int]) -> None:
        """Repairs: files that cannot be decrypted, and no file received for too long."""
        undecryptable = errors.get(ERROR_WRONG_KEY, 0) + errors.get(ERROR_UNDECRYPTABLE, 0)
        self._set_issue("undecryptable", bool(undecryptable), ir.IssueSeverity.ERROR, undecryptable)
        quiet = dt_util.utcnow() - (self._state.last_file or self._since)
        self._set_issue(
            "no_file", quiet > self._no_file_after, ir.IssueSeverity.WARNING, quiet.days
        )

    def _set_issue(self, kind: str, active: bool, severity: ir.IssueSeverity, count: int) -> None:
        issue_id = f"{kind}_{self._entry_id}"
        if active:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=severity,
                translation_key=kind,
                translation_placeholders={"count": str(count)},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def clear_issues(self) -> None:
        for kind in ("undecryptable", "no_file"):
            ir.async_delete_issue(self.hass, DOMAIN, f"{kind}_{self._entry_id}")

    async def _async_process(
        self, file: SourceFile, errors: dict[str, int], touched: dict[str, set[int]]
    ) -> bool:
        """One file from the source. Returns True if something was recorded."""
        try:
            published = await self.hass.async_add_executor_job(
                open_publication, file.data, self._key, file.name
            )
        except DecryptError as err:
            # Not marked as processed: tried again at the next poll, e.g. after a new key.
            kind = ERROR_WRONG_KEY if isinstance(err, WrongKeyError) else ERROR_UNDECRYPTABLE
            errors[kind] = errors.get(kind, 0) + 1
            _LOGGER.warning("A file from the source could not be decrypted: %s", err)
            return False

        now = dt_util.utcnow()
        for item in published:
            info = parse_filename(item.name)
            key = (info.key if info else None) or f"{file.ident}/{item.name}"
            if key in self._processed:
                continue
            try:
                publication = await self.hass.async_add_executor_job(parse, item.content, item.name)
            except R6xParseError as err:
                errors[ERROR_UNREADABLE] = errors.get(ERROR_UNREADABLE, 0) + 1
                _LOGGER.warning("A published file could not be read: %s", err)
            else:
                for warning in publication.warnings:
                    _LOGGER.warning("Published file partly ignored: %s", warning)
                self._apply(publication, touched)
                self._state.files_processed += 1
                self._state.last_file = now
            self._processed[key] = now.isoformat()
        self._processed[file.ident] = now.isoformat()
        return True

    def _apply(self, publication: Publication, touched: dict[str, set[int]]) -> None:
        natures: dict[str, dict[str, int]] = {}
        for series in publication.curves:
            if self._prms and series.prm not in self._prms:
                continue
            if series.grandeur_physique != "PA" or series.grandeur_metier not in ("CONS", "PROD"):
                continue  # reactive power and voltage: not imported yet
            instants = localize(point.timestamp for point in series.points)
            if not instants:
                continue
            name = f"{series.prm}|{series.grandeur_metier}"
            hours = merge(
                self._points.setdefault(name, {}),
                (
                    (instant, point.value, int(point.step.total_seconds()))
                    for instant, point in zip(instants, series.points, strict=True)
                ),
            )
            if hours:
                touched.setdefault(name, set()).update(hours)
            latest = max(instants)
            previous = self._state.last_point.get(series.prm)
            if previous is None or latest > previous:
                self._state.last_point[series.prm] = latest
            counts = natures.setdefault(series.prm, {})
            for point in series.points:
                nature = point.nature or "?"
                counts[nature] = counts.get(nature, 0) + 1
        self._state.natures.update(natures)

        for index in publication.indexes:
            if self._prms and index.prm not in self._prms:
                continue
            series_key = index_key(index)
            known = self._state.indexes.setdefault(index.prm, {})
            timestamp = index.timestamp.isoformat()
            if series_key in known and known[series_key]["timestamp"] > timestamp:
                continue
            known[series_key] = {
                "timestamp": timestamp,
                "value": index.value,
                "unit": index.unit,
                "grandeur_metier": index.grandeur_metier,
                "grandeur_physique": index.grandeur_physique,
                "grid": index.grid,
                "calendar_id": index.calendar_id,
                "class_id": index.class_id,
                "class_label": index.class_label,
                "dial": index.dial,
                "context": index.context,
                "reading_type": index.reading_type,
            }
