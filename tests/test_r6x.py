from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from custom_components.enedis_entreprise.api import (
    R6xParseError,
    localize,
    parse,
    parse_filename,
)

from . import synthetic as s


def test_filenames() -> None:
    inner = parse_filename(s.R63_NAME)
    assert inner is not None
    assert (inner.code_flux, inner.mode, inner.kind, inner.id_demande) == (
        "R63A", "Q", "CdC", "M0000TEST",
    )  # fmt: skip
    assert (inner.sequence, inner.siren, inner.extension) == (7, None, "json")
    assert inner.created == datetime(2026, 3, 2, 6, 30)
    assert inner.key == "R63A_M0000TEST_00007"

    outer = parse_filename(f"/tmp/lisible{s.R63_ARCHIVE}")
    assert outer is not None
    assert (outer.siren, outer.sequence, outer.key) == (s.SIREN, None, None)

    assert parse_filename("facture.pdf") is None
    assert parse_filename("Enedis_R63A_Q_CdC_X_00001_20269999999999.json") is None


def test_r63_json() -> None:
    publication = parse(s.as_json(s.r63_document()), s.R63_NAME)
    assert (publication.code_flux, publication.file_format) == ("R63A", "JSON")
    assert publication.warnings == []
    assert publication.header["idDemande"] == "M0000TEST"
    assert publication.header["echeances"]["frequence"] == "2H"
    (series,) = publication.curves
    assert (series.prm, series.etape, series.unit) == (s.PRM, "BEST", "W")
    assert (series.grandeur_metier, series.grandeur_physique) == ("CONS", "PA")
    assert series.period_end == datetime(2026, 3, 2, 6)
    assert len(series.points) == 288
    first, estimated = series.points[0], series.points[3]
    assert (first.timestamp, first.value, first.step) == (
        datetime(2026, 3, 1), 12000, timedelta(minutes=5),
    )  # fmt: skip
    assert (first.nature, first.completion, first.iv, first.ec) == ("R", None, None, None)
    assert (estimated.nature, estimated.completion) == ("E", "A")
    # 14 h at 12 kW + 10 h at 40 kW
    assert sum(p.energy for p in series.points) == pytest.approx(568_000)


def test_r63_json_numbers_and_strings_are_both_accepted() -> None:
    document = s.r63_document(count=2)
    points = document["mesures"][0]["grandeur"][0]["points"]
    points[0]["v"] = 4000
    points[1]["v"] = "4000.4"
    values = [p.value for p in parse(s.as_json(document)).curves[0].points]
    assert values == [4000, 4000]


def test_r63_bad_points_are_skipped_with_warnings_that_hide_the_prm() -> None:
    document = s.r63_document(count=6)
    points = document["mesures"][0]["grandeur"][0]["points"]
    points[0]["v"] = None
    points[1]["d"] = "hier"
    points[2]["p"] = "P1D"
    points[3]["v"] = "beaucoup"
    points[4]["v"] = True
    document["mesures"].append({"etapeMetier": "BRUT"})
    document["mesures"].append("garbage")
    document["mesures"][0]["grandeur"].append({"points": {"v": 1, "d": "2026-03-01 00:00:00"}})
    publication = parse(s.as_json(document))
    assert [len(c.points) for c in publication.curves] == [1, 0]
    assert sorted(publication.warnings) == [
        "curve point with an unknown step (2 skipped)",
        "curve point without a readable timestamp (1 skipped)",
        "curve point without a value (3 skipped)",
        "measure without idPrm (1 skipped)",
    ]
    assert s.PRM not in " ".join(publication.warnings)


def test_r64_json() -> None:
    publication = parse(s.as_json(s.r64_document()), s.R64_NAME)
    assert publication.code_flux == "R64A"
    assert publication.warnings == []
    assert len(publication.indexes) == 5
    by_class = {(i.grandeur_physique, i.class_id): i for i in publication.indexes}
    hph = by_class["EA", "HPH"]
    assert (hph.prm, hph.value, hph.unit, hph.grid) == (s.PRM, 314603000, "Wh", "D")
    assert (hph.context, hph.reading_type, hph.reason, hph.etape) == ("FMR", "RC", None, "BRUT")
    assert (hph.calendar_id, hph.class_label, hph.dial) == ("D", "Heures Pleines Hiver", None)
    assert hph.timestamp == datetime(2026, 3, 2, 4, 29, 58)
    assert hph.period_start == datetime(2026, 3, 2, 4)
    assert (by_class["PMA", "HPH"].value, by_class["PMA", "HPH"].unit) == (61000, "VA")
    assert by_class["DD", "HPH"].value == 0


def test_r64_json_linky_totaliser_and_bad_values() -> None:
    document = s.r64_document()
    document["header"]["codeFlux"] = "R64B"
    grandeurs = document["mesures"][0]["contexte"][0]["grandeur"]
    grandeurs[0]["cadranTotalisateur"] = {
        "codeCadran": "IDX_EAS_T",
        "valeur": [
            {"d": "2026-03-02 00:00:00", "v": 123, "iv": 0},
            {"d": None, "v": 1},
            {"d": "2026-03-02 00:00:00", "v": None},
        ],
    }
    document["mesures"].append({"periode": None})
    publication = parse(s.as_json(document))
    total = next(i for i in publication.indexes if i.dial == "IDX_EAS_T")
    assert (total.value, total.iv, total.grid, total.class_id) == (123, "0", None, None)
    assert sorted(publication.warnings) == [
        "index without a readable timestamp (1 skipped)",
        "index without a value (1 skipped)",
        "measure without idPrm (1 skipped)",
    ]


def test_r63_csv() -> None:
    publication = parse(
        b"\xef\xbb\xbf" + s.r63_csv(), "Enedis_R63A_Q_CdC_X_00001_20260302063000.csv"
    )
    assert (publication.code_flux, publication.file_format) == ("R63A", "CSV")
    (series,) = publication.curves
    assert (series.prm, series.etape, series.grandeur_physique, series.unit) == (
        s.PRM, "BRUT", "PA", "W",
    )  # fmt: skip
    assert series.period_start == datetime(2026, 3, 2, 4)
    assert [p.value for p in series.points] == list(range(100, 112))
    assert series.points[1].timestamp == datetime(2026, 3, 1, 0, 5)
    assert (series.points[0].nature, series.points[0].iv, series.points[0].ec) == ("R", None, None)


def test_r63_csv_without_name_latin1_and_bad_rows() -> None:
    text = s.r63_csv(count=2).decode()
    text += f";;;PA;CONS;BRUT;W;2026-03-01 00:10:00;1;R;PT5M;null;null\n\n{s.PRM};;;PA;CONS\n"
    publication = parse(text.encode("cp1252"))
    assert publication.code_flux == "R63"
    assert len(publication.curves[0].points) == 2
    assert sorted(publication.warnings) == [
        "curve point without a readable timestamp (1 skipped)",
        "row without PRM (1 skipped)",
    ]


def test_r64_csv() -> None:
    publication = parse(s.r64_csv())
    assert publication.code_flux == "R64"
    first, supplier, pma = publication.indexes
    assert (first.value, first.grid, first.calendar_id, first.calendar_label) == (
        9921, "D", "DI000003", None,
    )  # fmt: skip
    assert (first.class_id, first.class_label, first.dial, first.iv) == (
        "HPH", "Heures Pleines Hiver", "EA1", None,
    )  # fmt: skip
    assert (first.context, first.reading_type, first.reason) == ("FMR", "RC", None)
    assert (supplier.grid, supplier.iv, supplier.class_id) == ("F", "0", "BASE")
    assert (pma.grandeur_physique, pma.unit, pma.value, pma.dial) == ("PMA", "VA", 61000, None)


def test_r64_csv_bad_rows() -> None:
    text = s.r64_csv().decode() + ";;;EA\n" + f"{s.PRM};;;EA;CONS;Wh;null\n"
    publication = parse(text)
    assert len(publication.indexes) == 3
    assert sorted(publication.warnings) == [
        "index without a readable timestamp (1 skipped)",
        "row without PRM (1 skipped)",
    ]


@pytest.mark.parametrize(
    ("content", "name"),
    [
        (json.dumps({"header": {"codeFlux": "R65A"}, "mesures": [{"idPrm": s.PRM}]}), None),
        (json.dumps({"mesures": []}), None),
        ("Identifiant PRM;Autre\n1;2\n", None),
        (s.r63_csv().decode(), "Enedis_R99Z_Q_CdC_X_00001_20260302063000.csv"),
    ],
)
def test_unknown_flux_is_skipped_not_raised(content: str, name: str | None) -> None:
    publication = parse(content, name)
    assert publication.curves == [] and publication.indexes == []
    assert len(publication.warnings) == 1 and "unsupported flux" in publication.warnings[0]


def test_flux_code_falls_back_on_the_file_name() -> None:
    document = s.r63_document(count=1)
    del document["header"]
    assert parse(s.as_json(document), s.R63_NAME).code_flux == "R63A"


@pytest.mark.parametrize("content", ['{"header": ', "[1, 2]", "", "bonjour;tout le monde\n"])
def test_unreadable_content(content: str) -> None:
    with pytest.raises(R6xParseError):
        parse(content)


def test_localize_winter_and_summer() -> None:
    assert localize([datetime(2026, 1, 15, 0, 0), datetime(2026, 7, 15, 0, 0)]) == [
        datetime(2026, 1, 14, 23, 0, tzinfo=UTC),
        datetime(2026, 7, 14, 22, 0, tzinfo=UTC),
    ]


def test_localize_25_hour_day() -> None:
    """25 October 2026: 02:00–03:00 comes twice; every 5-minute point gets its own UTC instant."""
    naive = [datetime.strptime(d, s.FMT) for d in s.stamps("2026-10-25 00:00:00", 36)]
    naive += [datetime.strptime(d, s.FMT) for d in s.stamps("2026-10-25 02:00:00", 24)]
    utc = localize(naive)
    assert utc[0] == datetime(2026, 10, 24, 22, 0, tzinfo=UTC)
    assert all(b - a == timedelta(minutes=5) for a, b in zip(utc, utc[1:], strict=False))
    assert utc[-1] == datetime(2026, 10, 25, 2, 55, tzinfo=UTC)
    # A new series starts over: an isolated ambiguous time is read as the first pass.
    assert localize([datetime(2026, 10, 25, 2, 30)]) == [datetime(2026, 10, 25, 0, 30, tzinfo=UTC)]


def test_localize_23_hour_day() -> None:
    naive = [datetime(2026, 3, 29, 1, 55), datetime(2026, 3, 29, 3, 0)]
    a, b = localize(naive)
    assert b - a == timedelta(minutes=5)
