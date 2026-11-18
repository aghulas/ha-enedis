"""Config flow: choose where the Enedis files arrive (folder, mailbox, FTPS) and give the key."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import build_source
from .api import InvalidKeyError, parse_key
from .const import (
    CONF_DIRECTORY,
    CONF_HOST,
    CONF_HOST_KEY,
    CONF_KEY,
    CONF_MAILBOX,
    CONF_NO_FILE_DAYS,
    CONF_PASSWORD,
    CONF_PATH,
    CONF_PORT,
    CONF_PRMS,
    CONF_SENDER,
    CONF_SOURCE,
    CONF_USERNAME,
    DEFAULT_NO_FILE_DAYS,
    DOMAIN,
    SOURCE_FOLDER,
    SOURCE_FTPS,
    SOURCE_IMAP,
    SOURCE_SFTP,
)
from .sources import SftpSource, SourceError

SECRETS = (CONF_KEY, CONF_PASSWORD)
_SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_PORT = NumberSelector(NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX))
TITLES = {
    SOURCE_FOLDER: "Enedis (folder)",
    SOURCE_IMAP: "Enedis (mailbox)",
    SOURCE_FTPS: "Enedis (FTPS)",
    SOURCE_SFTP: "Enedis (SFTP)",
}


def _schema(kind: str, defaults: dict[str, Any], *, secrets_optional: bool) -> vol.Schema:
    """Form of one source. On reconfiguration, secrets left empty keep their current value."""

    def field(name: str, default: Any = None, *, required: bool = True) -> vol.Marker:
        marker = vol.Required if required else vol.Optional
        value = defaults.get(name, default)
        if value is None or name in SECRETS:
            return marker(name)
        return marker(name, description={"suggested_value": value})

    secret = not secrets_optional
    if kind == SOURCE_FOLDER:
        return vol.Schema({field(CONF_PATH): str, field(CONF_KEY, required=False): _SECRET})
    fields: dict[vol.Marker, Any] = {
        field(CONF_HOST): str,
        field(CONF_PORT, {SOURCE_IMAP: 993, SOURCE_SFTP: 22}.get(kind, 21)): _PORT,
        field(CONF_USERNAME): str,
        field(CONF_PASSWORD, required=secret): _SECRET,
    }
    if kind == SOURCE_IMAP:
        fields[field(CONF_MAILBOX, "INBOX")] = str
        fields[field(CONF_SENDER, required=False)] = str
    else:
        fields[field(CONF_DIRECTORY, "/")] = str
    if kind == SOURCE_SFTP:
        fields[field(CONF_HOST_KEY, required=False)] = str
    fields[field(CONF_KEY, required=secret)] = _SECRET
    return vol.Schema(fields)


def _unique_id(data: dict[str, Any]) -> str:
    if data[CONF_SOURCE] == SOURCE_FOLDER:
        return f"folder:{data[CONF_PATH]}"
    place = data.get(CONF_MAILBOX) or data.get(CONF_DIRECTORY)
    return f"{data[CONF_SOURCE]}:{data[CONF_HOST]}:{data[CONF_USERNAME]}:{place}"


class EnedisConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EnedisOptionsFlow:
        return EnedisOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=[SOURCE_IMAP, SOURCE_FOLDER, SOURCE_SFTP, SOURCE_FTPS]
        )

    async def async_step_folder(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_source(SOURCE_FOLDER, user_input)

    async def async_step_imap(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_source(SOURCE_IMAP, user_input)

    async def async_step_ftps(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_source(SOURCE_FTPS, user_input)

    async def async_step_sftp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_source(SOURCE_SFTP, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Same form as at creation, e.g. after Enedis issued a new key for the channel."""
        return await self._async_source(self._get_reconfigure_entry().data[CONF_SOURCE], None)

    async def _async_source(self, kind: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        current = dict(self._get_reconfigure_entry().data) if self.source == "reconfigure" else {}
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_SOURCE: kind} | {
                k: v for k, v in user_input.items() if v not in ("", None)
            }
            if CONF_PORT in data:
                data[CONF_PORT] = int(data[CONF_PORT])
            for name in SECRETS:
                if name not in data and name in current:
                    data[name] = current[name]
            errors = await self._async_check(data)
            if not errors and current:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data=data, unique_id=_unique_id(data)
                )
            if not errors:
                await self.async_set_unique_id(_unique_id(data))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=TITLES[kind], data=data)
        shown = {k: v for k, v in (current | (user_input or {})).items() if k not in SECRETS}
        return self.async_show_form(
            step_id=kind,
            data_schema=_schema(kind, shown, secrets_optional=bool(current)),
            errors=errors,
        )

    async def _async_check(self, data: dict[str, Any]) -> dict[str, str]:
        """The key must be well formed and the source reachable. Nothing is logged."""
        if data.get(CONF_KEY):
            try:
                parse_key(data[CONF_KEY])
            except InvalidKeyError:
                return {CONF_KEY: "invalid_key"}
        try:
            source = build_source(data)
            if isinstance(source, SftpSource) and not data.get(CONF_HOST_KEY):
                # First contact: the server's key is recorded and required from now on.
                data[CONF_HOST_KEY] = await self.hass.async_add_executor_job(source.fingerprint)
                source = build_source(data)
            await self.hass.async_add_executor_job(source.check)
        except SourceError:
            return {"base": "cannot_connect"}
        return {}


class EnedisOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            prms = [part for part in user_input.get(CONF_PRMS, "").replace(",", " ").split()]
            if all(len(prm) == 14 and prm.isdigit() for prm in prms):
                return self.async_create_entry(
                    data={CONF_PRMS: prms, CONF_NO_FILE_DAYS: int(user_input[CONF_NO_FILE_DAYS])}
                )
            errors[CONF_PRMS] = "invalid_prm"
        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_PRMS,
                    description={"suggested_value": ", ".join(options.get(CONF_PRMS, []))},
                ): str,
                vol.Required(
                    CONF_NO_FILE_DAYS,
                    default=options.get(CONF_NO_FILE_DAYS, DEFAULT_NO_FILE_DAYS),
                ): NumberSelector(NumberSelectorConfig(min=1, max=60, mode=NumberSelectorMode.BOX)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
