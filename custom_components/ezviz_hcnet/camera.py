"""Camera platform for ezviz_hcnet."""

from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CHANNEL, DOMAIN


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

    async def async_update(self) -> None:
        return
