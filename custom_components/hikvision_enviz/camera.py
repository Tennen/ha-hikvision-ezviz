"""Support for Hikvision Enviz cameras."""
from __future__ import annotations

import logging
import asyncio
import io
from typing import Any

from homeassistant.components.camera import Camera, DynamicStreamSettings
from homeassistant.components.stream import (
    CONF_USE_WALLCLOCK_AS_TIMESTAMPS,
    create_stream,
)
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
    """Set up Hikvision Enviz Camera from a config entry."""
    api: HikvisionEnvizAPI = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HikvisionEnvizCamera(hass, api, entry)], True)

class StreamBuffer(io.IOBase):
    """Buffer that implements read interface for PyAV."""
    
    def __init__(self):
        """Initialize stream buffer."""
        self._buffer = bytearray()
        self._lock = asyncio.Lock()
        
    def write(self, data):
        """Write data to buffer."""
        self._buffer.extend(data)
        return len(data)
        
    def read(self, size=-1):
        """Read data from buffer."""
        if size == -1:
            size = len(self._buffer)
        if not self._buffer:
            return b""
        ret = bytes(self._buffer[:size])
        del self._buffer[:size]
        return ret
        
    def readable(self):
        """Return True as this buffer is readable."""
        return True

class HikvisionEnvizCamera(Camera):
    """An implementation of a Hikvision Enviz camera."""

    def __init__(self, hass: HomeAssistant, api: HikvisionEnvizAPI, entry: ConfigEntry) -> None:
        """Initialize Hikvision Enviz camera."""
        super().__init__()
        self.hass = hass
        self._api = api
        self._attr_unique_id = f"{entry.entry_id}_camera"
        self._attr_name = f"Camera {api._host}"
        self._stream = None
        self._stream_buffer = StreamBuffer()
        self._running = True
        
        # Stream options
        self.stream_options = {
            CONF_USE_WALLCLOCK_AS_TIMESTAMPS: True,
        }

    async def _get_stream_source(self):
        """Get stream source from Hikvision API."""
        def stream_callback(data_type, data):
            """Callback to receive stream data."""
            if data_type == 2:  # NET_DVR_STREAMDATA
                self._stream_buffer.write(data)

        # 确保在正确的事件循环中运行
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._api.start_stream,
            stream_callback
        )
        
        return self._stream_buffer

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image response from the camera."""
        try:
            if self._stream is None:
                source = await self._get_stream_source()
                self._stream = create_stream(
                    self.hass,
                    source,
                    self.stream_options,
                    DynamicStreamSettings()
                )
            return await self._stream.async_get_image()
        except Exception as err:
            _LOGGER.error("Error getting camera image: %s", err)
            return None

    async def async_handle_web_rtc_offer(self, offer_sdp: str) -> str | None:
        """Handle the WebRTC offer and return an answer."""
        try:
            if not self._stream:
                source = await self._get_stream_source()
                self._stream = create_stream(
                    self.hass,
                    source,
                    self.stream_options,
                    DynamicStreamSettings()
                )
            return await self._stream.async_handle_web_rtc_offer(offer_sdp)
        except Exception as err:
            _LOGGER.error("Error handling WebRTC offer: %s", err)
            return None

    async def async_will_remove_from_hass(self) -> None:
        """Cleanup when entity is removed."""
        self._running = False
        if self._stream:
            await self._stream.stop()
            self._stream = None
        
        # 确保在正确的事件循环中停止流
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._api.stop_stream) 