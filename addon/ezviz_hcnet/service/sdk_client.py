"""HCNetSDK client wrappers for add-on backend."""

from __future__ import annotations

import asyncio
import ctypes as C
import logging
import threading
import time as pytime
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path
from urllib.parse import quote

from .const import (
    DEFAULT_PTZ_SPEED,
    DEFAULT_PTZ_STEP_MS,
    DEFAULT_RTSP_PATH,
    DEFAULT_RTSP_PORT,
    NET_DVR_FILE_NOFIND,
    NET_DVR_FILE_SUCCESS,
    NET_DVR_ISFINDING,
    NET_DVR_NOMOREFILE,
    NET_DVR_PLAYGETPOS,
    NET_DVR_PLAYPAUSE,
    NET_DVR_PLAYRESTART,
    NET_DVR_PLAYSETPOS,
    NET_DVR_PLAYSTART,
    PTZ_DIRECTION_TO_CMD,
)
from .ctypes_defs import (
    LoginResult,
    NET_DVR_DEVICEINFO_V40,
    NET_DVR_FILECOND_V40,
    NET_DVR_FINDDATA_V40,
    NET_DVR_STREAM_INFO,
    NET_DVR_USER_LOGIN_INFO,
    NET_DVR_VOD_PARA,
    PLAY_DATA_CALLBACK,
    from_sdk_time,
    fill_bytes,
    to_sdk_time,
)
from .loader import HcNetSdkLoader, SdkLoadError

_LOGGER = logging.getLogger(__name__)


class SdkCallError(RuntimeError):
    """SDK call failed."""

    def __init__(self, message: str, *, error_code: int | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code

    def __str__(self) -> str:
        message = super().__str__()
        if self.error_code is None:
            return message
        return f"{message} (error_code={self.error_code})"


class HcNetSdkEnvironment:
    """Process-wide HCNetSDK lifecycle manager."""

    def __init__(self, lib_dir_override: str | None = None) -> None:
        self._lib_dir_override = lib_dir_override
        self._loader: HcNetSdkLoader | None = None
        self._sdk: C.CDLL | None = None
        self._ref_count = 0
        self._initialized = False
        self._lock = threading.RLock()

    @property
    def sdk(self) -> C.CDLL:
        if self._sdk is None:
            raise SdkLoadError("SDK not initialized")
        return self._sdk

    @property
    def lib_dir_override(self) -> str | None:
        return self._lib_dir_override

    def acquire(self) -> None:
        with self._lock:
            if not self._initialized:
                self._loader = HcNetSdkLoader(self._lib_dir_override)
                self._sdk = self._loader.load()
                ok = self._sdk.NET_DVR_Init()
                if not ok:
                    err = int(self._sdk.NET_DVR_GetLastError())
                    raise SdkCallError("NET_DVR_Init failed", error_code=err)

                log_dir = Path("/tmp") / "ezviz_hcnet" / "sdklog"
                log_dir.mkdir(parents=True, exist_ok=True)
                self._sdk.NET_DVR_SetLogToFile(3, str(log_dir).encode("utf-8"), 0)

                self._initialized = True
                _LOGGER.info("HCNetSDK initialized from %s", self._loader.lib_dir)

            self._ref_count += 1

    def release(self) -> None:
        with self._lock:
            if self._ref_count > 0:
                self._ref_count -= 1
            if self._ref_count == 0 and self._initialized and self._sdk is not None:
                self._sdk.NET_DVR_Cleanup()
                self._initialized = False
                self._sdk = None
                self._loader = None
                _LOGGER.info("HCNetSDK cleaned up")

    def get_last_error(self) -> int:
        with self._lock:
            if self._sdk is None:
                return -1
            return int(self._sdk.NET_DVR_GetLastError())


@dataclass(slots=True)
class DeviceConfig:
    host: str
    port: int
    username: str
    password: str
    channel: int
    rtsp_port: int = DEFAULT_RTSP_PORT
    rtsp_path: str = DEFAULT_RTSP_PATH
    ptz_default_speed: int = DEFAULT_PTZ_SPEED
    ptz_step_ms: int = DEFAULT_PTZ_STEP_MS

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


class HcNetSdkClient:
    """SDK operations bound to one backend entry."""

    def __init__(self, env: HcNetSdkEnvironment, config: DeviceConfig, *, entry_id: str) -> None:
        self.env = env
        self.config = config
        self.entry_id = entry_id
        self._user_id: int | None = None
        self._login_result: LoginResult | None = None
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"ezviz-hcnet-{entry_id[:8]}",
        )
        self._executor_closed = False

    @property
    def available(self) -> bool:
        return self._user_id is not None

    @property
    def user_id(self) -> int:
        if self._user_id is None:
            raise SdkCallError("Device is not logged in")
        return self._user_id

    async def async_run_in_executor(self, func, *args):
        if self._executor_closed:
            raise RuntimeError("SDK executor is already closed")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, partial(func, *args))

    async def async_connect(self) -> None:
        await self.async_run_in_executor(self.connect)

    async def async_disconnect(self) -> None:
        if self._executor_closed:
            return
        await self.async_run_in_executor(self.disconnect)

    async def async_close(self) -> None:
        await self.async_disconnect()
        if not self._executor_closed:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor_closed = True

    async def async_list_recordings_for_date(self, day: date, slot_minutes: int = 60) -> list[dict]:
        return await self.async_run_in_executor(self.list_recordings_for_date, day, slot_minutes)

    def connect(self) -> None:
        with self._lock:
            if self._user_id is not None:
                return
            self.env.acquire()
            try:
                self._login_result = self._login_blocking(
                    self.config.host,
                    self.config.port,
                    self.config.username,
                    self.config.password,
                )
                self._user_id = self._login_result.user_id
            except Exception:
                self.env.release()
                raise

    def disconnect(self) -> None:
        with self._lock:
            uid = self._user_id
            self._user_id = None
            self._login_result = None
            if uid is not None:
                self.env.sdk.NET_DVR_Logout(uid)
            self.env.release()

    async def async_ptz_step(
        self,
        direction: str,
        speed: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        speed = speed or self.config.ptz_default_speed
        duration_ms = duration_ms or self.config.ptz_step_ms
        await self.async_run_in_executor(self.ptz_step, direction, speed, duration_ms)

    async def async_ptz_stop(self, direction: str, speed: int | None = None) -> None:
        speed = speed or self.config.ptz_default_speed
        await self.async_run_in_executor(self.ptz_control, direction, 1, speed)

    def ptz_step(self, direction: str, speed: int, duration_ms: int) -> None:
        with self._lock:
            cmd = PTZ_DIRECTION_TO_CMD.get(direction)
            if cmd is None:
                raise ValueError(f"Unsupported PTZ direction: {direction}")
            self._ptz_control_locked(cmd, stop=0, speed=speed)
            self._sleep_ms(duration_ms)
            self._ptz_control_locked(cmd, stop=1, speed=speed)

    def ptz_control(self, direction: str, stop: int, speed: int) -> None:
        with self._lock:
            cmd = PTZ_DIRECTION_TO_CMD.get(direction)
            if cmd is None:
                raise ValueError(f"Unsupported PTZ direction: {direction}")
            self._ptz_control_locked(cmd, stop=stop, speed=speed)

    def _ptz_control_locked(self, cmd: int, *, stop: int, speed: int) -> None:
        ok = self.env.sdk.NET_DVR_PTZControlWithSpeed_Other(
            self.user_id,
            self.config.channel,
            cmd,
            int(stop),
            int(speed),
        )
        if not ok:
            err = self.env.get_last_error()
            raise SdkCallError("PTZ control failed", error_code=err)

    def playback_open(self, start: datetime, end: datetime) -> int:
        with self._lock:
            vod = NET_DVR_VOD_PARA()
            vod.dwSize = C.sizeof(NET_DVR_VOD_PARA)
            vod.struIDInfo = NET_DVR_STREAM_INFO()
            vod.struIDInfo.dwSize = C.sizeof(NET_DVR_STREAM_INFO)
            vod.struIDInfo.dwChannel = self.config.channel
            vod.struBeginTime = to_sdk_time(start)
            vod.struEndTime = to_sdk_time(end)
            vod.hWnd = None
            vod.byDrawFrame = 0
            vod.byStreamType = 0

            handle = int(self.env.sdk.NET_DVR_PlayBackByTime_V40(self.user_id, C.byref(vod)))
            if handle < 0:
                err = self.env.get_last_error()
                raise SdkCallError("NET_DVR_PlayBackByTime_V40 failed", error_code=err)
            return handle

    def playback_start(self, handle: int) -> None:
        with self._lock:
            ok = self.env.sdk.NET_DVR_PlayBackControl(handle, NET_DVR_PLAYSTART, 0, None)
            if not ok:
                err = self.env.get_last_error()
                raise SdkCallError("NET_DVR_PLAYSTART failed", error_code=err)

    def playback_set_callback(self, handle: int, callback: PLAY_DATA_CALLBACK) -> None:
        with self._lock:
            ok = self.env.sdk.NET_DVR_SetPlayDataCallBack_V40(handle, callback, None)
            if not ok:
                err = self.env.get_last_error()
                raise SdkCallError("NET_DVR_SetPlayDataCallBack_V40 failed", error_code=err)

    def playback_control(self, handle: int, action: str, seek_percent: float | None = None) -> int:
        with self._lock:
            if action == "play":
                command = NET_DVR_PLAYRESTART
                value = 0
            elif action == "pause":
                command = NET_DVR_PLAYPAUSE
                value = 0
            elif action == "seek":
                command = NET_DVR_PLAYSETPOS
                if seek_percent is None:
                    raise ValueError("seek_percent is required for seek action")
                value = max(0, min(100, int(round(seek_percent))))
            else:
                raise ValueError(f"Unsupported playback action: {action}")

            out_val = C.c_int(0)
            ok = self.env.sdk.NET_DVR_PlayBackControl(handle, command, value, C.byref(out_val))
            if not ok:
                err = self.env.get_last_error()
                raise SdkCallError("NET_DVR_PlayBackControl failed", error_code=err)
            return int(out_val.value)

    def playback_get_pos(self, handle: int) -> int:
        with self._lock:
            out_val = C.c_int(0)
            ok = self.env.sdk.NET_DVR_PlayBackControl(handle, NET_DVR_PLAYGETPOS, 0, C.byref(out_val))
            if not ok:
                err = self.env.get_last_error()
                raise SdkCallError("NET_DVR_PLAYGETPOS failed", error_code=err)
            return int(out_val.value)

    def playback_close(self, handle: int) -> None:
        with self._lock:
            self.env.sdk.NET_DVR_StopPlayBack(handle)

    def list_recordings_for_date(self, day: date, slot_minutes: int = 60) -> list[dict]:
        del slot_minutes  # Kept for API compatibility; SDK search returns native file segments.

        day_start = datetime(day.year, day.month, day.day, 0, 0, 0)
        day_end = day_start + timedelta(days=1) - timedelta(seconds=1)

        cond = NET_DVR_FILECOND_V40()
        cond.lChannel = int(self.config.channel)
        cond.dwFileType = 0xFF
        cond.dwIsLocked = 0xFF
        cond.dwUseCardNo = 0
        cond.struStartTime = to_sdk_time(day_start)
        cond.struStopTime = to_sdk_time(day_end)
        cond.byDrawFrame = 0
        cond.byFindType = 0
        cond.byQuickSearch = 0
        cond.bySpecialFindInfoType = 0
        cond.dwVolumeNum = 0
        cond.byStreamType = 0
        cond.byAudioFile = 0

        with self._lock:
            find_handle = int(self.env.sdk.NET_DVR_FindFile_V40(self.user_id, C.byref(cond)))
        if find_handle < 0:
            err = self.env.get_last_error()
            raise SdkCallError("NET_DVR_FindFile_V40 failed", error_code=err)

        records: list[dict] = []
        try:
            while True:
                data = NET_DVR_FINDDATA_V40()
                with self._lock:
                    ret = int(self.env.sdk.NET_DVR_FindNextFile_V40(find_handle, C.byref(data)))

                if ret == NET_DVR_FILE_SUCCESS:
                    start = from_sdk_time(data.struStartTime)
                    end = from_sdk_time(data.struStopTime)
                    if end <= start:
                        continue

                    name_bytes = bytes(data.sFileName)
                    file_name = name_bytes.split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
                    records.append(
                        {
                            "id": f"{start.isoformat()}_{end.isoformat()}_{len(records)}",
                            "start": start.isoformat(),
                            "end": end.isoformat(),
                            "duration_seconds": int((end - start).total_seconds()),
                            "file_name": file_name,
                            "file_size": int(data.dwFileSize),
                            "file_type": int(data.byFileType),
                            "locked": bool(data.byLocked),
                            "file_index": int(data.dwFileIndex),
                            "stream_type": int(data.byStreamType),
                        }
                    )
                    continue

                if ret in (NET_DVR_NOMOREFILE, NET_DVR_FILE_NOFIND):
                    break

                if ret == NET_DVR_ISFINDING:
                    pytime.sleep(0.05)
                    continue

                err = self.env.get_last_error()
                raise SdkCallError("NET_DVR_FindNextFile_V40 failed", error_code=err)
        finally:
            with self._lock:
                self.env.sdk.NET_DVR_FindClose_V30(find_handle)

        records.sort(key=lambda item: item["start"])
        return records

    def _login_blocking(self, host: str, port: int, username: str, password: str) -> LoginResult:
        login = NET_DVR_USER_LOGIN_INFO()
        fill_bytes(login.sDeviceAddress, host)
        fill_bytes(login.sUserName, username)
        fill_bytes(login.sPassword, password)
        login.wPort = int(port)
        login.bUseAsynLogin = 0
        login.byLoginMode = 0
        login.byUseUTCTime = 0

        dev = NET_DVR_DEVICEINFO_V40()
        uid = int(self.env.sdk.NET_DVR_Login_V40(C.byref(login), C.byref(dev)))
        if uid < 0:
            err = self.env.get_last_error()
            raise SdkCallError("NET_DVR_Login_V40 failed", error_code=err)

        return LoginResult(
            user_id=uid,
            start_channel=int(dev.struDeviceV30.byStartChan),
            analog_channels=int(dev.struDeviceV30.byChanNum),
            digital_start_channel=int(dev.struDeviceV30.byStartDChan),
        )

    @staticmethod
    def _sleep_ms(duration_ms: int) -> None:
        import time

        time.sleep(max(0, duration_ms) / 1000.0)


def probe_login(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    lib_dir_override: str | None,
) -> dict[str, int]:
    """Try SDK load + login for validation in backend process."""

    env = HcNetSdkEnvironment(lib_dir_override)
    env.acquire()
    uid: int | None = None
    try:
        login = NET_DVR_USER_LOGIN_INFO()
        fill_bytes(login.sDeviceAddress, host)
        fill_bytes(login.sUserName, username)
        fill_bytes(login.sPassword, password)
        login.wPort = int(port)
        login.bUseAsynLogin = 0
        login.byLoginMode = 0
        login.byUseUTCTime = 0

        dev = NET_DVR_DEVICEINFO_V40()
        uid = int(env.sdk.NET_DVR_Login_V40(C.byref(login), C.byref(dev)))
        if uid < 0:
            err = env.get_last_error()
            raise SdkCallError("NET_DVR_Login_V40 failed", error_code=err)

        return {
            "start_channel": int(dev.struDeviceV30.byStartChan),
            "analog_channels": int(dev.struDeviceV30.byChanNum),
            "digital_start_channel": int(dev.struDeviceV30.byStartDChan),
        }
    finally:
        if uid is not None:
            env.sdk.NET_DVR_Logout(uid)
        env.release()
