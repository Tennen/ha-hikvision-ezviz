# ezviz_hcnet custom_component

Python Home Assistant custom component that uses HCNetSDK directly for:

- Live camera view via RTSP + HA Stream
- PTZ control (services + button entities)
- Timeline playback session (SDK callback -> ffmpeg -> temporary HLS)

## Requirements

- Home Assistant on Linux arm64/aarch64
- `ffmpeg` available in HA runtime
- Camera/NVR local account enabled for SDK (port 8000)
- RTSP enabled on device

## Install

1. Copy this folder into:
   - `/config/custom_components/ezviz_hcnet`
2. Restart Home Assistant.
3. Add integration from UI: `Settings -> Devices & Services -> Add Integration -> EZVIZ HCNet SDK`

## Default SDK path

The component loads bundled libraries from:

- `custom_components/ezviz_hcnet/lib/arm64`

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

- `/tmp/ezviz_hcnet/<session_id>`

No persistent recording files are kept.
