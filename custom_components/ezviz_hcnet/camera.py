"""Camera platform for ezviz_hcnet."""

from __future__ import annotations

import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHANNEL, DOMAIN

_LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - depends on HA version
    from homeassistant.components.stream import StreamType
except ImportError:  # pragma: no cover
    StreamType = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = hass.data[DOMAIN]["entries"][entry.entry_id]
    async_add_entities([EzvizHcnetCamera(entry, runtime.client)], update_before_add=False)


class EzvizHcnetCamera(Camera):
    """EZVIZ camera backed by HA Stream via RTSP URL."""

    _attr_has_entity_name = True
    _attr_name = "live"
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_use_stream_for_stills = True
    if StreamType is not None:  # pragma: no cover - depends on HA version
        _attr_frontend_stream_type = StreamType.HLS

    def __init__(self, entry: ConfigEntry, client) -> None:
        super().__init__()
        self._entry = entry
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_live"

    @property
    def available(self) -> bool:
        return self._client.available

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        return {
            "host": self._client.config.host,
            "channel": self._client.config.channel,
            "entry_id": self._entry.entry_id,
        }

    async def stream_source(self) -> str:
        return self._client.rtsp_url()

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        source = await self.stream_source()
        if not source:
            return None

        image_fetchers = []
        try:  # pragma: no cover - depends on HA version
            from homeassistant.components.stream import async_get_image as stream_async_get_image

            image_fetchers.append(stream_async_get_image)
        except ImportError:
            pass

        try:  # pragma: no cover - depends on HA version
            from homeassistant.components.camera import async_get_image as camera_async_get_image

            image_fetchers.append(camera_async_get_image)
        except ImportError:
            pass

        if not image_fetchers:
            _LOGGER.debug("No async_get_image helper found in current Home Assistant version")
            return None

        try:
            for fetcher in image_fetchers:
                image = await fetcher(self.hass, source, width=width, height=height)
                if isinstance(image, (bytes, bytearray)):
                    return bytes(image)
                content = getattr(image, "content", None)
                if isinstance(content, (bytes, bytearray)):
                    return bytes(content)
        except Exception:  # pragma: no cover - depends on runtime stream backend
            _LOGGER.debug("Failed to fetch still image from stream source", exc_info=True)
            return None

        return None

    async def async_update(self) -> None:
        return
