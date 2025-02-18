"""Support for Hikvision Enviz Cameras."""
from __future__ import annotations

import logging
import asyncio
from typing import Any
import io

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from PIL import Image
from homeassistant.helpers import entity_platform
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from . import DOMAIN
from .hikvision_api import HikvisionEnvizAPI

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool:
    """Set up Hikvision camera from a config entry."""
    api = hass.data[DOMAIN][entry.entry_id]
    
    # 注册 PTZ 服务
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "ptz_control",
        {
            vol.Optional("pan", default=0): vol.All(
                vol.Coerce(float), vol.Range(min=-1, max=1)
            ),
            vol.Optional("tilt", default=0): vol.All(
                vol.Coerce(float), vol.Range(min=-1, max=1)
            ),
            vol.Optional("zoom", default=0): vol.All(
                vol.Coerce(float), vol.Range(min=-1, max=1)
            ),
        },
        "ptz_control"
    )
    
    camera = HikvisionEnvizCamera(api, entry)
    async_add_entities([camera], True)
    return True

class HikvisionEnvizCamera(Camera):
    """Representation of a Hikvision Enviz Camera."""

    def __init__(self, api: HikvisionEnvizAPI, entry: ConfigEntry) -> None:
        """Initialize Hikvision Enviz Camera."""
        super().__init__()
        self._api = api
        self._entry = entry
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id
        self._attr_supported_features = CameraEntityFeature.ON_OFF | CameraEntityFeature.STREAM
        self._stream_handler = None

    @property
    def supported_features(self) -> int:
        """Return supported features."""
        return self._attr_supported_features

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image response from the camera."""
        return await self._api.async_camera_image()

    async def handle_async_mjpeg_stream(self, request):
        """Return an MJPEG stream."""
        if not self._stream_handler:
            self._stream_handler = await self.hass.async_add_executor_job(
                self._api.start_stream
            )
        return await self._stream_handler(request)

    async def async_turn_off(self):
        """Turn off camera."""
        if self._stream_handler:
            await self.hass.async_add_executor_job(self._api.stop_stream)
            self._stream_handler = None

    async def async_turn_on(self):
        """Turn on camera."""
        if not self._stream_handler:
            self._stream_handler = await self.hass.async_add_executor_job(
                self._api.start_stream
            )

    async def ptz_control(self, pan=0, tilt=0, zoom=0):
        """Handle PTZ service call."""
        try:
            await self.hass.async_add_executor_job(
                self._api.ptz_control, pan, tilt, zoom
            )
        except Exception as e:
            _LOGGER.error("Error controlling PTZ: %s", str(e)) 