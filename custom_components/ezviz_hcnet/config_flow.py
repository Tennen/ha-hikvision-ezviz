"""Config flow for ezviz_hcnet."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ADDON_BASE_URL,
    CONF_CHANNEL,
    CONF_PTZ_DEFAULT_SPEED,
    CONF_PTZ_STEP_MS,
    CONF_RTSP_PATH,
    CONF_RTSP_PORT,
    CONF_SDK_LIB_DIR_OVERRIDE,
    DEFAULT_ADDON_BASE_URL,
    DEFAULT_CHANNEL,
    DEFAULT_PORT,
    DEFAULT_PTZ_SPEED,
    DEFAULT_PTZ_STEP_MS,
    DEFAULT_RTSP_PATH,
    DEFAULT_RTSP_PORT,
    DOMAIN,
)
from .backend_client import AddonApiError, async_probe_login

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, "")): str,
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
            vol.Required(CONF_CHANNEL, default=defaults.get(CONF_CHANNEL, DEFAULT_CHANNEL)): int,
            vol.Required(CONF_RTSP_PORT, default=defaults.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)): int,
            vol.Required(CONF_RTSP_PATH, default=defaults.get(CONF_RTSP_PATH, DEFAULT_RTSP_PATH)): str,
            vol.Required(
                CONF_ADDON_BASE_URL,
                default=defaults.get(CONF_ADDON_BASE_URL, DEFAULT_ADDON_BASE_URL),
            ): str,
            vol.Optional(
                CONF_SDK_LIB_DIR_OVERRIDE,
                default=defaults.get(CONF_SDK_LIB_DIR_OVERRIDE, ""),
            ): str,
            vol.Required(
                CONF_PTZ_DEFAULT_SPEED,
                default=defaults.get(CONF_PTZ_DEFAULT_SPEED, DEFAULT_PTZ_SPEED),
            ): int,
            vol.Required(
                CONF_PTZ_STEP_MS,
                default=defaults.get(CONF_PTZ_STEP_MS, DEFAULT_PTZ_STEP_MS),
            ): int,
        }
    )


class EzvizHcnetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ezviz_hcnet."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        sdk_error = "-"

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            user_input[CONF_HOST] = host
            channel = int(user_input[CONF_CHANNEL])
            unique_id = f"{host}:{user_input[CONF_PORT]}:ch{channel}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            sdk_override = (user_input.get(CONF_SDK_LIB_DIR_OVERRIDE) or "").strip() or None
            try:
                await async_probe_login(
                    self.hass,
                    addon_base_url=user_input[CONF_ADDON_BASE_URL],
                    host=host,
                    port=int(user_input[CONF_PORT]),
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    lib_dir_override=sdk_override,
                )
            except AddonApiError as err:
                _LOGGER.warning("Add-on validation failed during config flow: %s", err)
                errors["base"] = "cannot_connect"
                sdk_error = str(err)
            except Exception as err:  # pragma: no cover
                _LOGGER.exception("Unexpected error during config flow")
                errors["base"] = "unknown"
                sdk_error = str(err)

            if not errors:
                if not user_input.get(CONF_NAME):
                    user_input[CONF_NAME] = f"{host}-ch{channel}"
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
            description_placeholders={"sdk_error": sdk_error},
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return EzvizHcnetOptionsFlow(config_entry)


class EzvizHcnetOptionsFlow(config_entries.OptionsFlow):
    """Handle options for ezviz_hcnet."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_user_schema(data))
