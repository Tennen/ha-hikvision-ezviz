"""Entry lifecycle manager for EZVIZ HCNet backend service."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .playback import PlaybackSession, PlaybackSessionManager
from .sdk_client import DeviceConfig, HcNetSdkClient, HcNetSdkEnvironment

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ManagedEntry:
    entry_id: str
    config: DeviceConfig
    client: HcNetSdkClient
    playback: PlaybackSessionManager

    async def async_close(self) -> None:
        await self.playback.async_close()
        await self.client.async_close()


class EzvizBackendManager:
    """Manages SDK clients and playback sessions by entry id."""

    def __init__(self, *, default_lib_dir_override: str | None = None) -> None:
        self._default_lib_dir_override = default_lib_dir_override
        self._env: HcNetSdkEnvironment | None = None
        self._entries: dict[str, ManagedEntry] = {}
        self._lock = asyncio.Lock()

    async def async_connect(
        self,
        entry_id: str,
        config: DeviceConfig,
        *,
        lib_dir_override: str | None = None,
    ) -> dict:
        old = await self._pop_entry(entry_id)
        if old is not None:
            await old.async_close()
            await self._maybe_reset_env_if_empty()

        async with self._lock:
            env = self._ensure_env_locked(lib_dir_override)

        client = HcNetSdkClient(env, config, entry_id=entry_id)
        try:
            await client.async_connect()
        except Exception:
            await client.async_close()
            await self._maybe_reset_env_if_empty()
            raise

        managed = ManagedEntry(
            entry_id=entry_id,
            config=config,
            client=client,
            playback=PlaybackSessionManager(client, entry_id),
        )
        async with self._lock:
            self._entries[entry_id] = managed

        return await self.async_status(entry_id)

    async def async_disconnect(self, entry_id: str) -> None:
        managed = await self._pop_entry(entry_id)
        if managed is None:
            return
        await managed.async_close()
        await self._maybe_reset_env_if_empty()

    async def async_close_all(self) -> None:
        async with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
            self._env = None

        for managed in entries:
            try:
                await managed.async_close()
            except Exception:
                _LOGGER.exception("Failed to close entry %s", managed.entry_id)

    async def async_status(self, entry_id: str) -> dict:
        managed = await self._get_entry(entry_id)
        payload = {
            "ok": True,
            "entry_id": entry_id,
            "connected": managed.client.available,
            "host": managed.config.host,
            "channel": managed.config.channel,
            "rtsp_url": managed.config.rtsp_url(),
            "playback": None,
        }
        session = managed.playback.current
        if session is not None:
            progress = await managed.playback.async_get_progress(session.session_id)
            payload["playback"] = _session_payload(session, progress=progress)
        return payload

    async def async_ptz_move(
        self,
        entry_id: str,
        direction: str,
        speed: int | None,
        duration_ms: int | None,
    ) -> None:
        managed = await self._get_entry(entry_id)
        await managed.client.async_ptz_step(direction, speed, duration_ms)

    async def async_ptz_stop(self, entry_id: str, direction: str, speed: int | None) -> None:
        managed = await self._get_entry(entry_id)
        await managed.client.async_ptz_stop(direction, speed)

    async def async_playback_open(self, entry_id: str, start: datetime, end: datetime) -> dict:
        managed = await self._get_entry(entry_id)
        session = await managed.playback.async_open(start, end)
        progress = await managed.playback.async_get_progress(session.session_id)
        payload = _session_payload(session, progress=progress)
        payload["status"] = "running"
        return payload

    async def async_playback_control(
        self,
        entry_id: str,
        session_id: str,
        action: str,
        seek_percent: float | None,
    ) -> dict:
        managed = await self._get_entry(entry_id)
        session = await managed.playback.async_control(session_id, action, seek_percent)
        progress = await managed.playback.async_get_progress(session.session_id)
        payload = _session_payload(session, progress=progress)
        return payload

    async def async_playback_close(self, entry_id: str, session_id: str) -> dict:
        managed = await self._get_entry(entry_id)
        await managed.playback.async_close(session_id)
        return {
            "ok": True,
            "entry_id": entry_id,
            "session_id": session_id,
            "status": "closed",
        }

    async def async_get_playback_index_path(self, entry_id: str, session_id: str) -> Path:
        session = await self._get_session(entry_id, session_id)
        index_path = session.index_file
        if not index_path.exists():
            raise FileNotFoundError("HLS index is not ready")
        return index_path

    async def async_get_playback_segment_path(self, entry_id: str, session_id: str, segment: str) -> Path:
        if "/" in segment or ".." in segment:
            raise ValueError("invalid segment name")

        session = await self._get_session(entry_id, session_id)
        file_path = session.base_dir / segment
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError("segment not found")
        return file_path

    async def async_cleanup_stale(self) -> None:
        async with self._lock:
            entries = list(self._entries.values())

        for managed in entries:
            try:
                await managed.playback.async_cleanup_if_stale()
            except Exception:
                _LOGGER.exception("Failed cleanup for %s", managed.entry_id)

    async def _get_entry(self, entry_id: str) -> ManagedEntry:
        async with self._lock:
            managed = self._entries.get(entry_id)
        if managed is None:
            raise LookupError(f"entry '{entry_id}' not found")
        return managed

    async def _get_session(self, entry_id: str, session_id: str) -> PlaybackSession:
        managed = await self._get_entry(entry_id)
        session = managed.playback.current
        if session is None or session.session_id != session_id:
            raise LookupError(f"playback session '{session_id}' not found")
        return session

    async def _pop_entry(self, entry_id: str) -> ManagedEntry | None:
        async with self._lock:
            return self._entries.pop(entry_id, None)

    async def _maybe_reset_env_if_empty(self) -> None:
        async with self._lock:
            if not self._entries:
                self._env = None

    def _ensure_env_locked(self, lib_dir_override: str | None) -> HcNetSdkEnvironment:
        override = (lib_dir_override or self._default_lib_dir_override or "").strip() or None
        if self._env is None:
            self._env = HcNetSdkEnvironment(override)
            return self._env

        if override and override != self._env.lib_dir_override:
            _LOGGER.warning(
                "Ignored sdk lib dir override '%s' because SDK environment is already initialized with '%s'",
                override,
                self._env.lib_dir_override,
            )
        return self._env


def _session_payload(session: PlaybackSession, *, progress: int) -> dict:
    info = session.info()
    return {
        "session_id": info.session_id,
        "entry_id": info.entry_id,
        "start": info.start.isoformat(),
        "end": info.end.isoformat(),
        "status": info.status,
        "last_error": info.last_error,
        "created_at": info.created_at.isoformat(),
        "last_access": info.last_access.isoformat(),
        "progress": progress,
    }
