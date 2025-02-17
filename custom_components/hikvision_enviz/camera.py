"""Support for Hikvision Enviz Cameras."""
from __future__ import annotations

import logging
import asyncio
from typing import Any
import io

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    SUPPORT_STREAM,
    SUPPORT_PTZ,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from PIL import Image

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
        self._entry = entry
        self._attr_name = entry.title
        self._attr_unique_id = entry.entry_id
        self._attr_supported_features = SUPPORT_STREAM | SUPPORT_PTZ
        self._frame_interval = 1/30  # 30 FPS
        self._current_image = None

    async def _handle_frame(self, frame_data: bytes) -> None:
        """Handle incoming frame data."""
        try:
            # Convert frame data to image
            image = Image.open(io.BytesIO(frame_data))
            # Save as JPEG
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='JPEG')
            self._current_image = img_byte_arr.getvalue()
        except Exception as e:
            _LOGGER.error("Error processing frame: %s", str(e))

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera."""
        return self._current_image

    async def async_added_to_hass(self) -> None:
        """Handle entity addition to hass."""
        await self._api.connect()
        # Start streaming when added to hass
        await self._api.start_stream(self._handle_frame)

    async def async_will_remove_from_hass(self) -> None:
        """Handle entity removal from hass."""
        await self._api.stop_stream()
        await self._api.disconnect() 