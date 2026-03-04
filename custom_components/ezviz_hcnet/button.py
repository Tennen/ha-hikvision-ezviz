"""Button entities for quick PTZ steps."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PTZ_BUTTON_DIRECTIONS

_DIRECTION_NAME = {
    "up": "PTZ Up",
    "down": "PTZ Down",
    "left": "PTZ Left",
    "right": "PTZ Right",
    "zoom_in": "PTZ Zoom In",
    "zoom_out": "PTZ Zoom Out",
}

_DIRECTION_ICON = {
    "up": "mdi:arrow-up-bold",
    "down": "mdi:arrow-down-bold",
    "left": "mdi:arrow-left-bold",
    "right": "mdi:arrow-right-bold",
    "zoom_in": "mdi:magnify-plus-outline",
    "zoom_out": "mdi:magnify-minus-outline",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    runtime = hass.data[DOMAIN]["entries"][entry.entry_id]
    entities = [
        EzvizHcnetPtzButton(entry.entry_id, runtime.client, direction)
        for direction in PTZ_BUTTON_DIRECTIONS
    ]
    async_add_entities(entities, update_before_add=False)


class EzvizHcnetPtzButton(ButtonEntity):
    """One PTZ direction button."""

    _attr_has_entity_name = True

    def __init__(self, entry_id: str, client, direction: str) -> None:
        self._entry_id = entry_id
        self._client = client
        self._direction = direction
        self._attr_name = _DIRECTION_NAME[direction]
        self._attr_icon = _DIRECTION_ICON[direction]
        self._attr_unique_id = f"{entry_id}_ptz_{direction}"

    @property
    def available(self) -> bool:
        return self._client.available

    async def async_press(self) -> None:
        await self._client.async_ptz_step(self._direction)
