# ezviz_hcnet custom_component

Python Home Assistant custom component that uses an add-on HCNetSDK backend for:

- Live camera view via RTSP + HA Stream
- PTZ control (services + button entities)
- Timeline playback session (SDK callback -> ffmpeg -> temporary HLS)

This integration now uses an external add-on backend process to run HCNetSDK
with glibc.

## Requirements

- Home Assistant on Linux arm64/aarch64
- EZVIZ HCNet SDK Backend add-on is installed and running
  - Default backend URL: `http://127.0.0.1:8099`
- Add-on runtime must provide glibc (`libc.so.6` and `ld-linux-aarch64.so.1`)
  - musl-based environments (for example Alpine-based containers) are not compatible with bundled SDK libs
- `ffmpeg` available in HA runtime
- Camera/NVR local account enabled for SDK (port 8000)
- RTSP enabled on device

## Install

1. Add this repository to Home Assistant add-on store custom repositories.
2. Install and start add-on: `EZVIZ HCNet SDK Backend`.
3. Copy this folder into:
   - `/config/custom_components/ezviz_hcnet`
4. Restart Home Assistant.
5. Add integration from UI: `Settings -> Devices & Services -> Add Integration -> EZVIZ HCNet SDK`
6. In config flow, set `Add-on backend URL` (use default unless you changed add-on networking).

## Backend SDK path

The add-on loads bundled libraries from:

- `/opt/ezviz/lib/arm64`

You can override this in config flow with `sdk_lib_dir_override`.

## Services

- `ezviz_hcnet.ptz_move`
- `ezviz_hcnet.ptz_stop`
- `ezviz_hcnet.playback_open`
- `ezviz_hcnet.playback_control`
- `ezviz_hcnet.playback_close`

## Playback panel

Each config entry registers a sidebar panel path:

- `ezviz-hcnet-<entry_id_prefix>`

Panel calls backend API under:

- `/api/ezviz_hcnet/{entry_id}/...`

Playback HLS files are temporary under:

- `/tmp/ezviz_hcnet/<entry_id>/<session_id>`

No persistent recording files are kept.
