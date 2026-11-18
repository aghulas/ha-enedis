"""Config flow — placeholder until session 3 (source and key forms).

Home Assistant needs this module to load config entries at all; the user step only explains
that the integration cannot be configured from the interface yet.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class EnedisConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_abort(reason="not_ready")
