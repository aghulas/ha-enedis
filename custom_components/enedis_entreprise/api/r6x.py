"""Parsers for Enedis recurring publications: R63 (load curve) and R64 (indexes), JSON and CSV.

Format: Enedis guide "flux R6X via compte client entreprise" v2.0, summarised in docs/api.md.

Rules (CLAUDE.md): unknown flux codes or fields give a warning and are skipped, never an exception
out of `parse()` for a well-formed file; warnings never contain a PRM or any other identifier.
Timestamps are kept exactly as published (naive); `localize()` is the single place where the
time-zone assumption lives.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
CURVE_FLUX = ("R63A", "R63B")
INDEX_FLUX = ("R64A", "R64B")
# Between the data type and the timestamp come two to four identifiers, depending on who names
# the file: request id, then (archives) publication id and/or SIREN, then the sequence number.
_FILENAME = re.compile(
    r"Enedis_(?P<flux>R\d{2}[A-Z])_(?P<mode>[A-Z])_(?P<kind>[A-Za-z]+)"
    r"_(?P<fields>[A-Za-z0-9]+(?:_[A-Za-z0-9]+){1,3})_(?P<stamp>\d{14})\.(?P<ext>zip|json|csv)",
    re.IGNORECASE,
)
_STEP = re.compile(r"PT(\d+)M")
_GRIDS = {"d": "D", "distributeur": "D", "f": "F", "fournisseur": "F"}


class R6xParseError(Exception):
    """The content is not a readable R6X file at all (bad JSON, no CSV header…)."""


@dataclass(frozen=True, slots=True)
class FileInfo:
    """What the name of an archive or of a JSON/CSV file says."""

    code_flux: str
    mode: str
    kind: str
    id_demande: str
    siren: str | None  # archives only
    sequence: int | None  # JSON/CSV files, and archives as really published
    created: datetime
    extension: str

    @property
    def key(self) -> str | None:
        """Identity of a published file (processed-file store); None without sequence number."""
        if self.sequence is None:
            return None
        return f"{self.code_flux}_{self.id_demande}_{self.sequence:05d}"


@dataclass(frozen=True, slots=True)
class CurvePoint:
    timestamp: datetime  # naive, as published
    value: int
    step: timedelta
    nature: str | None = None
    completion: str | None = None
    iv: str | None = None
    ec: str | None = None

    @property
    def energy(self) -> float:
        """Mean value over the step × duration in hours (Wh for a curve in W)."""
        return self.value * self.step.total_seconds() / 3600


@dataclass(slots=True)
class CurveSeries:
    prm: str
    etape: str | None
    grandeur_metier: str | None
    grandeur_physique: str | None
    unit: str | None
    period_start: datetime | None
    period_end: datetime | None
    points: list[CurvePoint] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class IndexValue:
    prm: str
    timestamp: datetime  # naive, as published
    value: int
    grandeur_metier: str | None
    grandeur_physique: str | None
    unit: str | None
    context: str | None = None
    reading_type: str | None = None
    reason: str | None = None
    etape: str | None = None
    grid: str | None = None  # "D" (distributor), "F" (supplier) or None (totaliser)
    calendar_id: str | None = None
    calendar_label: str | None = None
    class_id: str | None = None
    class_label: str | None = None
    dial: str | None = None
    iv: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None


@dataclass(slots=True)
class Publication:
    code_flux: str | None
    file_format: str  # "JSON" or "CSV"
    header: dict[str, Any] = field(default_factory=dict)
    curves: list[CurveSeries] = field(default_factory=list)
    indexes: list[IndexValue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --- names ---------------------------------------------------------------------------------------


def parse_filename(name: str) -> FileInfo | None:
    """What the name of an archive or of a JSON/CSV file says, or None if it is not an R6X name.

    Guide: `Enedis_<flux>_<mode>_<type>_<idDemande>_<SIREN|numSequence>_<horodate>.<ext>`.
    Real archives (2026): `ENEDIS_<flux>_<mode>_<type>_<idDemande>[_<idPublication>]_<SIREN>
    _<numSequence>_<horodate>.zip` — upper case, with the sequence number as well.
    """
    match = _FILENAME.search(name)
    if not match:
        return None
    try:
        created = datetime.strptime(match["stamp"], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    id_demande, *others = match["fields"].split("_")
    sequence = None
    if len(others[-1]) == 5 and others[-1].isdigit():
        sequence = int(others.pop())
    siren = next((f for f in reversed(others) if len(f) == 9 and f.isdigit()), None)
    return FileInfo(
        code_flux=match["flux"].upper(),
        mode=match["mode"].upper(),
        kind=match["kind"],
        id_demande=id_demande,
        siren=siren,
        sequence=sequence,
        created=created,
        extension=match["ext"].lower(),
    )


# --- small converters ----------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    """None for JSON null, empty strings and the literal `null` of CSV files."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text == "" or text.lower() == "null" else text


def _timestamp(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return round(float(text.replace(",", ".")))
    except (ValueError, OverflowError):
        return None


def _step(value: Any) -> timedelta | None:
    match = _STEP.fullmatch(_text(value) or "")
    return timedelta(minutes=int(match[1])) if match and int(match[1]) else None


def _grid(value: Any) -> str | None:
    text = _text(value)
    return None if text is None else _GRIDS.get(text.lower(), text)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    """A JSON array of objects — tolerates a single object, drops anything else."""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


class _Skipped:
    """Counts skipped items per reason so that a broken file gives a few warnings, not thousands."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def add(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1

    def warnings(self) -> list[str]:
        return [f"{reason} ({count} skipped)" for reason, count in self.counts.items()]


# --- entry point ---------------------------------------------------------------------------------


def parse(content: bytes | str, name: str | None = None) -> Publication:
    """Parse one JSON or CSV file. `name` (file name) helps identify the flux of a CSV file."""
    text = _decode(content) if isinstance(content, bytes) else content.lstrip("﻿")
    info = parse_filename(name) if name else None
    if text.lstrip().startswith("{"):
        return _parse_json(text, info)
    return _parse_csv(text, info)


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")


def _unsupported(publication: Publication) -> Publication:
    publication.warnings.append(f"unsupported flux code {publication.code_flux!r}: file skipped")
    return publication


# --- JSON ----------------------------------------------------------------------------------------


def _parse_json(text: str, info: FileInfo | None) -> Publication:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as err:
        raise R6xParseError(f"invalid JSON (line {err.lineno})") from None
    if not isinstance(document, dict):
        raise R6xParseError("invalid JSON: an object was expected")
    header = _object(document.get("header"))
    code = _text(header.get("codeFlux")) or (info.code_flux if info else None)
    publication = Publication(code_flux=code.upper() if code else None, file_format="JSON")
    publication.header = dict(header)
    if isinstance(document.get("echeances"), dict):
        publication.header["echeances"] = document["echeances"]
    skipped = _Skipped()
    mesures = _items(document.get("mesures"))
    if publication.code_flux in CURVE_FLUX:
        for mesure in mesures:
            publication.curves.extend(_json_curves(mesure, skipped))
    elif publication.code_flux in INDEX_FLUX:
        for mesure in mesures:
            publication.indexes.extend(_json_indexes(mesure, skipped))
    else:
        return _unsupported(publication)
    publication.warnings.extend(skipped.warnings())
    return publication


def _period(mesure: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    periode = _object(mesure.get("periode"))
    return _timestamp(periode.get("dateDebut")), _timestamp(periode.get("dateFin"))


def _json_curves(mesure: dict[str, Any], skipped: _Skipped) -> Iterator[CurveSeries]:
    prm = _text(mesure.get("idPrm"))
    if prm is None:
        skipped.add("measure without idPrm")
        return
    start, end = _period(mesure)
    for grandeur in _items(mesure.get("grandeur")):
        series = CurveSeries(
            prm=prm,
            etape=_text(mesure.get("etapeMetier")),
            grandeur_metier=_text(grandeur.get("grandeurMetier")),
            grandeur_physique=_text(grandeur.get("grandeurPhysique")),
            unit=_text(grandeur.get("unite")),
            period_start=start,
            period_end=end,
        )
        for raw in _items(grandeur.get("points")):
            point = _curve_point(
                raw.get("d"), raw.get("v"), raw.get("p"), raw.get("n"), raw.get("tc"),
                raw.get("iv"), raw.get("ec"), skipped,
            )  # fmt: skip
            if point:
                series.points.append(point)
        yield series


def _curve_point(
    d: Any, v: Any, p: Any, n: Any, tc: Any, iv: Any, ec: Any, skipped: _Skipped
) -> CurvePoint | None:
    timestamp, value, step = _timestamp(d), _integer(v), _step(p)
    if timestamp is None:
        skipped.add("curve point without a readable timestamp")
    elif value is None:
        skipped.add("curve point without a value")
    elif step is None:
        skipped.add("curve point with an unknown step")
    else:
        return CurvePoint(timestamp, value, step, _text(n), _text(tc), _text(iv), _text(ec))
    return None


def _json_indexes(mesure: dict[str, Any], skipped: _Skipped) -> Iterator[IndexValue]:
    prm = _text(mesure.get("idPrm"))
    if prm is None:
        skipped.add("measure without idPrm")
        return
    start, end = _period(mesure)
    for contexte in _items(mesure.get("contexte")):
        for grandeur in _items(contexte.get("grandeur")):
            common: dict[str, Any] = {
                "prm": prm,
                "grandeur_metier": _text(grandeur.get("grandeurMetier")),
                "grandeur_physique": _text(grandeur.get("grandeurPhysique")),
                "unit": _text(grandeur.get("unite")),
                "context": _text(contexte.get("contexteReleve")),
                "reading_type": _text(contexte.get("typeReleve")),
                "reason": _text(contexte.get("motifReleve")),
                "etape": _text(contexte.get("etapeMetier")),
                "period_start": start,
                "period_end": end,
            }
            for total in _items(grandeur.get("cadranTotalisateur")):
                yield from _index_values(
                    total.get("valeur"), common | {"dial": _text(total.get("codeCadran"))}, skipped
                )
            for calendrier in _items(grandeur.get("calendrier")):
                calendar = {
                    "grid": _grid(calendrier.get("libelleGrille")),
                    "calendar_id": _text(calendrier.get("idCalendrier")),
                    "calendar_label": _text(calendrier.get("libelleCalendrier")),
                }
                for classe in _items(calendrier.get("classeTemporelle")):
                    fields = common | calendar | {
                        "class_id": _text(classe.get("idClasseTemporelle")),
                        "class_label": _text(classe.get("libelleClasseTemporelle")),
                        "dial": _text(classe.get("codeCadran")),
                    }  # fmt: skip
                    yield from _index_values(classe.get("valeur"), fields, skipped)


def _index_values(values: Any, fields: dict[str, Any], skipped: _Skipped) -> Iterator[IndexValue]:
    for raw in _items(values):
        value = _index_value(raw.get("d"), raw.get("v"), raw.get("iv"), fields, skipped)
        if value:
            yield value


def _index_value(
    d: Any, v: Any, iv: Any, fields: dict[str, Any], skipped: _Skipped
) -> IndexValue | None:
    timestamp, value = _timestamp(d), _integer(v)
    if timestamp is None:
        skipped.add("index without a readable timestamp")
    elif value is None:
        skipped.add("index without a value")
    else:
        return IndexValue(timestamp=timestamp, value=value, iv=_text(iv), **fields)
    return None


# --- CSV -----------------------------------------------------------------------------------------


def _label(text: str) -> str:
    """`Libellé Calendrier` → `libelle calendrier` (the guide itself is inconsistent on case)."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().split())


def _parse_csv(text: str, info: FileInfo | None) -> Publication:
    rows = csv.reader(io.StringIO(text), delimiter=";")
    labels = [_label(cell) for cell in next(rows, [])]
    if "identifiant prm" not in labels:
        raise R6xParseError(
            "not an R6X file: neither JSON nor a CSV with an 'Identifiant PRM' column"
        )
    if info:
        code: str | None = info.code_flux
    elif "pas" in labels:
        code = "R63"  # the A/B variant is not in the content of a CSV file
    elif "cadran" in labels:
        code = "R64"
    else:
        code = None
    publication = Publication(code_flux=code, file_format="CSV")
    records = (dict(zip(labels, row, strict=False)) for row in rows if any(row))
    skipped = _Skipped()
    if code and code.startswith("R63"):
        publication.curves = _csv_curves(records, skipped)
    elif code and code.startswith("R64"):
        publication.indexes = list(_csv_indexes(records, skipped))
    else:
        return _unsupported(publication)
    publication.warnings.extend(skipped.warnings())
    return publication


def _csv_curves(records: Iterable[dict[str, str]], skipped: _Skipped) -> list[CurveSeries]:
    series: dict[tuple[Any, ...], CurveSeries] = {}
    for record in records:
        prm = _text(record.get("identifiant prm"))
        if prm is None:
            skipped.add("row without PRM")
            continue
        point = _curve_point(
            record.get("horodate"), record.get("valeur"), record.get("pas"), record.get("nature"),
            None, record.get("indice de vraisemblance"), record.get("etat complementaire"), skipped,
        )  # fmt: skip
        if point is None:
            continue
        candidate = CurveSeries(
            prm=prm,
            etape=_text(record.get("etape metier")),
            grandeur_metier=_text(record.get("grandeur metier")),
            grandeur_physique=_text(record.get("grandeur physique")),
            unit=_text(record.get("unite")),
            period_start=_timestamp(record.get("date de debut")),
            period_end=_timestamp(record.get("date de fin")),
        )
        key = (
            prm, candidate.etape, candidate.grandeur_metier, candidate.grandeur_physique,
            candidate.unit, candidate.period_start, candidate.period_end,
        )  # fmt: skip
        series.setdefault(key, candidate).points.append(point)
    return list(series.values())


def _csv_indexes(records: Iterable[dict[str, str]], skipped: _Skipped) -> Iterator[IndexValue]:
    for record in records:
        prm = _text(record.get("identifiant prm"))
        if prm is None:
            skipped.add("row without PRM")
            continue
        fields = {
            "prm": prm,
            "grandeur_metier": _text(record.get("grandeur metier")),
            "grandeur_physique": _text(record.get("grandeur physique")),
            "unit": _text(record.get("unite")),
            "context": _text(record.get("contexte de releve")),
            "reading_type": _text(record.get("type de releve")),
            "reason": _text(record.get("motif de releve")),
            "etape": _text(record.get("etape metier")),
            "grid": _grid(record.get("grille")),
            "calendar_id": _text(record.get("identifiant calendrier")),
            "calendar_label": _text(record.get("libelle calendrier")),
            "class_id": _text(record.get("identifiant classe temporelle")),
            "class_label": _text(record.get("libelle classe temporelle")),
            "dial": _text(record.get("cadran")),
            "period_start": _timestamp(record.get("date de debut")),
            "period_end": _timestamp(record.get("date de fin")),
        }
        value = _index_value(
            record.get("horodate"), record.get("valeur"), record.get("indice de vraisemblance"),
            fields, skipped,
        )  # fmt: skip
        if value:
            yield value


# --- time ----------------------------------------------------------------------------------------


def localize(timestamps: Iterable[datetime], zone: ZoneInfo = PARIS) -> list[datetime]:
    """Published (naive, French legal time — assumption, see docs/api.md) → aware UTC datetimes.

    Give the timestamps of ONE series in file order: when the clocks go back, 02:00–03:00 comes
    twice and the second pass is recognised because local time steps backwards.
    """
    out: list[datetime] = []
    previous: datetime | None = None
    fold = 0
    for naive in timestamps:
        ambiguous = (
            naive.replace(tzinfo=zone, fold=0).utcoffset()
            != naive.replace(tzinfo=zone, fold=1).utcoffset()
        )
        if not ambiguous:
            fold = 0
        elif previous is not None and naive <= previous:
            fold = 1
        previous = naive
        out.append(naive.replace(tzinfo=zone, fold=fold).astimezone(UTC))
    return out
