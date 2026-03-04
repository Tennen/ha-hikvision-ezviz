"""ezviz_hcnet integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval

try:  # pragma: no cover - compatibility with older HA
    from homeassistant.core import SupportsResponse
except ImportError:  # pragma: no cover
    SupportsResponse = None

from .const import (
    ATTR_ACTION,
    ATTR_DIRECTION,
    ATTR_DURATION_MS,
    ATTR_END,
    ATTR_ENTRY_ID,
    ATTR_SEEK_PERCENT,
    ATTR_SESSION_ID,
    ATTR_SPEED,
    ATTR_START,
    CONF_CHANNEL,
    CONF_PTZ_DEFAULT_SPEED,
    CONF_PTZ_STEP_MS,
    CONF_RTSP_PATH,
    CONF_RTSP_PORT,
    CONF_SDK_LIB_DIR_OVERRIDE,
    DEFAULT_CHANNEL,
    DEFAULT_PTZ_SPEED,
    DEFAULT_PTZ_STEP_MS,
    DEFAULT_RTSP_PATH,
    DEFAULT_RTSP_PORT,
    DOMAIN,
    PLAYBACK_ACTION_PAUSE,
    PLAYBACK_ACTION_PLAY,
    PLAYBACK_ACTION_SEEK,
    PLAYBACK_SESSION_CLEANUP_INTERVAL,
    PLATFORMS,
    PTZ_DIRECTION_TO_CMD,
    SERVICE_PLAYBACK_CLOSE,
    SERVICE_PLAYBACK_CONTROL,
    SERVICE_PLAYBACK_OPEN,
    SERVICE_PTZ_MOVE,
    SERVICE_PTZ_STOP,
)
from .http_views import async_register_http_views
from .panel import async_register_panel_for_entry, async_unregister_panel_for_entry
from .playback.session import PlaybackSessionManager
from .sdk.client import DeviceConfig, HcNetSdkClient, HcNetSdkEnvironment, SdkCallError
from .sdk.loader import SdkLoadError

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class EntryRuntime:
    client: HcNetSdkClient
    playback: PlaybackSessionManager


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _entry_config(entry: ConfigEntry) -> DeviceConfig:
    data: dict[str, Any] = {**entry.data, **entry.options}
    return DeviceConfig(
        host=data[CONF_HOST],
        port=int(data.get(CONF_PORT, 8000)),
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        channel=int(data.get(CONF_CHANNEL, DEFAULT_CHANNEL)),
        rtsp_port=int(data.get(CONF_RTSP_PORT, DEFAULT_RTSP_PORT)),
        rtsp_path=data.get(CONF_RTSP_PATH, DEFAULT_RTSP_PATH),
        ptz_default_speed=int(data.get(CONF_PTZ_DEFAULT_SPEED, DEFAULT_PTZ_SPEED)),
        ptz_step_ms=int(data.get(CONF_PTZ_STEP_MS, DEFAULT_PTZ_STEP_MS)),
    )


def _get_runtime(hass: HomeAssistant, entry_id: str) -> EntryRuntime:
    runtime = hass.data[DOMAIN]["entries"].get(entry_id)
    if runtime is None:
        raise HomeAssistantError(f"Entry runtime not found: {entry_id}")
    return runtime


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN].setdefault("entries", {})
    hass.data[DOMAIN].setdefault("env", None)
    hass.data[DOMAIN].setdefault("services_registered", False)

    await async_register_http_views(hass)

    if not hass.data[DOMAIN]["services_registered"]:
        _register_services(hass)
        hass.data[DOMAIN]["services_registered"] = True

    if "cleanup_unsub" not in hass.data[DOMAIN]:
        async def _cleanup_listener(now: datetime) -> None:
            del now
            for runtime in list(hass.data.get(DOMAIN, {}).get("entries", {}).values()):
                try:
                    await runtime.playback.async_cleanup_if_stale()
                except Exception:  # pragma: no cover
                    _LOGGER.exception("Failed to cleanup stale playback session")

        hass.data[DOMAIN]["cleanup_unsub"] = async_track_time_interval(
            hass,
            _cleanup_listener,
            PLAYBACK_SESSION_CLEANUP_INTERVAL,
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    override = (entry.options.get(CONF_SDK_LIB_DIR_OVERRIDE) or entry.data.get(CONF_SDK_LIB_DIR_OVERRIDE) or "").strip() or None

    env: HcNetSdkEnvironment | None = hass.data[DOMAIN].get("env")
    if env is None:
        env = HcNetSdkEnvironment(override)
        hass.data[DOMAIN]["env"] = env
    elif override:
        _LOGGER.warning("sdk_lib_dir_override is ignored for additional entries because SDK environment is already initialized")

    config = _entry_config(entry)
    client = HcNetSdkClient(hass, env, config)

    try:
        await client.async_connect()
    except (SdkLoadError, SdkCallError) as err:
        raise ConfigEntryNotReady(f"SDK init/login failed: {err}") from err

    runtime = EntryRuntime(client=client, playback=PlaybackSessionManager(hass, client, entry.entry_id))
    hass.data[DOMAIN]["entries"][entry.entry_id] = runtime

    await async_register_panel_for_entry(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    runtime = hass.data[DOMAIN]["entries"].pop(entry.entry_id, None)
    if runtime is not None:
        await runtime.playback.async_close()
        await runtime.client.async_close()

    if not hass.data[DOMAIN]["entries"]:
        hass.data[DOMAIN]["env"] = None

    await async_unregister_panel_for_entry(hass, entry)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    ptz_move_schema = vol.Schema(
        {
            vol.Required(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_DIRECTION): vol.In(tuple(PTZ_DIRECTION_TO_CMD.keys())),
            vol.Optional(ATTR_SPEED): vol.All(vol.Coerce(int), vol.Range(min=1, max=7)),
            vol.Optional(ATTR_DURATION_MS): vol.All(vol.Coerce(int), vol.Range(min=50, max=10000)),
        }
    )

    ptz_stop_schema = vol.Schema(
        {
            vol.Required(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_DIRECTION): vol.In(tuple(PTZ_DIRECTION_TO_CMD.keys())),
            vol.Optional(ATTR_SPEED): vol.All(vol.Coerce(int), vol.Range(min=1, max=7)),
        }
    )

    playback_open_schema = vol.Schema(
        {
            vol.Required(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_START): cv.string,
            vol.Required(ATTR_END): cv.string,
        }
    )

    playback_control_schema = vol.Schema(
        {
            vol.Required(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_SESSION_ID): cv.string,
            vol.Required(ATTR_ACTION): vol.In((PLAYBACK_ACTION_PLAY, PLAYBACK_ACTION_PAUSE, PLAYBACK_ACTION_SEEK)),
            vol.Optional(ATTR_SEEK_PERCENT): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
        }
    )

    playback_close_schema = vol.Schema(
        {
            vol.Required(ATTR_ENTRY_ID): cv.string,
            vol.Required(ATTR_SESSION_ID): cv.string,
        }
    )

    async def _handle_ptz_move(call: ServiceCall) -> None:
        runtime = _get_runtime(hass, call.data[ATTR_ENTRY_ID])
        await runtime.client.async_ptz_step(
            call.data[ATTR_DIRECTION],
            call.data.get(ATTR_SPEED),
            call.data.get(ATTR_DURATION_MS),
        )

    async def _handle_ptz_stop(call: ServiceCall) -> None:
        runtime = _get_runtime(hass, call.data[ATTR_ENTRY_ID])
        await runtime.client.async_ptz_stop(
            call.data[ATTR_DIRECTION],
            call.data.get(ATTR_SPEED),
        )

    async def _handle_playback_open(call: ServiceCall) -> dict[str, Any]:
        runtime = _get_runtime(hass, call.data[ATTR_ENTRY_ID])
        start = _parse_datetime(call.data[ATTR_START])
        end = _parse_datetime(call.data[ATTR_END])
        if end <= start:
            raise HomeAssistantError("end must be later than start")

        session = await runtime.playback.async_open(start, end)
        hls_url = f"/api/{DOMAIN}/{call.data[ATTR_ENTRY_ID]}/playback/{session.session_id}/index.m3u8"
        info = session.info(hls_url)
        return {
            "session_id": info.session_id,
            "hls_url": info.hls_url,
            "status": info.status,
        }

    async def _handle_playback_control(call: ServiceCall) -> None:
        runtime = _get_runtime(hass, call.data[ATTR_ENTRY_ID])
        action = call.data[ATTR_ACTION]
        seek_percent = call.data.get(ATTR_SEEK_PERCENT)
        await runtime.playback.async_control(call.data[ATTR_SESSION_ID], action, seek_percent)

    async def _handle_playback_close(call: ServiceCall) -> None:
        runtime = _get_runtime(hass, call.data[ATTR_ENTRY_ID])
        await runtime.playback.async_close(call.data[ATTR_SESSION_ID])

    hass.services.async_register(DOMAIN, SERVICE_PTZ_MOVE, _handle_ptz_move, schema=ptz_move_schema)
    hass.services.async_register(DOMAIN, SERVICE_PTZ_STOP, _handle_ptz_stop, schema=ptz_stop_schema)
    open_kwargs = {"schema": playback_open_schema}
    if SupportsResponse is not None:
        open_kwargs["supports_response"] = SupportsResponse.ONLY
    hass.services.async_register(DOMAIN, SERVICE_PLAYBACK_OPEN, _handle_playback_open, **open_kwargs)
    hass.services.async_register(DOMAIN, SERVICE_PLAYBACK_CONTROL, _handle_playback_control, schema=playback_control_schema)
    hass.services.async_register(DOMAIN, SERVICE_PLAYBACK_CLOSE, _handle_playback_close, schema=playback_close_schema)
