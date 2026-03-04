"""HCNetSDK dynamic loader."""

from __future__ import annotations

import ctypes as C
import logging
import os
import platform
from pathlib import Path

from .const import (
    NET_SDK_INIT_CFG_LIBEAY_PATH,
    NET_SDK_INIT_CFG_SDK_PATH,
    NET_SDK_INIT_CFG_SSLEAY_PATH,
)
from .ctypes_defs import (
    NET_DVR_DEVICEINFO_V40,
    NET_DVR_FINDDATA_V40,
    NET_DVR_FILECOND_V40,
    NET_DVR_LOCAL_SDK_PATH,
    NET_DVR_USER_LOGIN_INFO,
    NET_DVR_VOD_PARA,
    PLAY_DATA_CALLBACK,
)

_LOGGER = logging.getLogger(__name__)


class SdkLoadError(RuntimeError):
    """SDK load failure."""


class HcNetSdkLoader:
    """Load HCNetSDK and set minimal ctypes signatures."""

    def __init__(self, lib_dir_override: str | None = None) -> None:
        self._lib_dir = Path(lib_dir_override).expanduser().resolve() if lib_dir_override else self._default_lib_dir()
        self._handles: list[C.CDLL] = []
        self._sdk: C.CDLL | None = None

    @property
    def lib_dir(self) -> Path:
        return self._lib_dir

    @property
    def sdk(self) -> C.CDLL:
        if self._sdk is None:
            raise SdkLoadError("HCNetSDK not loaded")
        return self._sdk

    @staticmethod
    def _default_lib_dir() -> Path:
        return Path(__file__).resolve().parents[1] / "lib" / "arm64"

    @staticmethod
    def ensure_architecture() -> None:
        system = platform.system().lower()
        if system != "linux":
            raise SdkLoadError(
                f"Unsupported OS '{platform.system()}'. ezviz_hcnet requires Linux aarch64/arm64."
            )

        machine = platform.machine().lower()
        if machine not in {"aarch64", "arm64"}:
            raise SdkLoadError(
                f"Unsupported CPU architecture '{machine}'. ezviz_hcnet requires Linux aarch64/arm64 HCNetSDK."
            )

    def load(self) -> C.CDLL:
        self.ensure_architecture()
        if not self._lib_dir.exists():
            raise SdkLoadError(f"SDK library directory not found: {self._lib_dir}")

        hcnet = self._lib_dir / "libhcnetsdk.so"
        if not hcnet.exists():
            raise SdkLoadError(f"Missing libhcnetsdk.so in {self._lib_dir}")

        self._extend_ld_library_path()
        self._preload_dependencies()

        try:
            self._sdk = C.CDLL(str(hcnet), mode=C.RTLD_GLOBAL)
        except OSError as err:
            message = str(err)
            if "ld-linux-aarch64.so.1" in message:
                raise SdkLoadError(
                    "Missing glibc dynamic loader 'ld-linux-aarch64.so.1'. "
                    "The bundled HCNetSDK is glibc-based and cannot run on musl environments "
                    "(for example Alpine-based Home Assistant containers)."
                ) from err
            raise SdkLoadError(f"Failed to load libhcnetsdk.so from {self._lib_dir}: {err}") from err

        self._configure_signatures(self._sdk)

        self._configure_sdk_init_paths(self._sdk)
        return self._sdk

    def _extend_ld_library_path(self) -> None:
        base = str(self._lib_dir)
        com = str(self._lib_dir / "HCNetSDKCom")
        current = os.environ.get("LD_LIBRARY_PATH", "")
        parts = [p for p in current.split(":") if p]
        for p in (base, com):
            if p not in parts:
                parts.append(p)
        os.environ["LD_LIBRARY_PATH"] = ":".join(parts)

    def _load_shared(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            handle = C.CDLL(str(path), mode=C.RTLD_GLOBAL)
            self._handles.append(handle)
            _LOGGER.debug("Preloaded %s", path)
        except OSError as err:
            _LOGGER.warning("Failed to preload %s: %s", path, err)

    def _preload_dependencies(self) -> None:
        ordered = [
            "libcrypto.so.1.1",
            "libssl.so.1.1",
            "libz.so",
            "libhpr.so",
            "libHCCore.so",
            "libhcnetsdk.so",
        ]
        for name in ordered:
            self._load_shared(self._lib_dir / name)

        com_dir = self._lib_dir / "HCNetSDKCom"
        if com_dir.exists():
            skip = {"libHCDisplay.so", "libAudioIntercom.so"}
            for so in sorted(com_dir.glob("*.so")):
                if so.name in skip:
                    continue
                self._load_shared(so)

    def _configure_signatures(self, sdk: C.CDLL) -> None:
        # Init / cleanup
        sdk.NET_DVR_Init.argtypes = []
        sdk.NET_DVR_Init.restype = C.c_int

        sdk.NET_DVR_Cleanup.argtypes = []
        sdk.NET_DVR_Cleanup.restype = C.c_int

        sdk.NET_DVR_SetSDKInitCfg.argtypes = [C.c_int, C.c_void_p]
        sdk.NET_DVR_SetSDKInitCfg.restype = C.c_int

        sdk.NET_DVR_SetLogToFile.argtypes = [C.c_int, C.c_char_p, C.c_int]
        sdk.NET_DVR_SetLogToFile.restype = C.c_int

        # Login / logout
        sdk.NET_DVR_Login_V40.argtypes = [C.POINTER(NET_DVR_USER_LOGIN_INFO), C.POINTER(NET_DVR_DEVICEINFO_V40)]
        sdk.NET_DVR_Login_V40.restype = C.c_int

        sdk.NET_DVR_Logout.argtypes = [C.c_int]
        sdk.NET_DVR_Logout.restype = C.c_int

        sdk.NET_DVR_GetLastError.argtypes = []
        sdk.NET_DVR_GetLastError.restype = C.c_uint32

        # PTZ
        sdk.NET_DVR_PTZControlWithSpeed_Other.argtypes = [C.c_int, C.c_int, C.c_uint32, C.c_uint32, C.c_uint32]
        sdk.NET_DVR_PTZControlWithSpeed_Other.restype = C.c_int

        # Playback
        sdk.NET_DVR_PlayBackByTime_V40.argtypes = [C.c_int, C.POINTER(NET_DVR_VOD_PARA)]
        sdk.NET_DVR_PlayBackByTime_V40.restype = C.c_int

        sdk.NET_DVR_SetPlayDataCallBack_V40.argtypes = [C.c_int, PLAY_DATA_CALLBACK, C.c_void_p]
        sdk.NET_DVR_SetPlayDataCallBack_V40.restype = C.c_int

        sdk.NET_DVR_PlayBackControl.argtypes = [C.c_int, C.c_uint32, C.c_uint32, C.POINTER(C.c_int)]
        sdk.NET_DVR_PlayBackControl.restype = C.c_int

        sdk.NET_DVR_StopPlayBack.argtypes = [C.c_int]
        sdk.NET_DVR_StopPlayBack.restype = C.c_int

        # Recording search
        sdk.NET_DVR_FindFile_V40.argtypes = [C.c_int, C.POINTER(NET_DVR_FILECOND_V40)]
        sdk.NET_DVR_FindFile_V40.restype = C.c_int

        sdk.NET_DVR_FindNextFile_V40.argtypes = [C.c_int, C.POINTER(NET_DVR_FINDDATA_V40)]
        sdk.NET_DVR_FindNextFile_V40.restype = C.c_int

        sdk.NET_DVR_FindClose_V30.argtypes = [C.c_int]
        sdk.NET_DVR_FindClose_V30.restype = C.c_int

    def _configure_sdk_init_paths(self, sdk: C.CDLL) -> None:
        crypto = C.create_string_buffer(str(self._lib_dir / "libcrypto.so.1.1").encode("utf-8"))
        ssl = C.create_string_buffer(str(self._lib_dir / "libssl.so.1.1").encode("utf-8"))

        sdk_path = NET_DVR_LOCAL_SDK_PATH()
        path_bytes = (str(self._lib_dir) + "/").encode("utf-8")
        n = min(len(path_bytes), len(sdk_path.sPath) - 1)
        for i in range(n):
            sdk_path.sPath[i] = path_bytes[i]

        sdk.NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_LIBEAY_PATH, C.cast(crypto, C.c_void_p))
        sdk.NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_SSLEAY_PATH, C.cast(ssl, C.c_void_p))
        sdk.NET_DVR_SetSDKInitCfg(NET_SDK_INIT_CFG_SDK_PATH, C.byref(sdk_path))
