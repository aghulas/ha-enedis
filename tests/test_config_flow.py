from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.enedis_entreprise.const import DOMAIN
from custom_components.enedis_entreprise.sources import (
    FtpsSource,
    ImapSource,
    SftpSource,
    SourceError,
)

from . import synthetic as s

PASSWORD = "not-a-real-password"
IMAP = {
    "host": "mail.example.invalid",
    "port": 993,
    "username": "user",
    "password": PASSWORD,
    "mailbox": "INBOX",
    "key": s.KEY_HEX,
}


@pytest.fixture
def remote(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """IMAP and FTPS sources that answer without any network."""
    state: dict[str, Any] = {"fail": False, "checks": 0}

    def check(self: Any) -> None:
        state["checks"] += 1
        if state["fail"]:
            raise SourceError("unreachable")

    monkeypatch.setattr(SftpSource, "fingerprint", lambda self: "SHA256:first-seen")
    for source in (ImapSource, FtpsSource, SftpSource):
        monkeypatch.setattr(source, "check", check)
        monkeypatch.setattr(source, "poll", lambda self, known: [])
    return state


async def start(hass: HomeAssistant, kind: str) -> dict[str, Any]:
    menu = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert menu["type"] == "menu" and menu["menu_options"] == ["imap", "folder", "sftp", "ftps"]
    form = await hass.config_entries.flow.async_configure(menu["flow_id"], {"next_step_id": kind})
    assert (form["type"], form["step_id"]) == ("form", kind)
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


async def test_imap_and_ftps(
    recorder_mock: Any, hass: HomeAssistant, remote: dict[str, Any]
) -> None:
    configure = hass.config_entries.flow.async_configure
    form = await start(hass, "imap")
    remote["fail"] = True
    result = await configure(form["flow_id"], IMAP)
    assert result["errors"] == {"base": "cannot_connect"}
    remote["fail"] = False
    result = await configure(form["flow_id"], IMAP | {"port": 993.0, "sender": ""})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"] == {"source": "imap"} | IMAP

    form = await start(hass, "ftps")
    ftps = {k: v for k, v in IMAP.items() if k != "mailbox"} | {"port": 21, "directory": "/in"}
    result = await configure(form["flow_id"], ftps)
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"] == {"source": "ftps"} | ftps

    # SFTP: the host key shown at first contact is recorded with the entry.
    form = await start(hass, "sftp")
    result = await configure(form["flow_id"], ftps | {"port": 22})
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"] == {"source": "sftp", "host_key": "SHA256:first-seen"} | ftps | {
        "port": 22
    }


async def test_reconfigure_keeps_secrets_left_empty(
    recorder_mock: Any, hass: HomeAssistant, remote: dict[str, Any]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data={"source": "imap"} | IMAP, unique_id="imap:old", title="Enedis"
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    form = await entry.start_reconfigure_flow(hass)
    assert (form["type"], form["step_id"]) == ("form", "imap")
    # Secrets are never sent back to the browser.
    assert PASSWORD not in str(form["data_schema"].schema)
    assert s.KEY_HEX not in str(form["data_schema"].schema)

    new_key = "ab" * 32
    public = {k: v for k, v in IMAP.items() if k not in ("password", "key")}
    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], public | {"mailbox": "Enedis", "key": new_key}
    )
    await hass.async_block_till_done()
    assert (result["type"], result["reason"]) == ("abort", "reconfigure_successful")
    assert entry.data == {"source": "imap"} | IMAP | {"mailbox": "Enedis", "key": new_key}
    assert entry.data["password"] == PASSWORD


async def test_options(recorder_mock: Any, hass: HomeAssistant, tmp_path: Path) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"source": "folder", "path": str(tmp_path)})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert form["step_id"] == "init"
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

    form = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(form["flow_id"], {"no_file_days": 3})
    assert entry.options == {"prms": [], "no_file_days": 3}
