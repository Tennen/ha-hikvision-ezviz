"""HTTP client for EZVIZ HCNet add-on backend."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientTimeout

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .models import DeviceConfig

_REQUEST_TIMEOUT = ClientTimeout(total=30)


class AddonApiError(HomeAssistantError):
    """Add-on backend request failed."""


async def _response_error_text(resp: ClientResponse) -> str:
    try:
        payload = await resp.json(content_type=None)
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if detail:
                return str(detail)
        return str(payload)
    except Exception:
        text = await resp.text()
        return text.strip() or f"HTTP {resp.status}"


class AddonApiClient:
    """Low-level API transport to the add-on backend."""

    def __init__(self, hass: HomeAssistant, base_url: str) -> None:
        cleaned = base_url.strip().rstrip("/")
        if not cleaned:
            raise AddonApiError("addon_base_url is empty")

        self._base_url = cleaned
        self._session = async_get_clientsession(hass)

    async def request_json(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(method, url, json=json, timeout=_REQUEST_TIMEOUT) as resp:
                if resp.status >= 400:
                    detail = await _response_error_text(resp)
                    raise AddonApiError(f"{method.upper()} {path} failed ({resp.status}): {detail}")

                payload = await resp.json(content_type=None)
                if not isinstance(payload, dict):
                    raise AddonApiError(f"{method.upper()} {path} returned non-object JSON")
                return payload
        except AddonApiError:
            raise
        except asyncio.TimeoutError as err:
            raise AddonApiError(f"{method.upper()} {path} timed out") from err
        except ClientError as err:
            raise AddonApiError(f"{method.upper()} {path} failed to reach add-on: {err}") from err

    async def request_bytes(self, method: str, path: str) -> tuple[bytes, str]:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.request(method, url, timeout=_REQUEST_TIMEOUT) as resp:
                if resp.status >= 400:
                    detail = await _response_error_text(resp)
                    raise AddonApiError(f"{method.upper()} {path} failed ({resp.status}): {detail}")
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
                return await resp.read(), content_type
        except AddonApiError:
            raise
        except asyncio.TimeoutError as err:
            raise AddonApiError(f"{method.upper()} {path} timed out") from err
        except ClientError as err:
            raise AddonApiError(f"{method.upper()} {path} failed to reach add-on: {err}") from err


class AddonEntryClient:
    """Entry-scoped high-level client for add-on operations."""

    def __init__(self, hass: HomeAssistant, entry_id: str, config: DeviceConfig) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.config = config
        self._api = AddonApiClient(hass, config.addon_base_url)
        self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def rtsp_url(self) -> str:
        return self.config.rtsp_url()

    def _connect_payload(self) -> dict[str, Any]:
        return {
            "host": self.config.host,
            "port": int(self.config.port),
            "username": self.config.username,
            "password": self.config.password,
            "channel": int(self.config.channel),
            "rtsp_port": int(self.config.rtsp_port),
            "rtsp_path": self.config.rtsp_path,
            "ptz_default_speed": int(self.config.ptz_default_speed),
            "ptz_step_ms": int(self.config.ptz_step_ms),
            "lib_dir_override": (self.config.sdk_lib_dir_override or "").strip() or None,
        }

    async def async_connect(self) -> None:
        payload = await self._api.request_json(
            "post",
            f"/entries/{self.entry_id}/connect",
            json=self._connect_payload(),
        )
        self._available = bool(payload.get("connected", False))

    async def async_close(self) -> None:
        try:
            await self._api.request_json("delete", f"/entries/{self.entry_id}")
        finally:
            self._available = False

    async def async_status(self) -> dict[str, Any]:
        payload = await self._api.request_json("get", f"/entries/{self.entry_id}/status")
        self._available = bool(payload.get("connected", False))
        return payload

    async def async_ptz_step(self, direction: str, speed: int | None = None, duration_ms: int | None = None) -> None:
        await self._api.request_json(
            "post",
            f"/entries/{self.entry_id}/ptz/move",
            json={
                "direction": direction,
                "speed": speed,
                "duration_ms": duration_ms,
            },
        )

    async def async_ptz_stop(self, direction: str, speed: int | None = None) -> None:
        await self._api.request_json(
            "post",
            f"/entries/{self.entry_id}/ptz/stop",
            json={
                "direction": direction,
                "speed": speed,
            },
        )

    async def async_playback_open(self, start: datetime, end: datetime) -> dict[str, Any]:
        return await self._api.request_json(
            "post",
            f"/entries/{self.entry_id}/playback/session",
            json={
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )

    async def async_playback_control(self, session_id: str, action: str, seek_percent: float | None = None) -> dict[str, Any]:
        return await self._api.request_json(
            "post",
            f"/entries/{self.entry_id}/playback/{session_id}/control",
            json={
                "action": action,
                "seek_percent": seek_percent,
            },
        )

    async def async_playback_close(self, session_id: str) -> dict[str, Any]:
        return await self._api.request_json("delete", f"/entries/{self.entry_id}/playback/{session_id}")

    async def async_fetch_playback_index(self, session_id: str) -> tuple[bytes, str]:
        return await self._api.request_bytes(
            "get",
            f"/entries/{self.entry_id}/playback/{session_id}/index.m3u8",
        )

    async def async_fetch_playback_segment(self, session_id: str, segment: str) -> tuple[bytes, str]:
        return await self._api.request_bytes(
            "get",
            f"/entries/{self.entry_id}/playback/{session_id}/{segment}",
        )


async def async_probe_login(
    hass: HomeAssistant,
    *,
    addon_base_url: str,
    host: str,
    port: int,
    username: str,
    password: str,
    lib_dir_override: str | None,
) -> dict[str, Any]:
    """Validate add-on reachability and SDK login."""

    api = AddonApiClient(hass, addon_base_url)
    payload = await api.request_json(
        "post",
        "/probe_login",
        json={
            "host": host,
            "port": int(port),
            "username": username,
            "password": password,
            "lib_dir_override": (lib_dir_override or "").strip() or None,
        },
    )
    return dict(payload.get("result") or {})
