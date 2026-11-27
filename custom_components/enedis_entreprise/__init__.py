"""Enedis entreprise (R6X) — imports the files Enedis pushes (R63 load curve, R64 indexes)."""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .api import HistoryError, InvalidKeyError, parse_history_csv, parse_key
from .const import (
    CONF_DIRECTORY,
    CONF_ENTRY_ID,
    CONF_HOST,
    CONF_HOST_KEY,
    CONF_KEY,
    CONF_NO_FILE_DAYS,
    CONF_OVERWRITE,
    CONF_PASSWORD,
    CONF_PATH,
    CONF_PORT,
    CONF_PRM,
    CONF_PRMS,
    CONF_SOURCE,
    CONF_USERNAME,
    DEFAULT_NO_FILE_DAYS,
    DOMAIN,
    SERVICE_IMPORT_HISTORY,
    SOURCE_FOLDER,
    SOURCE_FTPS,
    SOURCE_IMAP,
    SOURCE_SFTP,
)
from .coordinator import EnedisCoordinator
from .sources import FolderSource, FtpsSource, SftpSource, Source

__all__ = [
    "DOMAIN",
    "async_remove_entry",
    "async_setup",
    "async_setup_entry",
    "async_unload_entry",
    "build_source",
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PATH): cv.string,
        vol.Required(CONF_PRM): vol.All(cv.string, vol.Match(r"^\d{14}$")),
        vol.Optional(CONF_ENTRY_ID): cv.string,
        vol.Optional(CONF_OVERWRITE, default=False): cv.boolean,
    }
)

PLATFORMS = [Platform.SENSOR]

type EnedisConfigEntry = ConfigEntry[EnedisCoordinator]


def build_source(data: dict[str, object]) -> Source:
    kind = data.get(CONF_SOURCE)
    if kind == SOURCE_FOLDER:
        return FolderSource(str(data[CONF_PATH]))
    if kind == SOURCE_FTPS:
        return FtpsSource(
            str(data[CONF_HOST]),
            str(data[CONF_USERNAME]),
            str(data[CONF_PASSWORD]),
            port=int(str(data.get(CONF_PORT, 21))),
            directory=str(data.get(CONF_DIRECTORY, "/")),
        )
    if kind == SOURCE_SFTP:
        return SftpSource(
            str(data[CONF_HOST]),
            str(data[CONF_USERNAME]),
            str(data[CONF_PASSWORD]),
            port=int(str(data.get(CONF_PORT, 22))),
            directory=str(data.get(CONF_DIRECTORY, "/")),
            host_key=str(data[CONF_HOST_KEY]) if data.get(CONF_HOST_KEY) else None,
        )
    raise ConfigEntryError(f"unknown source type {kind!r}")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the one-off history import service."""

    async def import_history(call: ServiceCall) -> ServiceResponse:
        loaded = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
            and call.data.get(CONF_ENTRY_ID) in (None, entry.entry_id)
        ]
        if len(loaded) != 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_found"
            )
        path = call.data[CONF_PATH]
        if not hass.config.is_allowed_path(path):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="path_not_allowed"
            )
        try:
            text = await hass.async_add_executor_job(_read_text, path)
            points = await hass.async_add_executor_job(parse_history_csv, text)
        except (OSError, UnicodeDecodeError, HistoryError) as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="history_unreadable",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from None
        coordinator: EnedisCoordinator = loaded[0].runtime_data
        return await coordinator.async_import_history(
            call.data[CONF_PRM], points, call.data[CONF_OVERWRITE]
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_HISTORY,
        import_history,
        schema=_HISTORY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8-sig")


def _mail_issue(entry: ConfigEntry) -> str:
    return f"mail_source_removed_{entry.entry_id}"


async def async_setup_entry(hass: HomeAssistant, entry: EnedisConfigEntry) -> bool:
    if entry.data.get(CONF_SOURCE) == SOURCE_IMAP:
        # Entry created by a development version: the mailbox source no longer exists. Statistics
        # already imported are kept; the entry has to be replaced by one with another source.
        ir.async_create_issue(
            hass,
            DOMAIN,
            _mail_issue(entry),
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="mail_source_removed",
        )
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="mail_source_removed")
    key = None
    if entry.data.get(CONF_KEY):
        try:
            key = parse_key(entry.data[CONF_KEY])
        except InvalidKeyError as err:
            raise ConfigEntryError(str(err)) from err
    prms = {str(prm) for prm in entry.options.get(CONF_PRMS, [])}
    coordinator = EnedisCoordinator(
        hass,
        entry,
        build_source(dict(entry.data)),
        key,
        prms,
        int(entry.options.get(CONF_NO_FILE_DAYS, DEFAULT_NO_FILE_DAYS)),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_reload(hass: HomeAssistant, entry: EnedisConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: EnedisConfigEntry) -> None:
    ir.async_delete_issue(hass, DOMAIN, _mail_issue(entry))


async def async_unload_entry(hass: HomeAssistant, entry: EnedisConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        entry.runtime_data.clear_issues()
    return unloaded
