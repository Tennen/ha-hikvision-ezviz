"""The Hikvision Enviz Camera integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .hikvision_api import HikvisionEnvizAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CAMERA]

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Hikvision Enviz component."""
    hass.data.setdefault(DOMAIN, {})
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hikvision Enviz Camera from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    api = HikvisionEnvizAPI(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )

    try:
        if not await api.connect():
            return False
    except Exception as e:
        _LOGGER.error("Failed to connect to Hikvision camera: %s", str(e))
        return False

    hass.data[DOMAIN][entry.entry_id] = api

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        api = hass.data[DOMAIN].pop(entry.entry_id)
        await api.disconnect()

    return unload_ok 