"""Diagnostics: configuration with secrets removed, state with PRM numbers replaced."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import EnedisConfigEntry
from .const import (
    CONF_DIRECTORY,
    CONF_HOST,
    CONF_KEY,
    CONF_MAILBOX,
    CONF_PASSWORD,
    CONF_PATH,
    CONF_PRMS,
    CONF_SENDER,
    CONF_USERNAME,
)

TO_REDACT = {
    CONF_KEY, CONF_PASSWORD, CONF_USERNAME, CONF_HOST, CONF_SENDER, CONF_PATH, CONF_MAILBOX,
    CONF_DIRECTORY, CONF_PRMS,
}  # fmt: skip


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnedisConfigEntry
) -> dict[str, Any]:
    data = entry.runtime_data.data
    prms = sorted(set(data.last_point) | set(data.indexes) | set(data.natures))
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "files_processed": data.files_processed,
        "last_file": data.last_file.isoformat() if data.last_file else None,
        "errors": data.errors,
        "meters": [
            {
                "meter": f"PRM {number}",
                "last_point": data.last_point[prm].isoformat() if prm in data.last_point else None,
                "natures": data.natures.get(prm, {}),
                "indexes": {
                    key: {k: v for k, v in value.items() if k in ("timestamp", "unit", "context")}
                    for key, value in data.indexes.get(prm, {}).items()
                },
            }
            for number, prm in enumerate(prms, start=1)
        ],
    }
