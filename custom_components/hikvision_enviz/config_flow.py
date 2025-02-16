"""Config flow for Hikvision Enviz Camera integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult

from .const import DEFAULT_PORT, DEFAULT_USERNAME, DOMAIN
from .hikvision_api import HikvisionEnvizAPI

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

class HikvisionEnvizConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hikvision Enviz Camera."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            try:
                _LOGGER.debug("Testing connection with input: %s", user_input)
                api = HikvisionEnvizAPI(
                    host=user_input[CONF_HOST],
                    port=user_input[CONF_PORT],
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                )

                if await self.hass.async_add_executor_job(api.test_connection):
                    await self.async_set_unique_id(user_input[CONF_HOST])
                    self._abort_if_unique_id_configured()
                    
                    return self.async_create_entry(
                        title=f"Camera {user_input[CONF_HOST]}",
                        data=user_input,
                    )
                
                errors["base"] = "cannot_connect"
            except Exception as ex:
                _LOGGER.exception("Unexpected exception: %s", ex)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        ) 