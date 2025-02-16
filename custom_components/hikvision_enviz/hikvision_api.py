"""Hikvision Enviz Camera API interface."""
import logging
import os
import time
from typing import Optional
from ctypes import byref

from .HCNetSDK import (
    NET_DVR_USER_LOGIN_INFO,
    NET_DVR_DEVICEINFO_V40,
    NET_DVR_PREVIEWINFO,
    NET_DVR_LOCAL_SDK_PATH,
    NET_SDK_INIT_CFG_TYPE,
    REALDATACALLBACK,
    load_library,
    netsdkdllpath,
    playM4dllpath,
    sys_platform,
    create_string_buffer,
)

_LOGGER = logging.getLogger(__name__)

class HikvisionEnvizAPI:
    """Interface class for Hikvision Enviz Camera."""

    def __init__(self, host: str, port: int, username: str, password: str):
        """Initialize the API."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._user_id = -1  # 登录句柄
        self._real_play_handle = -1  # 预览句柄
        self._connected = False
        
        # Load SDK libraries
        try:
            self._hik_sdk = load_library(netsdkdllpath)
            self._play_sdk = load_library(playM4dllpath)
            _LOGGER.debug("SDK libraries loaded successfully")
        except OSError as e:
            _LOGGER.error("Failed to load SDK libraries: %s", str(e))
            raise

        # Initialize callback function
        self._real_data_callback = REALDATACALLBACK(self._real_data_callback_v30)

    def _set_sdk_init_cfg(self) -> None:
        """Set SDK initialization configuration."""
        # Set HCNetSDK component and SSL library paths
        if sys_platform == 'windows':
            base_path = os.getcwd().encode('gbk')
            str_path = base_path + b'\\lib'
            sdk_com_path = NET_DVR_LOCAL_SDK_PATH()
            sdk_com_path.sPath = str_path

            # Set SDK path
            if self._hik_sdk.NET_DVR_SetSDKInitCfg(
                NET_SDK_INIT_CFG_TYPE.NET_SDK_INIT_CFG_SDK_PATH.value,
                byref(sdk_com_path)
            ):
                _LOGGER.debug('SDK path set successfully')

            # Set crypto library path
            if self._hik_sdk.NET_DVR_SetSDKInitCfg(
                NET_SDK_INIT_CFG_TYPE.NET_SDK_INIT_CFG_LIBEAY_PATH.value,
                create_string_buffer(str_path + b'\\libcrypto-1_1-x64.dll')
            ):
                _LOGGER.debug('Crypto library path set successfully')

            # Set SSL library path
            if self._hik_sdk.NET_DVR_SetSDKInitCfg(
                NET_SDK_INIT_CFG_TYPE.NET_SDK_INIT_CFG_SSLEAY_PATH.value,
                create_string_buffer(str_path + b'\\libssl-1_1-x64.dll')
            ):
                _LOGGER.debug('SSL library path set successfully')
        else:
            base_path = os.getcwd().encode('utf-8')
            str_path = base_path + b'/lib'
            sdk_com_path = NET_DVR_LOCAL_SDK_PATH()
            sdk_com_path.sPath = str_path

            # Set SDK path
            if self._hik_sdk.NET_DVR_SetSDKInitCfg(
                NET_SDK_INIT_CFG_TYPE.NET_SDK_INIT_CFG_SDK_PATH.value,
                byref(sdk_com_path)
            ):
                _LOGGER.debug('SDK path set successfully')

            # Set crypto library path
            if self._hik_sdk.NET_DVR_SetSDKInitCfg(
                NET_SDK_INIT_CFG_TYPE.NET_SDK_INIT_CFG_LIBEAY_PATH.value,
                create_string_buffer(str_path + b'/libcrypto.so.1.1')
            ):
                _LOGGER.debug('Crypto library path set successfully')

            # Set SSL library path
            if self._hik_sdk.NET_DVR_SetSDKInitCfg(
                NET_SDK_INIT_CFG_TYPE.NET_SDK_INIT_CFG_SSLEAY_PATH.value,
                create_string_buffer(str_path + b'/libssl.so.1.1')
            ):
                _LOGGER.debug('SSL library path set successfully')

    def _real_data_callback_v30(self, lPlayHandle, dwDataType, pBuffer, dwBufSize, pUser):
        """Real-time data callback function."""
        # Implement callback handling if needed for streaming
        pass

    async def connect(self) -> bool:
        """Connect to the camera."""
        if self._connected:
            return True

        try:
            # Set SDK initialization configuration
            self._set_sdk_init_cfg()
            
            # Initialize SDK
            if not self._hik_sdk.NET_DVR_Init():
                error_code = self._hik_sdk.NET_DVR_GetLastError()
                _LOGGER.error("Failed to initialize SDK with error code: %s", error_code)
                return False

            # Prepare login info
            login_info = NET_DVR_USER_LOGIN_INFO()
            device_info = NET_DVR_DEVICEINFO_V40()
            
            login_info.sDeviceAddress = self._host.encode()
            login_info.wPort = self._port
            login_info.sUserName = self._username.encode()
            login_info.sPassword = self._password.encode()
            
            # Login to device
            self._user_id = self._hik_sdk.NET_DVR_Login_V40(byref(login_info), byref(device_info))
            
            if self._user_id < 0:
                error_code = self._hik_sdk.NET_DVR_GetLastError()
                _LOGGER.error("Login failed with error code: %s", error_code)
                return False
                
            self._connected = True
            _LOGGER.info("Successfully connected to Hikvision camera")
            return True
            
        except Exception as ex:
            _LOGGER.error("Error connecting to camera: %s", str(ex))
            return False

    async def disconnect(self) -> None:
        """Disconnect from the camera."""
        if self._connected:
            if self._real_play_handle >= 0:
                self._hik_sdk.NET_DVR_StopRealPlay(self._real_play_handle)
                self._real_play_handle = -1
            
            self._hik_sdk.NET_DVR_Logout(self._user_id)
            self._hik_sdk.NET_DVR_Cleanup()
            self._connected = False
            self._user_id = -1

    async def get_stream_url(self) -> Optional[str]:
        """Get the camera stream URL."""
        if not self._connected:
            return None
        
        return f"rtsp://{self._username}:{self._password}@{self._host}:{self._port}/Streaming/Channels/101"

    async def get_snapshot(self) -> Optional[bytes]:
        """Get camera snapshot."""
        if not self._connected:
            return None

        try:
            # Start preview to get snapshot
            preview_info = NET_DVR_PREVIEWINFO()
            preview_info.hPlayWnd = 0
            preview_info.lChannel = 1  # Channel number
            preview_info.dwStreamType = 0  # Main stream
            preview_info.dwLinkMode = 0  # TCP
            preview_info.bBlocked = 1  # Blocking stream

            self._real_play_handle = self._hik_sdk.NET_DVR_RealPlay_V40(
                self._user_id, 
                byref(preview_info),
                self._real_data_callback,
                None
            )

            if self._real_play_handle < 0:
                error_code = self._hik_sdk.NET_DVR_GetLastError()
                _LOGGER.error("Failed to start preview with error code: %s", error_code)
                return None

            # Get snapshot
            buffer = byref(c_byte())
            buffer_size = c_long()

            if not self._hik_sdk.NET_DVR_CaptureJPEGPicture_NEW(
                self._user_id, 1, buffer, buffer_size
            ):
                error_code = self._hik_sdk.NET_DVR_GetLastError()
                _LOGGER.error("Failed to capture snapshot with error code: %s", error_code)
                return None

            # Stop preview
            self._hik_sdk.NET_DVR_StopRealPlay(self._real_play_handle)
            self._real_play_handle = -1

            return bytes(buffer.value[:buffer_size.value])
        except Exception as err:
            _LOGGER.error("Error capturing snapshot: %s", err)
            return None

    async def pan_tilt(self, pan: float, tilt: float) -> bool:
        """Control camera pan/tilt."""
        if not self._connected:
            return False

        try:
            command = 21 if pan > 0 else 22  # Left/Right
            self._hik_sdk.NET_DVR_PTZControl(self._user_id, command, 0)
            command = 23 if tilt > 0 else 24  # Up/Down
            self._hik_sdk.NET_DVR_PTZControl(self._user_id, command, 0)
            return True
        except Exception as err:
            _LOGGER.error("Error controlling PTZ: %s", err)
            return False 
        
    def __del__(self):
        """Cleanup when object is destroyed."""
        if hasattr(self, '_connected') and self._connected:
            self._hik_sdk.NET_DVR_Logout(self._user_id)
            self._hik_sdk.NET_DVR_Cleanup() 