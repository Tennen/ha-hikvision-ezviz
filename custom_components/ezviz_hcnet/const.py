"""Constants for ezviz_hcnet integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "ezviz_hcnet"

PLATFORMS = ["camera", "button"]

CONF_NAME = "name"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_CHANNEL = "channel"
CONF_RTSP_PORT = "rtsp_port"
CONF_RTSP_PATH = "rtsp_path"
CONF_SDK_LIB_DIR_OVERRIDE = "sdk_lib_dir_override"
CONF_ADDON_BASE_URL = "addon_base_url"
CONF_PTZ_DEFAULT_SPEED = "ptz_default_speed"
CONF_PTZ_STEP_MS = "ptz_step_ms"

DEFAULT_PORT = 8000
DEFAULT_CHANNEL = 1
DEFAULT_RTSP_PORT = 554
DEFAULT_RTSP_PATH = "/Streaming/Channels/{channel}01"
DEFAULT_ADDON_BASE_URL = "http://127.0.0.1:8099"
DEFAULT_PTZ_SPEED = 4
DEFAULT_PTZ_STEP_MS = 400

SERVICE_PTZ_MOVE = "ptz_move"
SERVICE_PTZ_STOP = "ptz_stop"
SERVICE_PLAYBACK_OPEN = "playback_open"
SERVICE_PLAYBACK_CONTROL = "playback_control"
SERVICE_PLAYBACK_CLOSE = "playback_close"

ATTR_ENTRY_ID = "entry_id"
ATTR_DIRECTION = "direction"
ATTR_SPEED = "speed"
ATTR_DURATION_MS = "duration_ms"
ATTR_SESSION_ID = "session_id"
ATTR_ACTION = "action"
ATTR_SEEK_PERCENT = "seek_percent"
ATTR_START = "start"
ATTR_END = "end"

PLAYBACK_ACTION_PLAY = "play"
PLAYBACK_ACTION_PAUSE = "pause"
PLAYBACK_ACTION_SEEK = "seek"

PLAYBACK_SESSION_IDLE_TIMEOUT = timedelta(minutes=5)
PLAYBACK_SESSION_CLEANUP_INTERVAL = timedelta(seconds=30)

PANEL_BASE_PATH = "ezviz-hcnet"
STATIC_BASE_PATH = "/ezviz_hcnet_static"
STATIC_MODULE_FILE = "ezviz-hcnet-panel.js"

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
NET_DVR_SYSHEAD = 1
NET_DVR_STREAMDATA = 2
NET_DVR_AUDIOSTREAMDATA = 3

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

PTZ_BUTTON_DIRECTIONS = (
    "up",
    "down",
    "left",
    "right",
    "zoom_in",
    "zoom_out",
)
