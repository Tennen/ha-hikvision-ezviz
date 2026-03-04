"""Constants for EZVIZ HCNet add-on backend."""

from __future__ import annotations

from datetime import timedelta

DEFAULT_PORT = 8000
DEFAULT_CHANNEL = 1
DEFAULT_RTSP_PORT = 554
DEFAULT_RTSP_PATH = "/Streaming/Channels/{channel}01"
DEFAULT_PTZ_SPEED = 4
DEFAULT_PTZ_STEP_MS = 400

PLAYBACK_SESSION_IDLE_TIMEOUT = timedelta(minutes=5)
PLAYBACK_SESSION_CLEANUP_INTERVAL = timedelta(seconds=30)

# SDK constants
NET_SDK_INIT_CFG_SDK_PATH = 2
NET_SDK_INIT_CFG_LIBEAY_PATH = 3
NET_SDK_INIT_CFG_SSLEAY_PATH = 4

NET_DVR_PLAYSTART = 1
NET_DVR_PLAYSTOP = 2
NET_DVR_PLAYPAUSE = 3
NET_DVR_PLAYRESTART = 4
NET_DVR_PLAYSETPOS = 12
NET_DVR_PLAYGETPOS = 13

NET_DVR_FILE_SUCCESS = 1000
NET_DVR_FILE_NOFIND = 1001
NET_DVR_ISFINDING = 1002
NET_DVR_NOMOREFILE = 1003

PTZ_DIRECTION_TO_CMD = {
    "up": 21,
    "down": 22,
    "left": 23,
    "right": 24,
    "up_left": 25,
    "up_right": 26,
    "down_left": 27,
    "down_right": 28,
    "zoom_in": 11,
    "zoom_out": 12,
    "focus_near": 13,
    "focus_far": 14,
}
