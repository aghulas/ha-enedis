from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.enedis_entreprise import build_source
from custom_components.enedis_entreprise.api import encrypt, parse_key
from custom_components.enedis_entreprise.const import DOMAIN
from custom_components.enedis_entreprise.coordinator import EnedisCoordinator
from custom_components.enedis_entreprise.sources import FtpsSource, ImapSource

from . import synthetic as s

KEY = parse_key(s.KEY_HEX)
ENERGY = f"{DOMAIN}:{s.PRM}_energy"
POWER = f"{DOMAIN}:{s.PRM}_power"
# The synthetic day is 1 March 2026, Paris time (UTC+1).
DAY_START = datetime(2026, 2, 28, 23, tzinfo=UTC)


def name(sequence: int, flux: str = "R63A", kind: str = "CdC", stamp: int = 0) -> str:
    return f"Enedis_{flux}_Q_{kind}_M0000TEST_{sequence:05d}_202603020630{stamp:02d}.json"


def drop(folder: Path, sequence: int, document: dict[str, Any], *, key: bytes = KEY) -> None:
    """An encrypted archive, as it would arrive from Enedis."""
    inner = name(sequence, stamp=sequence)
    archive = s.archive({inner: s.as_json(document)})
    (folder / inner.replace(".json", ".zip")).write_bytes(encrypt(archive, key))


def ours(caplog: pytest.LogCaptureFixture) -> str:
    """What the integration itself logged (the recorder's SQL debug output is not ours)."""
    return "\n".join(record.getMessage() for record in caplog.records if DOMAIN in record.name)


def count(folder: Path) -> int:
    return len(list(folder.iterdir()))


def curve(start: str, watts: list[int]) -> dict[str, Any]:
    document = s.r63_document(start, len(watts))
    for point, value in zip(document["mesures"][0]["grandeur"][0]["points"], watts, strict=True):
        point["v"] = str(value)
        point["n"] = "R"
    return document


async def setup(hass: HomeAssistant, folder: Path, **extra: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"source": "folder", "path": str(folder), "key": s.KEY_HEX} | extra.pop("data", {}),
        options=extra.pop("options", {}),
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> EnedisCoordinator:
    coordinator: EnedisCoordinator = entry.runtime_data
    await coordinator.async_refresh()
    await async_wait_recording_done(hass)
    return coordinator


async def rows(hass: HomeAssistant, statistic: str = ENERGY) -> list[dict[str, Any]]:
    await async_wait_recording_done(hass)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2026, 1, 1, tzinfo=UTC),
        None,
        {statistic},
        "hour",
        None,
        {"state", "sum", "mean", "min", "max"},
    )
    return [dict(row) for row in result.get(statistic, [])]


async def test_curve_file_becomes_hourly_statistics(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path
) -> None:
    drop(tmp_path, 1, s.r63_document())
    entry = await setup(hass, tmp_path)
    assert entry.state is ConfigEntryState.LOADED

    energy = await rows(hass)
    assert len(energy) == 24
    assert energy[0]["start"] == DAY_START.timestamp()
    assert energy[0]["state"] == pytest.approx(12.0)
    assert energy[8]["state"] == pytest.approx(40.0)
    # 14 h at 12 kW + 10 h at 40 kW
    assert energy[-1]["sum"] == pytest.approx(568.0)
    power = await rows(hass, POWER)
    assert (power[8]["mean"], power[8]["min"], power[8]["max"]) == (
        pytest.approx(40.0), pytest.approx(40.0), pytest.approx(40.0),
    )  # fmt: skip

    data = entry.runtime_data.data
    assert data.files_processed == 1 and data.errors == {}
    assert data.last_point[s.PRM] == datetime(2026, 3, 1, 22, 55, tzinfo=UTC)
    assert data.natures[s.PRM] == {"R": 287, "E": 1}
    # Nothing was removed from the source folder.
    assert count(tmp_path) == 1


async def test_same_file_twice_changes_nothing(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path
) -> None:
    drop(tmp_path, 1, s.r63_document())
    entry = await setup(hass, tmp_path)
    before = await rows(hass)

    # Same poll again, then the same published file under another archive name, then the same
    # measures published again under a new sequence number.
    await refresh(hass, entry)
    inner = name(1, stamp=1)
    (tmp_path / "Enedis_R63A_Q_CdC_M0000TEST_00001_20260309000000.zip").write_bytes(
        encrypt(s.archive({inner: s.as_json(s.r63_document())}), KEY)
    )
    await refresh(hass, entry)
    assert entry.runtime_data.data.files_processed == 1
    drop(tmp_path, 2, s.r63_document())
    coordinator = await refresh(hass, entry)
    assert coordinator.data.files_processed == 2
    assert await rows(hass) == before


async def test_hour_split_across_files_then_corrected(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path
) -> None:
    drop(tmp_path, 1, curve("2026-03-01 08:00:00", [12000] * 18))  # 08:00 → 09:30
    entry = await setup(hass, tmp_path)
    energy = await rows(hass)
    assert [row["state"] for row in energy] == [pytest.approx(12.0), pytest.approx(6.0)]

    drop(tmp_path, 2, curve("2026-03-01 09:30:00", [12000] * 18))  # 09:30 → 11:00
    await refresh(hass, entry)
    energy = await rows(hass)
    assert [row["state"] for row in energy] == [pytest.approx(12.0)] * 3
    assert energy[-1]["sum"] == pytest.approx(36.0)

    # Late correction of the first hour (BEST data): later totals follow.
    drop(tmp_path, 3, curve("2026-03-01 08:00:00", [24000] * 12))
    await refresh(hass, entry)
    energy = await rows(hass)
    assert [row["state"] for row in energy] == [
        pytest.approx(24.0), pytest.approx(12.0), pytest.approx(12.0),
    ]  # fmt: skip
    assert [row["sum"] for row in energy] == [
        pytest.approx(24.0), pytest.approx(36.0), pytest.approx(48.0),
    ]  # fmt: skip

    # An older hour arriving afterwards shifts everything that follows it.
    drop(tmp_path, 4, curve("2026-03-01 06:00:00", [6000] * 12))
    await refresh(hass, entry)
    energy = await rows(hass)
    assert [row["sum"] for row in energy] == [
        pytest.approx(6.0), pytest.approx(30.0), pytest.approx(42.0), pytest.approx(54.0),
    ]  # fmt: skip

    # A later day continues the running total.
    drop(tmp_path, 5, curve("2026-03-02 08:00:00", [12000] * 12))
    await refresh(hass, entry)
    assert (await rows(hass))[-1]["sum"] == pytest.approx(66.0)


async def test_wrong_key_is_retried_and_unreadable_file_is_not(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    drop(tmp_path, 1, s.r63_document(), key=parse_key("ab" * 32))
    (tmp_path / name(2)).write_bytes(b'{"header": ')
    (tmp_path / name(3)).write_bytes(b"\x00" * 7)
    entry = await setup(hass, tmp_path)
    data = entry.runtime_data.data
    assert data.errors == {"wrong_key": 1, "undecryptable": 1, "unreadable": 1}
    assert data.files_processed == 0 and await rows(hass) == []

    coordinator = await refresh(hass, entry)
    assert coordinator.data.errors == {"wrong_key": 1, "undecryptable": 1}
    assert s.KEY_HEX not in ours(caplog) and s.PRM not in ours(caplog)


async def test_indexes_prm_filter_and_other_quantities(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / name(1, "R64A", "Index")).write_bytes(s.as_json(s.r64_document()))
    older = s.r64_document()
    for classe in older["mesures"][0]["contexte"][0]["grandeur"][0]["calendrier"][0][
        "classeTemporelle"
    ]:
        classe["valeur"][0] |= {"d": "2026-03-01 04:29:58", "v": 1}
    (tmp_path / name(2, "R64A", "Index", stamp=9)).write_bytes(s.as_json(older))

    mixed = s.r63_document(count=12)
    mixed["mesures"][0]["grandeur"].append(
        {"grandeurMetier": "CONS", "grandeurPhysique": "PRI", "unite": "VAr", "points": []}
    )
    mixed["mesures"][0]["grandeur"].append(
        {"grandeurMetier": "PROD", "grandeurPhysique": "PA", "unite": "W", "points": []}
    )
    mixed["mesures"][0]["grandeur"][0]["points"][0]["v"] = None
    stranger = s.r63_document(count=12)
    stranger["mesures"][0]["idPrm"] = "00000000000099"
    mixed["mesures"].append(stranger["mesures"][0])
    drop(tmp_path, 3, mixed)

    entry = await setup(hass, tmp_path, options={"prms": [s.PRM]})
    data = entry.runtime_data.data
    assert list(data.indexes) == [s.PRM] and list(data.last_point) == [s.PRM]
    hph = data.indexes[s.PRM]["CONS|EA|D|D|HPH"]
    assert (hph["value"], hph["unit"], hph["timestamp"]) == (
        314603000, "Wh", "2026-03-02T04:29:58",
    )  # fmt: skip
    assert data.indexes[s.PRM]["CONS|PMA|D|D|HPH"]["value"] == 61000
    assert len(await rows(hass)) == 1
    assert await rows(hass, f"{DOMAIN}:00000000000099_energy") == []
    assert "partly ignored" in ours(caplog) and s.PRM not in ours(caplog)


async def test_state_survives_a_restart(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path
) -> None:
    drop(tmp_path, 1, s.r63_document())
    entry = await setup(hass, tmp_path)
    before = await rows(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data = entry.runtime_data.data
    assert data.files_processed == 1 and data.last_file is not None
    assert data.last_point[s.PRM] == datetime(2026, 3, 1, 22, 55, tzinfo=UTC)
    assert await rows(hass) == before


async def test_setup_failures(recorder_mock: Any, hass: HomeAssistant, tmp_path: Path) -> None:
    missing = await setup(hass, tmp_path / "absent")
    assert missing.state is ConfigEntryState.SETUP_RETRY
    bad_key = await setup(hass, tmp_path, data={"key": "abc"})
    assert bad_key.state is ConfigEntryState.SETUP_ERROR
    unknown = await setup(hass, tmp_path, data={"source": "pigeon"})
    assert unknown.state is ConfigEntryState.SETUP_ERROR
    no_key = await setup(hass, tmp_path, data={"key": ""})
    assert no_key.state is ConfigEntryState.LOADED


def test_build_source() -> None:
    common = {"host": "h.example.invalid", "username": "u", "password": "p"}
    assert isinstance(
        build_source({"source": "imap", "sender": "x@example.invalid"} | common), ImapSource
    )
    assert isinstance(build_source({"source": "imap"} | common), ImapSource)
    assert isinstance(build_source({"source": "ftps", "port": "990"} | common), FtpsSource)


async def test_config_flow_placeholder(recorder_mock: Any, hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert (result["type"], result["reason"]) == ("abort", "not_ready")
