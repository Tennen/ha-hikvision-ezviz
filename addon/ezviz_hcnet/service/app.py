"""FastAPI application for EZVIZ HCNet SDK backend."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .const import (
    DEFAULT_CHANNEL,
    DEFAULT_PORT,
    DEFAULT_PTZ_SPEED,
    DEFAULT_PTZ_STEP_MS,
    DEFAULT_RTSP_PATH,
    DEFAULT_RTSP_PORT,
    PLAYBACK_SESSION_CLEANUP_INTERVAL,
)
from .loader import SdkLoadError
from .manager import EzvizBackendManager
from .sdk_client import DeviceConfig, SdkCallError, probe_login

_LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


class ProbeRequest(BaseModel):
    host: str
    port: int = Field(default=DEFAULT_PORT, ge=1, le=65535)
    username: str
    password: str
    lib_dir_override: str | None = None


class ConnectRequest(ProbeRequest):
    channel: int = Field(default=DEFAULT_CHANNEL, ge=1)
    rtsp_port: int = Field(default=DEFAULT_RTSP_PORT, ge=1, le=65535)
    rtsp_path: str = DEFAULT_RTSP_PATH
    ptz_default_speed: int = Field(default=DEFAULT_PTZ_SPEED, ge=1, le=7)
    ptz_step_ms: int = Field(default=DEFAULT_PTZ_STEP_MS, ge=50, le=10000)


class PtzMoveRequest(BaseModel):
    direction: str
    speed: int | None = Field(default=None, ge=1, le=7)
    duration_ms: int | None = Field(default=None, ge=50, le=10000)


class PtzStopRequest(BaseModel):
    direction: str
    speed: int | None = Field(default=None, ge=1, le=7)


class PlaybackOpenRequest(BaseModel):
    start: str
    end: str


class PlaybackControlRequest(BaseModel):
    action: str
    seek_percent: float | None = Field(default=None, ge=0, le=100)


def _media_type_for(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".m3u8"):
        return "application/vnd.apple.mpegurl"
    if name.endswith(".ts"):
        return "video/mp2t"
    if name.endswith(".mp4"):
        return "video/mp4"
    return "application/octet-stream"


sdk_lib_dir = (os.environ.get("EZVIZ_SDK_LIB_DIR") or "").strip() or None
manager = EzvizBackendManager(default_lib_dir_override=sdk_lib_dir)
app = FastAPI(title="EZVIZ HCNet SDK Backend", version="0.1.0")
_cleanup_task: asyncio.Task | None = None


@app.on_event("startup")
async def _on_startup() -> None:
    global _cleanup_task

    async def _cleanup_loop() -> None:
        interval = PLAYBACK_SESSION_CLEANUP_INTERVAL.total_seconds()
        while True:
            await asyncio.sleep(interval)
            await manager.async_cleanup_stale()

    _cleanup_task = asyncio.create_task(_cleanup_loop())


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    global _cleanup_task
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
        _cleanup_task = None
    await manager.async_close_all()


def _error_400(message: str):
    return HTTPException(status_code=400, detail=message)


def _error_404(message: str):
    return HTTPException(status_code=404, detail=message)


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "ezviz_hcnet_backend"}


@app.post("/probe_login")
async def api_probe_login(body: ProbeRequest) -> dict:
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: probe_login(
                host=body.host,
                port=body.port,
                username=body.username,
                password=body.password,
                lib_dir_override=(body.lib_dir_override or "").strip() or None,
            ),
        )
    except (SdkLoadError, SdkCallError, RuntimeError, ValueError) as err:
        raise _error_400(str(err)) from err

    return {
        "ok": True,
        "result": result,
    }


@app.post("/entries/{entry_id}/connect")
async def api_connect(entry_id: str, body: ConnectRequest) -> dict:
    config = DeviceConfig(
        host=body.host.strip(),
        port=int(body.port),
        username=body.username,
        password=body.password,
        channel=int(body.channel),
        rtsp_port=int(body.rtsp_port),
        rtsp_path=body.rtsp_path,
        ptz_default_speed=int(body.ptz_default_speed),
        ptz_step_ms=int(body.ptz_step_ms),
    )

    try:
        return await manager.async_connect(
            entry_id,
            config,
            lib_dir_override=(body.lib_dir_override or "").strip() or None,
        )
    except (SdkLoadError, SdkCallError, RuntimeError, ValueError) as err:
        raise _error_400(str(err)) from err


@app.delete("/entries/{entry_id}")
async def api_disconnect(entry_id: str) -> dict:
    await manager.async_disconnect(entry_id)
    return {"ok": True, "entry_id": entry_id, "status": "disconnected"}


@app.get("/entries/{entry_id}/status")
async def api_status(entry_id: str) -> dict:
    try:
        return await manager.async_status(entry_id)
    except LookupError as err:
        raise _error_404(str(err)) from err


@app.get("/entries/{entry_id}/recordings")
async def api_recordings(
    entry_id: str,
    day: date = Query(..., alias="date"),
    slot_minutes: int = Query(default=60, ge=5, le=60),
) -> dict:
    try:
        return await manager.async_list_recordings(entry_id, day, slot_minutes=slot_minutes)
    except LookupError as err:
        raise _error_404(str(err)) from err
    except (RuntimeError, ValueError) as err:
        raise _error_400(str(err)) from err


@app.post("/entries/{entry_id}/ptz/move")
async def api_ptz_move(entry_id: str, body: PtzMoveRequest) -> dict:
    try:
        await manager.async_ptz_move(entry_id, body.direction, body.speed, body.duration_ms)
    except LookupError as err:
        raise _error_404(str(err)) from err
    except (SdkCallError, RuntimeError, ValueError) as err:
        raise _error_400(str(err)) from err

    return {"ok": True, "entry_id": entry_id}


@app.post("/entries/{entry_id}/ptz/stop")
async def api_ptz_stop(entry_id: str, body: PtzStopRequest) -> dict:
    try:
        await manager.async_ptz_stop(entry_id, body.direction, body.speed)
    except LookupError as err:
        raise _error_404(str(err)) from err
    except (SdkCallError, RuntimeError, ValueError) as err:
        raise _error_400(str(err)) from err

    return {"ok": True, "entry_id": entry_id}


@app.post("/entries/{entry_id}/playback/session")
async def api_playback_open(entry_id: str, body: PlaybackOpenRequest) -> dict:
    try:
        start = _parse_datetime(body.start)
        end = _parse_datetime(body.end)
        if end <= start:
            raise ValueError("end must be later than start")
        result = await manager.async_playback_open(entry_id, start, end)
        return {
            "ok": True,
            **result,
        }
    except LookupError as err:
        raise _error_404(str(err)) from err
    except (SdkCallError, RuntimeError, ValueError) as err:
        raise _error_400(str(err)) from err


@app.post("/entries/{entry_id}/playback/{session_id}/control")
async def api_playback_control(entry_id: str, session_id: str, body: PlaybackControlRequest) -> dict:
    try:
        result = await manager.async_playback_control(
            entry_id,
            session_id,
            body.action.strip().lower(),
            body.seek_percent,
        )
        return {
            "ok": True,
            **result,
        }
    except LookupError as err:
        raise _error_404(str(err)) from err
    except (SdkCallError, RuntimeError, ValueError) as err:
        raise _error_400(str(err)) from err


@app.delete("/entries/{entry_id}/playback/{session_id}")
async def api_playback_close(entry_id: str, session_id: str) -> dict:
    try:
        return await manager.async_playback_close(entry_id, session_id)
    except LookupError as err:
        raise _error_404(str(err)) from err


@app.get("/entries/{entry_id}/playback/{session_id}/index.m3u8")
async def api_playback_index(entry_id: str, session_id: str):
    try:
        path = await manager.async_get_playback_index_path(entry_id, session_id)
    except LookupError as err:
        raise _error_404(str(err)) from err
    except FileNotFoundError as err:
        raise _error_404(str(err)) from err

    return FileResponse(path=path, media_type="application/vnd.apple.mpegurl")


@app.get("/entries/{entry_id}/playback/{session_id}/{segment}")
async def api_playback_segment(entry_id: str, session_id: str, segment: str):
    try:
        path = await manager.async_get_playback_segment_path(entry_id, session_id, segment)
    except LookupError as err:
        raise _error_404(str(err)) from err
    except FileNotFoundError as err:
        raise _error_404(str(err)) from err
    except ValueError as err:
        raise _error_400(str(err)) from err

    return FileResponse(path=path, media_type=_media_type_for(path))
