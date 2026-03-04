"""HTTP views for ezviz_hcnet panel and APIs."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _runtime_or_404(hass: HomeAssistant, entry_id: str):
    runtime = hass.data.get(DOMAIN, {}).get("entries", {}).get(entry_id)
    if runtime is None:
        raise web.HTTPNotFound(text=f"entry '{entry_id}' not found")
    return runtime


def _session_or_404(runtime, session_id: str):
    session = runtime.playback.current
    if session is None or session.session_id != session_id:
        raise web.HTTPNotFound(text=f"playback session '{session_id}' not found")
    return session


async def async_register_http_views(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("http_views_registered"):
        return

    hass.http.register_view(EzvizHcnetStatusView(hass))
    hass.http.register_view(EzvizHcnetPlaybackOpenView(hass))
    hass.http.register_view(EzvizHcnetPlaybackControlView(hass))
    hass.http.register_view(EzvizHcnetPlaybackCloseView(hass))
    hass.http.register_view(EzvizHcnetPlaybackIndexView(hass))
    hass.http.register_view(EzvizHcnetPlaybackSegmentView(hass))

    data["http_views_registered"] = True


class _BaseEzvizView(HomeAssistantView):
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass


class EzvizHcnetStatusView(_BaseEzvizView):
    url = "/api/ezviz_hcnet/{entry_id}/status"
    name = "api:ezviz_hcnet:status"

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        runtime = _runtime_or_404(self.hass, entry_id)
        session = runtime.playback.current
        payload = {
            "ok": True,
            "entry_id": entry_id,
            "connected": runtime.client.available,
            "host": runtime.client.config.host,
            "channel": runtime.client.config.channel,
            "rtsp_url": runtime.client.rtsp_url(),
            "playback": None,
        }
        if session is not None:
            hls_url = f"/api/{DOMAIN}/{entry_id}/playback/{session.session_id}/index.m3u8"
            info = session.info(hls_url)
            progress = await runtime.client.async_run_in_executor(session.get_progress)
            payload["playback"] = {
                "session_id": info.session_id,
                "status": info.status,
                "hls_url": info.hls_url,
                "start": info.start.isoformat(),
                "end": info.end.isoformat(),
                "last_error": info.last_error,
                "progress": progress,
            }
        return self.json(payload)


class EzvizHcnetPlaybackOpenView(_BaseEzvizView):
    url = "/api/ezviz_hcnet/{entry_id}/playback/session"
    name = "api:ezviz_hcnet:playback_open"

    async def post(self, request: web.Request, entry_id: str) -> web.Response:
        runtime = _runtime_or_404(self.hass, entry_id)
        body = await request.json()

        start_raw = body.get("start")
        end_raw = body.get("end")
        if not start_raw or not end_raw:
            raise web.HTTPBadRequest(text="start and end are required")

        try:
            start = _parse_datetime(start_raw)
            end = _parse_datetime(end_raw)
        except ValueError as err:
            raise web.HTTPBadRequest(text=f"invalid datetime format: {err}") from err
        if end <= start:
            raise web.HTTPBadRequest(text="end must be later than start")

        try:
            session = await runtime.playback.async_open(start, end)
        except RuntimeError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        hls_url = f"/api/{DOMAIN}/{entry_id}/playback/{session.session_id}/index.m3u8"
        info = session.info(hls_url)

        return self.json(
            {
                "ok": True,
                "session_id": info.session_id,
                "hls_url": info.hls_url,
                "status": info.status,
                "start": info.start.isoformat(),
                "end": info.end.isoformat(),
            }
        )


class EzvizHcnetPlaybackControlView(_BaseEzvizView):
    url = "/api/ezviz_hcnet/{entry_id}/playback/{session_id}/control"
    name = "api:ezviz_hcnet:playback_control"

    async def post(self, request: web.Request, entry_id: str, session_id: str) -> web.Response:
        runtime = _runtime_or_404(self.hass, entry_id)
        body = await request.json()

        action = str(body.get("action", "")).strip().lower()
        if action not in {"play", "pause", "seek"}:
            raise web.HTTPBadRequest(text="action must be play|pause|seek")

        seek_percent = body.get("seek_percent")
        if action == "seek":
            if seek_percent is None:
                raise web.HTTPBadRequest(text="seek_percent is required when action=seek")
            seek_percent = float(seek_percent)

        try:
            await runtime.playback.async_control(session_id, action, seek_percent)
        except ValueError as err:
            raise web.HTTPBadRequest(text=str(err)) from err
        except RuntimeError as err:
            raise web.HTTPNotFound(text=str(err)) from err

        session = _session_or_404(runtime, session_id)
        hls_url = f"/api/{DOMAIN}/{entry_id}/playback/{session.session_id}/index.m3u8"
        info = session.info(hls_url)
        progress = await runtime.client.async_run_in_executor(session.get_progress)
        return self.json(
            {
                "ok": True,
                "session_id": info.session_id,
                "status": info.status,
                "progress": progress,
            }
        )


class EzvizHcnetPlaybackCloseView(_BaseEzvizView):
    url = "/api/ezviz_hcnet/{entry_id}/playback/{session_id}"
    name = "api:ezviz_hcnet:playback_close"

    async def delete(self, request: web.Request, entry_id: str, session_id: str) -> web.Response:
        runtime = _runtime_or_404(self.hass, entry_id)
        await runtime.playback.async_close(session_id)
        return self.json({"ok": True, "session_id": session_id, "status": "closed"})


class EzvizHcnetPlaybackIndexView(_BaseEzvizView):
    url = "/api/ezviz_hcnet/{entry_id}/playback/{session_id}/index.m3u8"
    name = "api:ezviz_hcnet:playback_index"

    async def get(self, request: web.Request, entry_id: str, session_id: str) -> web.Response:
        runtime = _runtime_or_404(self.hass, entry_id)
        session = _session_or_404(runtime, session_id)

        index_path = session.index_file
        if not index_path.exists():
            raise web.HTTPNotFound(text="HLS index is not ready")

        return web.FileResponse(path=index_path, headers={"Content-Type": "application/vnd.apple.mpegurl"})


class EzvizHcnetPlaybackSegmentView(_BaseEzvizView):
    url = "/api/ezviz_hcnet/{entry_id}/playback/{session_id}/{segment}"
    name = "api:ezviz_hcnet:playback_segment"

    async def get(self, request: web.Request, entry_id: str, session_id: str, segment: str) -> web.Response:
        runtime = _runtime_or_404(self.hass, entry_id)
        session = _session_or_404(runtime, session_id)

        if "/" in segment or ".." in segment:
            raise web.HTTPBadRequest(text="invalid segment name")

        file_path: Path = session.base_dir / segment
        if not file_path.exists() or not file_path.is_file():
            raise web.HTTPNotFound(text="segment not found")

        if segment.endswith(".m3u8"):
            content_type = "application/vnd.apple.mpegurl"
        elif segment.endswith(".ts"):
            content_type = "video/mp2t"
        elif segment.endswith(".mp4"):
            content_type = "video/mp4"
        else:
            content_type = "application/octet-stream"

        return web.FileResponse(path=file_path, headers={"Content-Type": content_type})
