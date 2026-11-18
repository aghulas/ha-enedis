from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.enedis_entreprise.api import HistoryError, parse_history_csv
from custom_components.enedis_entreprise.const import DOMAIN
from custom_components.enedis_entreprise.energy import Buffer, last_day_peak, merge

from . import synthetic as s
from .test_coordinator import curve, drop, refresh, rows, setup
from .test_entities import state_of

PARIS = ZoneInfo("Europe/Paris")


def export(start: datetime, kilowatts: list[float | None], minutes: int = 5) -> str:
    """The CSV written by enedis-mcp: local time with offset, decimal comma."""
    lines = ["debut;kw_moyen"]
    for i, value in enumerate(kilowatts):
        when = (start + timedelta(minutes=minutes * i)).astimezone(PARIS)
        lines.append(f"{when.isoformat()};{'' if value is None else str(value).replace('.', ',')}")
    return "\n".join(lines) + "\n"


def test_parse_history() -> None:
    start = datetime(2026, 1, 31, 23, tzinfo=UTC)  # 1 February 00:00 in Paris
    points = parse_history_csv("﻿" + export(start, [4.0, None, 12.5]) + "\n")
    assert points == [(start, 4000, 300), (start + timedelta(minutes=10), 12500, 300)]
    assert parse_history_csv(export(start, [1.0, 2.0], minutes=30))[0][2] == 1800
    assert parse_history_csv(export(start, [1.0])) == [(start, 1000, 300)]
    assert parse_history_csv("debut;kw_moyen\n") == []


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Identifiant PRM;Valeur\n",
        "debut;kw_moyen\nhier;1\n",
        "debut;kw_moyen\n2026-02-01T00:00:00+01:00;beaucoup\n",
        "debut;kw_moyen\n2026-02-01T00:00:00;1\n",
        "debut;kw_moyen\n2026-02-01T00:00:00+01:00;1\n2026-02-01T00:07:00+01:00;1\n",
        "debut;kw_moyen\n2026-02-01T00:00:00+01:00;1\n2026-02-01T00:00:00+01:00;1\n",
    ],
)
def test_parse_history_refuses(text: str) -> None:
    with pytest.raises(HistoryError):
        parse_history_csv(text)


def test_last_day_peak() -> None:
    buffer: Buffer = {}
    assert last_day_peak(buffer, PARIS) is None
    day = datetime(2026, 2, 28, 23, tzinfo=UTC)  # 1 March 00:00 in Paris
    values = [10000] * 288
    values[100] = values[200] = 45000
    merge(buffer, [(day + timedelta(minutes=5 * i), v, 300) for i, v in enumerate(values)])
    # The following day has only started: it is not "the last complete day".
    merge(buffer, [(day + timedelta(days=1, minutes=5 * i), 99000, 300) for i in range(12)])
    peak = last_day_peak(buffer, PARIS)
    assert peak is not None
    assert (peak.day, peak.kw) == (date(2026, 3, 1), 45.0)
    assert peak.at == day + timedelta(minutes=500)  # first of two equal peaks

    assert last_day_peak({k: v for k, v in list(buffer.items())[:100]}, PARIS) is None


async def test_import_history_service(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path
) -> None:
    # Enedis publications cover 1 March from 08:00; the portal export covers the whole day.
    drop(tmp_path, 1, curve("2026-03-01 08:00:00", [12000] * 12))
    entry = await setup(hass, tmp_path)
    path = tmp_path / "courbe.csv"
    path.write_text(export(datetime(2026, 2, 28, 23, tzinfo=UTC), [6.0] * 288))
    hass.config.allowlist_external_dirs.add(str(tmp_path))
    call = {"path": str(path), "prm": s.PRM}

    result = await hass.services.async_call(
        DOMAIN, "import_history", call, blocking=True, return_response=True
    )
    assert result == {"points": 276, "hours": 23}
    await async_wait_recording_done(hass)
    energy = await rows(hass)
    assert len(energy) == 24
    # The hour already received from Enedis is kept; the rest comes from the export.
    assert energy[8]["state"] == pytest.approx(12.0)
    assert energy[0]["state"] == pytest.approx(6.0)
    assert energy[-1]["sum"] == pytest.approx(23 * 6.0 + 12.0)

    # Again: nothing new. With overwrite: the export wins.
    again = await hass.services.async_call(
        DOMAIN, "import_history", call, blocking=True, return_response=True
    )
    assert again == {"points": 0, "hours": 0}
    await hass.services.async_call(
        DOMAIN, "import_history", call | {"overwrite": True, "config_entry_id": entry.entry_id},
        blocking=True,
    )  # fmt: skip
    await async_wait_recording_done(hass)
    energy = await rows(hass)
    assert energy[8]["state"] == pytest.approx(6.0)
    assert energy[-1]["sum"] == pytest.approx(144.0)

    # The day is now complete: the peak sensor appears.
    await hass.async_block_till_done()
    peak = state_of(hass, f"{s.PRM}_last_day_peak")
    assert (peak.state, peak.attributes["unit_of_measurement"]) == ("6.0", "kW")
    assert peak.attributes["day"] == "2026-03-01"
    assert entry.runtime_data.data.last_point[s.PRM] == datetime(2026, 3, 1, 22, 55, tzinfo=UTC)


async def test_import_history_refusals(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path
) -> None:
    entry = await setup(hass, tmp_path)
    path = tmp_path / "courbe.csv"
    path.write_text("not a history file\n")

    async def call(**data: Any) -> Any:
        return await hass.services.async_call(
            DOMAIN, "import_history", {"path": str(path), "prm": s.PRM} | data, blocking=True
        )

    with pytest.raises(ServiceValidationError) as err:
        await call()
    assert err.value.translation_key == "path_not_allowed"
    hass.config.allowlist_external_dirs.add(str(tmp_path))
    with pytest.raises(ServiceValidationError) as err:
        await call()
    assert err.value.translation_key == "history_unreadable"
    with pytest.raises(ServiceValidationError) as err:
        await call(path=str(tmp_path / "absent.csv"))
    assert err.value.translation_key == "history_unreadable"
    with pytest.raises(ServiceValidationError) as err:
        await call(config_entry_id="unknown")
    assert err.value.translation_key == "entry_not_found"
    with pytest.raises(Exception, match="prm"):
        await call(prm="123")
    await refresh(hass, entry)
