"""Frontend panel registration for ezviz_hcnet."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from homeassistant.components import panel_custom
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, PANEL_BASE_PATH, STATIC_BASE_PATH, STATIC_MODULE_FILE

_LOGGER = logging.getLogger(__name__)


async def _ensure_static_path(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("static_registered"):
        return

    frontend_dir = Path(__file__).resolve().parent / "frontend"
    if not frontend_dir.exists():
        _LOGGER.warning("Frontend directory not found: %s", frontend_dir)
        return

    # Compatibility across HA versions
    if hasattr(hass.http, "register_static_path"):
        maybe_coro = hass.http.register_static_path(STATIC_BASE_PATH, str(frontend_dir), cache_headers=False)
        if asyncio.iscoroutine(maybe_coro):
            await maybe_coro
    else:
        # pragma: no cover - fallback for newer API variants
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_BASE_PATH, str(frontend_dir), False)]
        )

    data["static_registered"] = True


async def async_register_panel_for_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await _ensure_static_path(hass)

    data = hass.data.setdefault(DOMAIN, {})
    panel_path = f"{PANEL_BASE_PATH}-{entry.entry_id[:8]}"
    module_url = f"{STATIC_BASE_PATH}/{STATIC_MODULE_FILE}"

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="ezviz-hcnet-panel",
        frontend_url_path=panel_path,
        module_url=module_url,
        sidebar_title=entry.title,
        sidebar_icon="mdi:cctv",
        config={"entry_id": entry.entry_id},
        require_admin=False,
    )

    data.setdefault("panel_paths", {})[entry.entry_id] = panel_path


async def async_unregister_panel_for_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    panel_path = hass.data.get(DOMAIN, {}).get("panel_paths", {}).pop(entry.entry_id, None)
    if panel_path and hasattr(hass.components.frontend, "async_remove_panel"):
        result = hass.components.frontend.async_remove_panel(panel_path)
        if asyncio.iscoroutine(result):
            await result
