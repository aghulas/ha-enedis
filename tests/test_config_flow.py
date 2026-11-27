from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.enedis_entreprise.const import DOMAIN
from custom_components.enedis_entreprise.sources import (
    FtpsSource,
    SftpSource,
    SourceError,
)

from . import synthetic as s

PASSWORD = "not-a-real-password"
SFTP = {
    "host": "sftp.example.invalid",
    "port": 22,
    "username": "user",
    "password": PASSWORD,
    "directory": "/in",
    "key": s.KEY_HEX,
}


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """SFTP and FTPS sources that answer without any network."""
    state: dict[str, Any] = {"fail": False, "checks": 0}

    def check(self: Any) -> None:
        state["checks"] += 1
        if state["fail"]:
            raise SourceError("unreachable")

    monkeypatch.setattr(SftpSource, "fingerprint", lambda self: "SHA256:first-seen")
    for source in (FtpsSource, SftpSource):
        monkeypatch.setattr(source, "check", check)
        monkeypatch.setattr(source, "poll", lambda self, known: [])
    return state


async def start(hass: HomeAssistant, kind: str) -> dict[str, Any]:
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert menu["type"] == "menu" and menu["menu_options"] == ["sftp", "folder", "ftps"]
    form = await hass.config_entries.flow.async_configure(menu["flow_id"], {"next_step_id": kind})
    assert (form["type"], form["step_id"]) == ("form", kind)
    return dict(form)


async def open_options(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> dict[str, Any]:
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    assert menu["type"] == "menu" and menu["menu_options"] == ["settings", "import_history"]
    form = await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": step}
    )
    assert (form["type"], form["step_id"]) == ("form", step)
    return dict(form)


async def test_folder(recorder_mock: Any, hass: HomeAssistant, tmp_path: Path) -> None:
    form = await start(hass, "folder")
    configure = hass.config_entries.flow.async_configure

    result = await configure(form["flow_id"], {"path": str(tmp_path / "absent")})
    assert result["errors"] == {"base": "cannot_connect"}
    result = await configure(form["flow_id"], {"path": str(tmp_path), "key": "abc"})
    assert result["errors"] == {"key": "invalid_key"}

    result = await configure(form["flow_id"], {"path": str(tmp_path), "key": s.KEY_HEX})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"] == {"source": "folder", "path": str(tmp_path), "key": s.KEY_HEX}
    assert result["result"].state is ConfigEntryState.LOADED

    # Same folder again, this time without a key (files already decrypted): refused as duplicate.
    again = await start(hass, "folder")
    result = await configure(again["flow_id"], {"path": str(tmp_path)})
    assert (result["type"], result["reason"]) == ("abort", "already_configured")


async def test_sftp_and_ftps(
    recorder_mock: Any, hass: HomeAssistant, remote: dict[str, Any]
) -> None:
    configure = hass.config_entries.flow.async_configure
    # SFTP: the host key shown at first contact is recorded with the entry.
    form = await start(hass, "sftp")
    remote["fail"] = True
    result = await configure(form["flow_id"], SFTP)
    assert result["errors"] == {"base": "cannot_connect"}
    remote["fail"] = False
    result = await configure(form["flow_id"], SFTP | {"port": 22.0, "host_key": ""})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"] == {"source": "sftp", "host_key": "SHA256:first-seen"} | SFTP
    assert result["result"].unique_id == "sftp:sftp.example.invalid:user:/in"

    form = await start(hass, "ftps")
    ftps = SFTP | {"port": 21}
    result = await configure(form["flow_id"], ftps)
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"] == {"source": "ftps"} | ftps


async def test_entry_with_the_removed_mailbox_source(
    recorder_mock: Any, hass: HomeAssistant
) -> None:
    """An entry made by a development version: refused with a repair issue, never a crash."""
    legacy = {
        "source": "imap",
        "host": "mail.example.invalid",
        "port": 993,
        "username": "user",
        "password": PASSWORD,
        "mailbox": "INBOX",
        "key": s.KEY_HEX,
    }
    entry = MockConfigEntry(domain=DOMAIN, data=legacy, unique_id="imap:old", title="Enedis")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    issues = ir.async_get(hass)
    issue = issues.async_get_issue(DOMAIN, f"mail_source_removed_{entry.entry_id}")
    assert issue is not None and issue.translation_key == "mail_source_removed"

    result = await entry.start_reconfigure_flow(hass)
    assert (result["type"], result["reason"]) == ("abort", "mail_source_removed")

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert issues.async_get_issue(DOMAIN, f"mail_source_removed_{entry.entry_id}") is None


async def test_reconfigure_keeps_secrets_left_empty(
    recorder_mock: Any, hass: HomeAssistant, remote: dict[str, Any]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"source": "sftp", "host_key": "SHA256:first-seen"} | SFTP,
        unique_id="sftp:old",
        title="Enedis",
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    form = await entry.start_reconfigure_flow(hass)
    assert (form["type"], form["step_id"]) == ("form", "sftp")
    # Secrets are never sent back to the browser.
    assert PASSWORD not in str(form["data_schema"].schema)
    assert s.KEY_HEX not in str(form["data_schema"].schema)

    new_key = "ab" * 32
    public = {k: v for k, v in SFTP.items() if k not in ("password", "key")}
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"],
        public | {"directory": "/enedis", "host_key": "SHA256:first-seen", "key": new_key},
    )
    await hass.async_block_till_done()
    assert (result["type"], result["reason"]) == ("abort", "reconfigure_successful")
    assert entry.data == {"source": "sftp", "host_key": "SHA256:first-seen"} | SFTP | {
        "directory": "/enedis",
        "key": new_key,
    }
    assert entry.data["password"] == PASSWORD


async def test_options(recorder_mock: Any, hass: HomeAssistant, tmp_path: Path) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"source": "folder", "path": str(tmp_path)})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    form = await open_options(hass, entry, "settings")
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"prms": "1234", "no_file_days": 5}
    )
    assert result["errors"] == {"prms": "invalid_prm"}
    result = await hass.config_entries.options.async_configure(
        form["flow_id"], {"prms": f"{s.PRM}, 00000000000043", "no_file_days": 5.0}
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options == {"prms": [s.PRM, "00000000000043"], "no_file_days": 5}
    # Saving options reloads the entry with them.
    assert entry.state is ConfigEntryState.LOADED

    form = await open_options(hass, entry, "settings")
    result = await hass.config_entries.options.async_configure(form["flow_id"], {"no_file_days": 3})
    assert entry.options == {"prms": [], "no_file_days": 3}


async def test_import_history_from_the_options(
    recorder_mock: Any, hass: HomeAssistant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from custom_components.enedis_entreprise import config_flow

    from .test_coordinator import rows
    from .test_history import export

    # The file selector hands over the id of the upload (a UUID), not a path.
    good, bad = "0123456789abcdef0123456789abcdef", "fedcba9876543210fedcba9876543210"
    uploads = {
        good: export(datetime(2026, 2, 28, 23, tzinfo=UTC), [6.0] * 288),
        bad: "not a history file\n",
    }

    @contextmanager
    def uploaded(hass: HomeAssistant, file_id: str) -> Any:
        path = tmp_path / f"{file_id}.csv"
        path.write_text(uploads[file_id])
        yield path

    monkeypatch.setattr(config_flow, "process_uploaded_file", uploaded)
    source = tmp_path / "source"
    source.mkdir()
    entry = MockConfigEntry(domain=DOMAIN, data={"source": "folder", "path": str(source)})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    configure = hass.config_entries.options.async_configure

    form = await open_options(hass, entry, "import_history")
    result = await configure(form["flow_id"], {"file": good, "prm": "123"})
    assert result["errors"] == {"prm": "invalid_prm"}
    result = await configure(form["flow_id"], {"file": bad, "prm": s.PRM})
    assert result["errors"] == {"file": "history_unreadable"}
    result = await configure(form["flow_id"], {"file": good, "prm": f" {s.PRM} "})
    assert (result["type"], result["reason"]) == ("abort", "history_imported")
    assert result["description_placeholders"] == {"points": "288", "hours": "24"}
    energy = await rows(hass)
    assert len(energy) == 24 and energy[-1]["sum"] == pytest.approx(144.0)
    # Importing does not touch the options, so the entry is not reloaded.
    assert entry.options == {}

    # The meter is now known: it is proposed in the form.
    form = await open_options(hass, entry, "import_history")
    marker = next(key for key in form["data_schema"].schema if key == "prm")
    assert marker.description == {"suggested_value": s.PRM}
