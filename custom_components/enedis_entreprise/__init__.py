"""Enedis entreprise (R6X) — imports the files Enedis pushes (R63 load curve, R64 indexes)."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .api import InvalidKeyError, parse_key
from .const import (
    CONF_DIRECTORY,
    CONF_HOST,
    CONF_KEY,
    CONF_MAILBOX,
    CONF_PASSWORD,
    CONF_PATH,
    CONF_PORT,
    CONF_PRMS,
    CONF_SENDER,
    CONF_SOURCE,
    CONF_USERNAME,
    DOMAIN,
    SOURCE_FOLDER,
    SOURCE_FTPS,
    SOURCE_IMAP,
)
from .coordinator import EnedisCoordinator
from .sources import FolderSource, FtpsSource, ImapSource, Source

__all__ = ["DOMAIN", "async_setup_entry", "async_unload_entry", "build_source"]

type EnedisConfigEntry = ConfigEntry[EnedisCoordinator]


def build_source(data: dict[str, object]) -> Source:
    kind = data.get(CONF_SOURCE)
    if kind == SOURCE_FOLDER:
        return FolderSource(str(data[CONF_PATH]))
    if kind == SOURCE_IMAP:
        return ImapSource(
            str(data[CONF_HOST]),
            str(data[CONF_USERNAME]),
            str(data[CONF_PASSWORD]),
            port=int(str(data.get(CONF_PORT, 993))),
            mailbox=str(data.get(CONF_MAILBOX, "INBOX")),
            sender=str(data[CONF_SENDER]) if data.get(CONF_SENDER) else None,
        )
    if kind == SOURCE_FTPS:
        return FtpsSource(
            str(data[CONF_HOST]),
            str(data[CONF_USERNAME]),
            str(data[CONF_PASSWORD]),
            port=int(str(data.get(CONF_PORT, 21))),
            directory=str(data.get(CONF_DIRECTORY, "/")),
        )
    raise ConfigEntryError(f"unknown source type {kind!r}")


async def async_setup_entry(hass: HomeAssistant, entry: EnedisConfigEntry) -> bool:
    key = None
    if entry.data.get(CONF_KEY):
        try:
            key = parse_key(entry.data[CONF_KEY])
        except InvalidKeyError as err:
            raise ConfigEntryError(str(err)) from err
    prms = {str(prm) for prm in entry.options.get(CONF_PRMS, [])}
    coordinator = EnedisCoordinator(hass, entry, build_source(dict(entry.data)), key, prms)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnedisConfigEntry) -> bool:
    return True
