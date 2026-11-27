"""Config flow: choose where the Enedis files are read (folder, SFTP, FTPS) and give the key."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    FileSelector,
    FileSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from . import build_source
from .api import HistoryError, InvalidKeyError, parse_history_csv, parse_key
from .const import (
    CONF_DIRECTORY,
    CONF_HOST,
    CONF_HOST_KEY,
    CONF_KEY,
    CONF_NO_FILE_DAYS,
    CONF_OVERWRITE,
    CONF_PASSWORD,
    CONF_PATH,
    CONF_PORT,
    CONF_PRM,
    CONF_PRMS,
    CONF_SOURCE,
    CONF_USERNAME,
    DEFAULT_NO_FILE_DAYS,
    DOMAIN,
    SOURCE_FOLDER,
    SOURCE_FTPS,
    SOURCE_SFTP,
)
from .sources import SftpSource, SourceError

SECRETS = (CONF_KEY, CONF_PASSWORD)
CONF_FILE = "file"
_SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
_PORT = NumberSelector(NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX))
TITLES = {
    SOURCE_FOLDER: "Enedis (folder)",
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
        field(CONF_PORT, 22 if kind == SOURCE_SFTP else 21): _PORT,
        field(CONF_USERNAME): str,
        field(CONF_PASSWORD, required=secret): _SECRET,
        field(CONF_DIRECTORY, "/"): str,
    }
    if kind == SOURCE_SFTP:
        fields[field(CONF_HOST_KEY, required=False)] = str
    fields[field(CONF_KEY, required=secret)] = _SECRET
    return vol.Schema(fields)


def _unique_id(data: dict[str, Any]) -> str:
    if data[CONF_SOURCE] == SOURCE_FOLDER:
        return f"folder:{data[CONF_PATH]}"
    return f"{data[CONF_SOURCE]}:{data[CONF_HOST]}:{data[CONF_USERNAME]}:{data.get(CONF_DIRECTORY)}"


class EnedisConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EnedisOptionsFlow:
        return EnedisOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=[SOURCE_FOLDER, SOURCE_SFTP, SOURCE_FTPS]
        )

    async def async_step_folder(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_source(SOURCE_FOLDER, user_input)

    async def async_step_ftps(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_source(SOURCE_FTPS, user_input)

    async def async_step_sftp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_source(SOURCE_SFTP, user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Same form as at creation, e.g. after Enedis issued a new key for the channel."""
        kind = self._get_reconfigure_entry().data[CONF_SOURCE]
        if kind not in TITLES:  # the mailbox source of the development versions
            return self.async_abort(reason="mail_source_removed")
        return await self._async_source(kind, None)

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


def _is_prm(text: str) -> bool:
    return len(text) == 14 and text.isdigit()


def _read_history(hass: HomeAssistant, file_id: str) -> list[tuple[Any, int, int]]:
    """Parse the uploaded CSV; Home Assistant deletes the upload when the block ends."""
    with process_uploaded_file(hass, file_id) as path:
        return parse_history_csv(path.read_text(encoding="utf-8-sig"))


class EnedisOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["settings", "import_history"])

    async def async_step_import_history(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One-off import of a load curve exported from the Enedis portal (CSV upload)."""
        errors: dict[str, str] = {}
        coordinator = self.config_entry.runtime_data
        if user_input is not None:
            prm = user_input[CONF_PRM].strip()
            if not _is_prm(prm):
                errors[CONF_PRM] = "invalid_prm"
            else:
                try:
                    points = await self.hass.async_add_executor_job(
                        _read_history, self.hass, user_input[CONF_FILE]
                    )
                except (HistoryError, OSError, ValueError):
                    errors[CONF_FILE] = "history_unreadable"
                else:
                    result = await coordinator.async_import_history(
                        prm, points, user_input.get(CONF_OVERWRITE, False)
                    )
                    return self.async_abort(
                        reason="history_imported",
                        description_placeholders={k: str(v) for k, v in result.items()},
                    )
        known = sorted(coordinator.data.last_point) + self.config_entry.options.get(CONF_PRMS, [])
        schema = vol.Schema(
            {
                vol.Required(CONF_FILE): FileSelector(FileSelectorConfig(accept=".csv")),
                vol.Required(
                    CONF_PRM,
                    description={"suggested_value": known[0] if len(set(known)) == 1 else None},
                ): str,
                vol.Optional(CONF_OVERWRITE, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="import_history", data_schema=schema, errors=errors)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            prms = [part for part in user_input.get(CONF_PRMS, "").replace(",", " ").split()]
            if all(_is_prm(prm) for prm in prms):
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
        return self.async_show_form(step_id="settings", data_schema=schema, errors=errors)
