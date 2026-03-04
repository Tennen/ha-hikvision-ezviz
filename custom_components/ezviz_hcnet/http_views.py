"""HTTP views for ezviz_hcnet panel and APIs."""

from __future__ import annotations

from datetime import datetime

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .backend_client import AddonApiError
from .const import DOMAIN


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


def _hls_proxy_url(entry_id: str, session_id: str) -> str:
    return f"/api/{DOMAIN}/{entry_id}/playback/{session_id}/index.m3u8"


def _raise_from_addon_error(err: AddonApiError) -> None:
    message = str(err)
    if "(404)" in message:
        raise web.HTTPNotFound(text=message) from err
    if "(400)" in message:
        raise web.HTTPBadRequest(text=message) from err
    raise web.HTTPBadGateway(text=message) from err


async def async_register_http_views(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("http_views_registered"):
        return

    hass.http.register_view(EzvizHcnetStatusView(hass))
    hass.http.register_view(EzvizHcnetRecordingsView(hass))
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
        del request
        runtime = _runtime_or_404(self.hass, entry_id)
        try:
            payload = await runtime.client.async_status()
        except AddonApiError as err:
            _raise_from_addon_error(err)

        playback = payload.get("playback")
        if isinstance(playback, dict):
            session_id = str(playback.get("session_id", "")).strip()
            if session_id:
                playback["hls_url"] = _hls_proxy_url(entry_id, session_id)

        payload["entry_id"] = entry_id
        payload["ok"] = True
        return self.json(payload)


class EzvizHcnetRecordingsView(_BaseEzvizView):
    url = "/api/ezviz_hcnet/{entry_id}/recordings"
    name = "api:ezviz_hcnet:recordings"

    async def get(self, request: web.Request, entry_id: str) -> web.Response:
        runtime = _runtime_or_404(self.hass, entry_id)
        day = (request.query.get("date") or "").strip()
        if not day:
            raise web.HTTPBadRequest(text="date query is required (YYYY-MM-DD)")

        slot_minutes_raw = (request.query.get("slot_minutes") or "15").strip()
        try:
            slot_minutes = int(slot_minutes_raw)
        except ValueError as err:
            raise web.HTTPBadRequest(text="slot_minutes must be integer") from err

        try:
            payload = await runtime.client.async_list_recordings(day, slot_minutes=slot_minutes)
        except AddonApiError as err:
            _raise_from_addon_error(err)

        payload["ok"] = True
        payload["entry_id"] = entry_id
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
            payload = await runtime.client.async_playback_open(start, end)
        except AddonApiError as err:
            _raise_from_addon_error(err)

        session_id = str(payload.get("session_id", "")).strip()
        if not session_id:
            raise web.HTTPBadGateway(text="backend did not return session_id")

        return self.json(
            {
                "ok": True,
                "session_id": session_id,
                "hls_url": _hls_proxy_url(entry_id, session_id),
                "status": payload.get("status", "running"),
                "start": payload.get("start"),
                "end": payload.get("end"),
                "progress": payload.get("progress", 0),
                "last_error": payload.get("last_error"),
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
            payload = await runtime.client.async_playback_control(session_id, action, seek_percent)
        except AddonApiError as err:
            _raise_from_addon_error(err)

        return self.json(
            {
                "ok": True,
                "session_id": payload.get("session_id", session_id),
                "status": payload.get("status", "running"),
                "progress": payload.get("progress", 0),
            }
        )


class EzvizHcnetPlaybackCloseView(_BaseEzvizView):
    url = "/api/ezviz_hcnet/{entry_id}/playback/{session_id}"
    name = "api:ezviz_hcnet:playback_close"

    async def delete(self, request: web.Request, entry_id: str, session_id: str) -> web.Response:
        del request
        runtime = _runtime_or_404(self.hass, entry_id)
        try:
            payload = await runtime.client.async_playback_close(session_id)
        except AddonApiError as err:
            _raise_from_addon_error(err)

        return self.json(
            {
                "ok": True,
                "session_id": payload.get("session_id", session_id),
                "status": payload.get("status", "closed"),
            }
        )


class EzvizHcnetPlaybackIndexView(_BaseEzvizView):
    requires_auth = False
    url = "/api/ezviz_hcnet/{entry_id}/playback/{session_id}/index.m3u8"
    name = "api:ezviz_hcnet:playback_index"

    async def get(self, request: web.Request, entry_id: str, session_id: str) -> web.Response:
        del request
        runtime = _runtime_or_404(self.hass, entry_id)
        try:
            data, content_type = await runtime.client.async_fetch_playback_index(session_id)
        except AddonApiError as err:
            _raise_from_addon_error(err)

        return web.Response(body=data, headers={"Content-Type": content_type})


class EzvizHcnetPlaybackSegmentView(_BaseEzvizView):
    requires_auth = False
    url = "/api/ezviz_hcnet/{entry_id}/playback/{session_id}/{segment}"
    name = "api:ezviz_hcnet:playback_segment"

    async def get(self, request: web.Request, entry_id: str, session_id: str, segment: str) -> web.Response:
        del request
        runtime = _runtime_or_404(self.hass, entry_id)

        if "/" in segment or ".." in segment:
            raise web.HTTPBadRequest(text="invalid segment name")

        try:
            data, content_type = await runtime.client.async_fetch_playback_segment(session_id, segment)
        except AddonApiError as err:
            _raise_from_addon_error(err)

        return web.Response(body=data, headers={"Content-Type": content_type})
