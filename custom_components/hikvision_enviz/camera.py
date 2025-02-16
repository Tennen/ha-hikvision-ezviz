"""Support for Hikvision Enviz Cameras."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .hikvision_api import HikvisionEnvizAPI

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Hikvision Enviz Camera from config entry."""
    api = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HikvisionEnvizCamera(api, entry)], True)

class HikvisionEnvizCamera(Camera):
    """Representation of a Hikvision Enviz Camera."""

    def __init__(self, api: HikvisionEnvizAPI, entry: ConfigEntry) -> None:
        """Initialize Hikvision Enviz Camera."""
        super().__init__()
        self._api = api
        self._attr_name = f"Hikvision Enviz {entry.title}"
        self._attr_unique_id = entry.entry_id
        self._attr_supported_features = (
            CameraEntityFeature.STREAM | 
            CameraEntityFeature.PTZ
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera."""
        return await self._api.get_snapshot()

    async def async_stream_source(self) -> str | None:
        """Return the stream source."""
        return await self._api.get_stream_url()

    async def async_added_to_hass(self) -> None:
        """Handle entity addition to hass."""
        await self._api.connect()

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal from hass."""
        await self._api.disconnect() 