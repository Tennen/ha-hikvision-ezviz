"""Hikvision Enviz Camera API interface."""
import logging
import os
import time
from typing import Optional, Callable
from ctypes import byref, c_byte, c_long, memmove, CFUNCTYPE, c_char_p, c_void_p, cast, POINTER
import asyncio
from datetime import datetime
from aiohttp import web
import queue

from .HCNetSDK import (
    NET_DVR_USER_LOGIN_INFO,
    NET_DVR_DEVICEINFO_V40,
    NET_DVR_PREVIEWINFO,
    NET_DVR_LOCAL_SDK_PATH,
    NET_SDK_INIT_CFG_TYPE,
    REALDATACALLBACK,
    load_library,
    netsdkdllpath,
    sys_platform,
    create_string_buffer,
    NET_DVR_SYSHEAD,
    NET_DVR_STREAMDATA,
)

from .PlayCtrl import *

_LOGGER = logging.getLogger(__name__)

class HikvisionEnvizAPI:
    """Interface class for Hikvision Enviz Camera."""

    def __init__(self, host: str, port: int, username: str, password: str):
        """Initialize the API."""
        # 设置库路径
        os.environ['LD_LIBRARY_PATH'] = '/lib:/lib/HCNetSDKCom/:/usr/lib:/usr/lib/HCNetSDKCom/'
        
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._user_id = -1
        self._real_play_handle = -1
        self._connected = False
        self._play_ctrl_port = c_long(-1)
        self._stream_callback = None
        self._current_frame = None
        self._play_handle = -1
        self._stream_data = queue.Queue()
        self._running = False
        self._callback = None
        self._loop = None
        
        # Load SDK libraries
        try:
            self._hik_sdk = load_library(netsdkdllpath)
            self._play_sdk = load_library(playM4dllpath)
            _LOGGER.debug("SDK libraries loaded successfully")
        except OSError as e:
            _LOGGER.error("Failed to load SDK libraries: %s", str(e))
            raise

        # Initialize callbacks
        self._real_data_callback = REALDATACALLBACK(self._real_data_callback_v30)
        self._dec_callback = DECCBFUNWIN(self._decode_callback)

    def _decode_callback(self, nPort, pBuf, nSize, pFrameInfo, nUser, nReserved2):
        """Decode callback function."""
        try:
            if pFrameInfo.contents.nType == 3:  # Video frame
                # Convert frame data to bytes
                frame_data = (c_byte * nSize)()
                memmove(frame_data, pBuf, nSize)
                self._current_frame = bytes(frame_data)
                
                # If there's a callback registered, call it
                if self._stream_callback:
                    asyncio.create_task(self._stream_callback(self._current_frame))
        except Exception as e:
            _LOGGER.error("Decode callback error: %s", str(e))

    def _real_data_callback_v30(self, lPlayHandle, dwDataType, pBuffer, dwBufSize, pUser):
        """Real-time data callback function."""
        try:
            if dwDataType == NET_DVR_SYSHEAD:  # System header
                # Set stream mode
                self._play_sdk.PlayM4_SetStreamOpenMode(self._play_ctrl_port, 0)
                
                # Open stream
                if self._play_sdk.PlayM4_OpenStream(self._play_ctrl_port, pBuffer, dwBufSize, 1024 * 1024):
                    # Set decode callback
                    self._play_sdk.PlayM4_SetDecCallBackExMend(
                        self._play_ctrl_port, 
                        self._dec_callback,
                        None, 0, None
                    )
                    
                    # Start decoding
                    if self._play_sdk.PlayM4_Play(self._play_ctrl_port, None):
                        _LOGGER.debug("Stream playback started successfully")
                    else:
                        _LOGGER.error("Failed to start playback")
                else:
                    _LOGGER.error(
                        "Failed to open stream, error: %s",
                        self._play_sdk.PlayM4_GetLastError(self._play_ctrl_port)
                    )
                    
            elif dwDataType == NET_DVR_STREAMDATA:  # Stream data
                # Input data for decoding
                self._play_sdk.PlayM4_InputData(self._play_ctrl_port, pBuffer, dwBufSize)
                
        except Exception as e:
            _LOGGER.error("Real data callback error: %s", str(e))

    def start_stream(self, callback=None):
        """启动视频流.
        
        Args:
            callback: 可选的回调函数，接收 (data_type, data) 参数
                     data_type: 1 为系统头数据，2 为码流数据
                     data: bytes 类型的数据
        """
        try:
            # 设置回调函数
            self._stream_callback = callback
            
            # 创建预览参数结构体
            preview_info = NET_DVR_PREVIEWINFO()
            preview_info.hPlayWnd = 0      # 不使用窗口
            preview_info.lChannel = 1      # 通道号
            preview_info.dwStreamType = 0  # 主码流
            preview_info.dwLinkMode = 0    # TCP
            preview_info.bBlocked = 1      # 阻塞取流

            # 设置回调函数
            self._callback = REALDATACALLBACK(self.real_data_callback)
            
            # 启动预览
            self._play_handle = self._hik_sdk.NET_DVR_RealPlay_V40(
                self._user_id, byref(preview_info), self._callback, None
            )

            if self._play_handle < 0:
                error_code = self._hik_sdk.NET_DVR_GetLastError()
                _LOGGER.error(f"Start preview failed with error code: {error_code}")
                return None

            return self._play_handle

        except Exception as e:
            _LOGGER.error(f"Error starting stream: {str(e)}")
            return None

    async def stop_stream(self) -> None:
        """停止视频流."""
        try:
            if self._play_handle >= 0:
                self._hik_sdk.NET_DVR_StopRealPlay(self._play_handle)
                self._play_handle = -1

            # 停止解码，释放播放库资源
            if self._play_ctrl_port.value >= 0:
                self._play_sdk.PlayM4_Stop(self._play_ctrl_port)
                self._play_sdk.PlayM4_CloseStream(self._play_ctrl_port)
                self._play_sdk.PlayM4_FreePort(self._play_ctrl_port)
                self._play_ctrl_port = c_long(-1)

            self._stream_callback = None

        except Exception as e:
            _LOGGER.error(f"Error stopping stream: {str(e)}")

    async def get_current_frame(self) -> Optional[bytes]:
        """Get the current frame."""
        return self._current_frame

    def _set_sdk_init_cfg(self) -> None:
        """Set SDK initialization configuration."""
        # Set HCNetSDK component and SSL library paths
        # 先用字符串处理路径
        str_path = '/lib/'
        # 然后转换为 bytes
        sdk_com_path = NET_DVR_LOCAL_SDK_PATH()
        sdk_com_path.sPath = str_path.encode()

        # Set SDK path
        if self._hik_sdk.NET_DVR_SetSDKInitCfg(
            NET_SDK_INIT_CFG_TYPE.NET_SDK_INIT_CFG_SDK_PATH.value,
            byref(sdk_com_path)
        ):
            _LOGGER.debug('SDK path set successfully')

        # Set crypto library path
        crypto_path = os.path.join(str_path, 'libcrypto.so.1.1')
        if self._hik_sdk.NET_DVR_SetSDKInitCfg(
            NET_SDK_INIT_CFG_TYPE.NET_SDK_INIT_CFG_LIBEAY_PATH.value,
            create_string_buffer(crypto_path.encode())
        ):
            _LOGGER.debug('Crypto library path set successfully')

        # Set SSL library path
        ssl_path = os.path.join(str_path, 'libssl.so.1.1')
        if self._hik_sdk.NET_DVR_SetSDKInitCfg(
            NET_SDK_INIT_CFG_TYPE.NET_SDK_INIT_CFG_SSLEAY_PATH.value,
            create_string_buffer(ssl_path.encode())
        ):
            _LOGGER.debug('SSL library path set successfully')
        self._hik_sdk.NET_DVR_SetConnectTime(2000, 1)
        self._hik_sdk.NET_DVR_SetReconnect(10000, True)

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
            self.GeneralSetting()

            # Prepare login info
            login_info = NET_DVR_USER_LOGIN_INFO()
            device_info = NET_DVR_DEVICEINFO_V40()
            
            login_info.sDeviceAddress = self._host.encode()
            login_info.bUseAsynLogin = 0
            login_info.wPort = self._port
            login_info.sUserName = self._username.encode()
            login_info.sPassword = self._password.encode()
            login_info.byLoginMode = 0
            login_info.byHttps = 0
            login_info.byVerifyMode = 0
            
            # Login to device
            self._user_id = self._hik_sdk.NET_DVR_Login_V40(byref(login_info), byref(device_info))
            
            if self._user_id < 0:
                error_code = self._hik_sdk.NET_DVR_GetLastError()
                _LOGGER.error("Login failed with error code: %s", error_code)
                return False
                
            self._connected = True
            _LOGGER.info("Successfully connected to Hikvision camera, user_id: %s", self._user_id)

            # 登录成功后测试流
            if self._user_id >= 0:
                _LOGGER.info("Testing stream...")
                if not self.test_stream():
                    _LOGGER.error("Stream test failed")
                    return False
                _LOGGER.info("Stream test successful")
            
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

    def check_device_accessible(self):
        """Check if the device is accessible."""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((self._host, self._port))
            sock.close()
            if result == 0:
                _LOGGER.debug("Device is accessible")
                return True
            _LOGGER.error("Device is not accessible")
            return False
        except Exception as e:
            _LOGGER.error("Network check failed: %s", str(e))
            return False
    
    def GeneralSetting(self):
        # 日志的等级（默认为0）：0-表示关闭日志，1-表示只输出ERROR错误日志，2-输出ERROR错误信息和DEBUG调试信息，3-输出ERROR错误信息、DEBUG调试信息和INFO普通信息等所有信息
        # self.hikSDK.NET_DVR_SetLogToFile(3, b'./SdkLog_Python/', False)
        self._hik_sdk.NET_DVR_SetLogToFile(3, bytes('./SdkLog_Python/', encoding="utf-8"), False)

    def test_connection(self) -> bool:
        """Test connection to camera."""
        try:
            # Set SDK initialization configuration
            self._set_sdk_init_cfg()
            
            # Initialize SDK
            if not self._hik_sdk.NET_DVR_Init():
                error_code = self._hik_sdk.NET_DVR_GetLastError()
                _LOGGER.error("Failed to initialize SDK with error code: %s", error_code)
                return False

            if not self.check_device_accessible():
                _LOGGER.error("Device is not accessible")
                return False
            self.GeneralSetting()
            # Prepare login info
            login_info = NET_DVR_USER_LOGIN_INFO()
            
            # Convert string inputs to bytes for SDK
            login_info.sDeviceAddress = self._host.encode()
            login_info.bUseAsynLogin = 0
            login_info.wPort = self._port
            login_info.sUserName = self._username.encode()
            login_info.sPassword = self._password.encode()
            login_info.byLoginMode = 0
            login_info.byHttps = 0
            login_info.byVerifyMode = 0

            struDeviceInfoV40 = NET_DVR_DEVICEINFO_V40()
            
            # Try to login
            user_id = self._hik_sdk.NET_DVR_Login_V30(self._host.encode(), self._port, self._username.encode(), self._password.encode(), byref(struDeviceInfoV40))
            
            if user_id < 0:
                error_code = self._hik_sdk.NET_DVR_GetLastError()
                error_msg = self._hik_sdk.NET_DVR_GetErrorMsg(byref(c_long(error_code)))
                _LOGGER.error("Login failed with error code: %d, message: %s", error_code, error_msg)
                return False
            
            # Cleanup test connection
            self._hik_sdk.NET_DVR_Logout(user_id)
            self._hik_sdk.NET_DVR_Cleanup()
            
            return True
            
        except Exception as ex:
            ex.with_traceback()
            _LOGGER.error("Error testing connection: %s", str(ex))
            return False 

    def real_data_callback(self, lRealHandle, dwDataType, pBuffer, dwBufSize, dwUser):
        """回调函数，接收实时流数据."""
        try:
            if dwDataType == NET_DVR_SYSHEAD:  # 系统头数据
                _LOGGER.info("Received system header")
                # 保存系统头数据
                if self._stream_callback:
                    data_array = (c_byte * dwBufSize)()
                    memmove(data_array, pBuffer, dwBufSize)
                    header_data = bytes(data_array)
                    asyncio.create_task(self._stream_callback(1, header_data))
                
            elif dwDataType == NET_DVR_STREAMDATA:  # 码流数据
                # 直接传递码流数据
                if self._stream_callback:
                    data_array = (c_byte * dwBufSize)()
                    memmove(data_array, pBuffer, dwBufSize)
                    stream_data = bytes(data_array)
                    asyncio.create_task(self._stream_callback(2, stream_data))
                
        except Exception as e:
            _LOGGER.error(f"Error in callback: {str(e)}")

    async def test_stream(self) -> bool:
        """测试视频流."""
        try:
            # 创建预览参数结构体
            preview_info = NET_DVR_PREVIEWINFO()
            preview_info.hPlayWnd = 0      # 不使用窗口
            preview_info.lChannel = 1      # 通道号
            preview_info.dwStreamType = 0  # 主码流
            preview_info.dwLinkMode = 0    # TCP
            preview_info.bBlocked = 1      # 阻塞取流

            # 设置回调函数
            self._callback = REALDATACALLBACK(self.RealDataCallBack_V30)
            
            # 启动预览
            self.lRealPlayHandle = self._hik_sdk.NET_DVR_RealPlay_V40(
                self._user_id, byref(preview_info), self._callback, None
            )

            if self.lRealPlayHandle < 0:
                error_code = self._hik_sdk.NET_DVR_GetLastError()
                _LOGGER.error(f"Start preview failed with error code: {error_code}")
                return False

            # 使用异步等待替代 sleep
            await asyncio.sleep(10)

            # 停止预览
            self._hik_sdk.NET_DVR_StopRealPlay(self.lRealPlayHandle)
            self.lRealPlayHandle = -1
            
            _LOGGER.info("Stream test completed")
            return True

        except Exception as e:
            _LOGGER.error(f"Error testing stream: {str(e)}")
            return False

    def RealDataCallBack_V30(self, lPlayHandle, dwDataType, pBuffer, dwBufSize, pUser):
        """码流回调函数."""
        try:
            if dwDataType == NET_DVR_SYSHEAD:
                # 系统头数据
                from datetime import datetime
                current_time = datetime.now()
                timestamp_str = current_time.strftime('%Y%m%d_%H%M%S')
                self.preview_file = f'/config/test_stream_{timestamp_str}.mp4'
                _LOGGER.info(f"Created new stream file: {self.preview_file}")
                
            elif dwDataType == NET_DVR_STREAMDATA:
                # 码流数据
                self.writeFile(self.preview_file, pBuffer, dwBufSize)
                
            else:
                _LOGGER.debug(f'其他数据,长度: {dwBufSize}')
                
        except Exception as e:
            _LOGGER.error(f"Error in callback: {str(e)}")

    def writeFile(self, filePath, pBuffer, dwBufSize):
        """将视频流保存到本地."""
        try:
            # 使用memmove函数将指针数据读到数组中
            data_array = (c_byte * dwBufSize)()
            memmove(data_array, pBuffer, dwBufSize)

            # 确保目录存在
            os.makedirs(os.path.dirname(filePath), exist_ok=True)

            # 判断文件是否存在
            if not os.path.exists(filePath):
                # 如果不存在，创建文件
                open(filePath, "wb").close()

            # 追加写入数据
            with open(filePath, 'ab') as f:
                f.write(data_array)
                
        except Exception as e:
            _LOGGER.error(f"Error writing file: {str(e)}") 