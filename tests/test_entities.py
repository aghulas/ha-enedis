"""Sensors, Repairs issues and diagnostics, on a real (test) Home Assistant."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.enedis_entreprise.api import parse_key
from custom_components.enedis_entreprise.const import DOMAIN
from custom_components.enedis_entreprise.diagnostics import async_get_config_entry_diagnostics

from . import synthetic as s
from .test_coordinator import drop, name, refresh, setup


def state_of(hass: HomeAssistant, unique_id: str) -> Any:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None, unique_id
    return hass.states.get(entity_id)


async def test_sensors_appear_as_files_arrive(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path
) -> None:
    entry = await setup(hass, tmp_path)
    assert state_of(hass, f"{entry.entry_id}_files_processed").state == "0"
    assert state_of(hass, f"{entry.entry_id}_last_file").state == "unknown"
    assert er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{s.PRM}_last_point") is None

    drop(tmp_path, 1, s.r63_document())
    (tmp_path / name(2, "R64A", "Index")).write_bytes(s.as_json(s.r64_document()))
    await refresh(hass, entry)
    await hass.async_block_till_done()

    assert state_of(hass, f"{entry.entry_id}_files_processed").state == "2"
    assert state_of(hass, f"{s.PRM}_last_point").state == "2026-03-01T22:55:00+00:00"

    energy = state_of(hass, f"{s.PRM}_CONS|EA|D|D|HPH")
    assert energy.state == "314603000"
    assert (
        energy.name == "PRM 00000000000042 Active energy index – Heures Pleines Hiver – distributor"
    )
    assert energy.attributes["unit_of_measurement"] == "Wh"
    assert energy.attributes["device_class"] == "energy"
    assert energy.attributes["state_class"] == "total_increasing"
    assert energy.attributes["reading_time"] == "2026-03-02T04:29:58"
    assert energy.attributes["context"] == "FMR"

    pma = state_of(hass, f"{s.PRM}_CONS|PMA|D|D|HPH")
    assert (pma.state, pma.attributes["unit_of_measurement"]) == ("61000", "VA")
    assert pma.attributes["device_class"] == "apparent_power"
    assert state_of(hass, f"{s.PRM}_CONS|DD|D|D|HPH").state == "0"

    # A later poll adds nothing twice.
    before = len(er.async_get(hass).entities)
    await refresh(hass, entry)
    assert len(er.async_get(hass).entities) == before


async def test_issue_when_files_cannot_be_decrypted(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path
) -> None:
    drop(tmp_path, 1, s.r63_document(), key=parse_key("ab" * 32))
    entry = await setup(hass, tmp_path)
    issues = ir.async_get(hass)
    issue = issues.async_get_issue(DOMAIN, f"undecryptable_{entry.entry_id}")
    assert issue is not None
    assert (issue.severity, issue.translation_placeholders) == ("error", {"count": "1"})
    assert issues.async_get_issue(DOMAIN, f"no_file_{entry.entry_id}") is None

    # The right key arrives (reconfiguration): the kept file is read and the issue goes away.
    hass.config_entries.async_update_entry(entry, data=entry.data | {"key": "ab" * 32})
    await hass.async_block_till_done()
    await async_wait_recording_done(hass)
    assert entry.runtime_data.data.files_processed == 1
    assert issues.async_get_issue(DOMAIN, f"undecryptable_{entry.entry_id}") is None


async def test_issue_when_no_file_arrives(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    entry = await setup(hass, tmp_path, options={"no_file_days": 2})
    issues = ir.async_get(hass)
    issue_id = f"no_file_{entry.entry_id}"
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    freezer.tick(timedelta(days=1, hours=23))
    await refresh(hass, entry)
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    freezer.tick(timedelta(hours=2))
    await refresh(hass, entry)
    issue = issues.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert (issue.severity, issue.translation_placeholders) == ("warning", {"count": "2"})

    drop(tmp_path, 1, s.r63_document())
    await refresh(hass, entry)
    assert issues.async_get_issue(DOMAIN, issue_id) is None

    # The delay then runs from the last file, and unloading removes what is left.
    freezer.tick(timedelta(days=3))
    await refresh(hass, entry)
    assert issues.async_get_issue(DOMAIN, issue_id) is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert issues.async_get_issue(DOMAIN, issue_id) is None


async def test_diagnostics_hide_secrets_and_meter_numbers(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path
) -> None:
    drop(tmp_path, 1, s.r63_document())
    (tmp_path / name(2, "R64A", "Index")).write_bytes(s.as_json(s.r64_document()))
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "source": "folder",
            "path": str(tmp_path),
            "key": s.KEY_HEX,
            "password": "not-a-real-password",
            "username": "user",
            "host": "h.example.invalid",
        },  # fmt: skip
        options={"prms": [s.PRM]},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(diagnostics)
    for secret in (s.KEY_HEX, s.PRM, "not-a-real-password", "h.example.invalid", str(tmp_path)):
        assert secret not in text
    assert diagnostics["entry"]["source"] == "folder"
    assert diagnostics["files_processed"] == 2
    (meter,) = diagnostics["meters"]
    assert meter["meter"] == "PRM 1"
    assert meter["natures"] == {"R": 287, "E": 1}
    assert meter["indexes"]["CONS|EA|D|D|HPH"] == {
        "timestamp": "2026-03-02T04:29:58", "unit": "Wh", "context": "FMR",
    }  # fmt: skip
