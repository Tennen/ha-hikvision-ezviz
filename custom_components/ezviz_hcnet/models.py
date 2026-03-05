"""Shared data models for ezviz_hcnet integration."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from .const import (
    DEFAULT_CHANNEL,
    DEFAULT_PORT,
    DEFAULT_PTZ_SPEED,
    DEFAULT_PTZ_STEP_MS,
    DEFAULT_RTSP_PATH,
    DEFAULT_RTSP_PORT,
)


@dataclass(slots=True)
class DeviceConfig:
    host: str
    port: int = DEFAULT_PORT
    username: str = ""
    password: str = ""
    channel: int = DEFAULT_CHANNEL
    rtsp_port: int = DEFAULT_RTSP_PORT
    rtsp_path: str = DEFAULT_RTSP_PATH
    ptz_default_speed: int = DEFAULT_PTZ_SPEED
    ptz_step_ms: int = DEFAULT_PTZ_STEP_MS
    sdk_lib_dir_override: str | None = None
    addon_base_url: str = ""

    def rtsp_url(self) -> str:
        try:
            path = self.rtsp_path.format(channel=self.channel)
        except Exception:
            path = self.rtsp_path

        if not path.startswith("/"):
            path = f"/{path}"

        username = quote(self.username, safe="")
        password = quote(self.password, safe="")
        return (
            f"rtsp://{username}:{password}@"
            f"{self.host}:{self.rtsp_port}{path}"
        )
