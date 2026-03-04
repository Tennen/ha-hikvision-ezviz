"""ctypes definitions for a minimal HCNetSDK surface."""

from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
from datetime import datetime

NET_SDK_MAX_FILE_PATH = 256
NET_DVR_DEV_ADDRESS_MAX_LEN = 129
NET_DVR_LOGIN_USERNAME_MAX_LEN = 64
NET_DVR_LOGIN_PASSWD_MAX_LEN = 64
SERIALNO_LEN = 48
NAME_LEN = 32
STREAM_ID_LEN = 32
GUID_LEN = 16
CARDNUM_LEN_OUT = 32
ACS_CARD_NO_LEN = CARDNUM_LEN_OUT
NET_DVR_FILE_NAME_LEN = 100
SPECIAL_FIND_INFO_LEN = 8


class NET_DVR_TIME(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("dwYear", C.c_uint32),
        ("dwMonth", C.c_uint32),
        ("dwDay", C.c_uint32),
        ("dwHour", C.c_uint32),
        ("dwMinute", C.c_uint32),
        ("dwSecond", C.c_uint32),
    ]


class NET_DVR_DEVICEINFO_V30(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("sSerialNumber", C.c_ubyte * SERIALNO_LEN),
        ("byAlarmInPortNum", C.c_ubyte),
        ("byAlarmOutPortNum", C.c_ubyte),
        ("byDiskNum", C.c_ubyte),
        ("byDVRType", C.c_ubyte),
        ("byChanNum", C.c_ubyte),
        ("byStartChan", C.c_ubyte),
        ("byAudioChanNum", C.c_ubyte),
        ("byIPChanNum", C.c_ubyte),
        ("byZeroChanNum", C.c_ubyte),
        ("byMainProto", C.c_ubyte),
        ("bySubProto", C.c_ubyte),
        ("bySupport", C.c_ubyte),
        ("bySupport1", C.c_ubyte),
        ("bySupport2", C.c_ubyte),
        ("wDevType", C.c_uint16),
        ("bySupport3", C.c_ubyte),
        ("byMultiStreamProto", C.c_ubyte),
        ("byStartDChan", C.c_ubyte),
        ("byStartDTalkChan", C.c_ubyte),
        ("byHighDChanNum", C.c_ubyte),
        ("bySupport4", C.c_ubyte),
        ("byLanguageType", C.c_ubyte),
        ("byVoiceInChanNum", C.c_ubyte),
        ("byStartVoiceInChanNo", C.c_ubyte),
        ("bySupport5", C.c_ubyte),
        ("bySupport6", C.c_ubyte),
        ("byMirrorChanNum", C.c_ubyte),
        ("wStartMirrorChanNo", C.c_uint16),
        ("bySupport7", C.c_ubyte),
        ("byRes2", C.c_ubyte),
    ]


class NET_DVR_DEVICEINFO_V40(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("struDeviceV30", NET_DVR_DEVICEINFO_V30),
        ("bySupportLock", C.c_ubyte),
        ("byRetryLoginTime", C.c_ubyte),
        ("byPasswordLevel", C.c_ubyte),
        ("byRes1", C.c_ubyte),
        ("dwSurplusLockTime", C.c_uint32),
        ("byCharEncodeType", C.c_ubyte),
        ("bySupportDev5", C.c_ubyte),
        ("bySupport", C.c_ubyte),
        ("byLoginMode", C.c_ubyte),
        ("dwOEMCode", C.c_uint32),
        ("iResidualValidity", C.c_int32),
        ("byResidualValidity", C.c_ubyte),
        ("bySingleStartDTalkChan", C.c_ubyte),
        ("bySingleDTalkChanNums", C.c_ubyte),
        ("byPassWordResetLevel", C.c_ubyte),
        ("bySupportStreamEncrypt", C.c_ubyte),
        ("byMarketType", C.c_ubyte),
        ("byRes2", C.c_ubyte * 238),
    ]


class NET_DVR_USER_LOGIN_INFO(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("sDeviceAddress", C.c_ubyte * NET_DVR_DEV_ADDRESS_MAX_LEN),
        ("byUseTransport", C.c_ubyte),
        ("wPort", C.c_uint16),
        ("sUserName", C.c_ubyte * NET_DVR_LOGIN_USERNAME_MAX_LEN),
        ("sPassword", C.c_ubyte * NET_DVR_LOGIN_PASSWD_MAX_LEN),
        ("cbLoginResult", C.c_void_p),
        ("pUser", C.c_void_p),
        ("bUseAsynLogin", C.c_uint32),
        ("byProxyType", C.c_ubyte),
        ("byUseUTCTime", C.c_ubyte),
        ("byLoginMode", C.c_ubyte),
        ("byHttps", C.c_ubyte),
        ("iProxyID", C.c_uint32),
        ("byVerifyMode", C.c_ubyte),
        ("byRes2", C.c_ubyte * 119),
    ]


class NET_DVR_LOCAL_SDK_PATH(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("sPath", C.c_ubyte * NET_SDK_MAX_FILE_PATH),
        ("byRes", C.c_ubyte * 128),
    ]


class NET_DVR_STREAM_INFO(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("dwSize", C.c_uint32),
        ("byID", C.c_ubyte * STREAM_ID_LEN),
        ("dwChannel", C.c_uint32),
        ("byRes", C.c_ubyte * 32),
    ]


class NET_DVR_VOD_PARA(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("dwSize", C.c_uint32),
        ("struIDInfo", NET_DVR_STREAM_INFO),
        ("struBeginTime", NET_DVR_TIME),
        ("struEndTime", NET_DVR_TIME),
        ("hWnd", C.c_void_p),
        ("byDrawFrame", C.c_ubyte),
        ("byVolumeType", C.c_ubyte),
        ("byVolumeNum", C.c_ubyte),
        ("byStreamType", C.c_ubyte),
        ("dwFileIndex", C.c_uint32),
        ("byAudioFile", C.c_ubyte),
        ("byCourseFile", C.c_ubyte),
        ("byDownload", C.c_ubyte),
        ("byOptimalStreamType", C.c_ubyte),
        ("byRes2", C.c_ubyte * 20),
    ]


class NET_DVR_FILECOND_V40(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("lChannel", C.c_int32),
        ("dwFileType", C.c_uint32),
        ("dwIsLocked", C.c_uint32),
        ("dwUseCardNo", C.c_uint32),
        ("sCardNumber", C.c_ubyte * CARDNUM_LEN_OUT),
        ("struStartTime", NET_DVR_TIME),
        ("struStopTime", NET_DVR_TIME),
        ("byDrawFrame", C.c_ubyte),
        ("byFindType", C.c_ubyte),
        ("byQuickSearch", C.c_ubyte),
        ("bySpecialFindInfoType", C.c_ubyte),
        ("dwVolumeNum", C.c_uint32),
        ("byWorkingDeviceGUID", C.c_ubyte * GUID_LEN),
        ("uSpecialFindInfo", C.c_ubyte * SPECIAL_FIND_INFO_LEN),
        ("byStreamType", C.c_ubyte),
        ("byAudioFile", C.c_ubyte),
        ("byRes2", C.c_ubyte * 30),
    ]


class NET_DVR_FINDDATA_V40(C.Structure):
    _pack_ = 1
    _fields_ = [
        ("sFileName", C.c_ubyte * NET_DVR_FILE_NAME_LEN),
        ("struStartTime", NET_DVR_TIME),
        ("struStopTime", NET_DVR_TIME),
        ("dwFileSize", C.c_uint32),
        ("sCardNum", C.c_ubyte * CARDNUM_LEN_OUT),
        ("byLocked", C.c_ubyte),
        ("byFileType", C.c_ubyte),
        ("byQuickSearch", C.c_ubyte),
        ("byRes", C.c_ubyte),
        ("dwFileIndex", C.c_uint32),
        ("byStreamType", C.c_ubyte),
        ("byRes1", C.c_ubyte * 127),
    ]


PLAY_DATA_CALLBACK = C.CFUNCTYPE(
    None,
    C.c_int32,
    C.c_uint32,
    C.c_void_p,
    C.c_uint32,
    C.c_uint32,
)


def fill_bytes(target: C.Array, value: str) -> None:
    """Write UTF-8 bytes into a fixed-size unsigned char array with zero padding."""
    raw = value.encode("utf-8")
    max_len = len(target)
    n = min(len(raw), max_len - 1 if max_len > 0 else 0)
    for i in range(max_len):
        target[i] = 0
    for i in range(n):
        target[i] = raw[i]


def to_sdk_time(value: datetime) -> NET_DVR_TIME:
    t = NET_DVR_TIME()
    t.dwYear = value.year
    t.dwMonth = value.month
    t.dwDay = value.day
    t.dwHour = value.hour
    t.dwMinute = value.minute
    t.dwSecond = value.second
    return t


def from_sdk_time(value: NET_DVR_TIME) -> datetime:
    year = int(value.dwYear) or 1970
    month = min(max(int(value.dwMonth), 1), 12)
    day = min(max(int(value.dwDay), 1), 31)
    hour = min(max(int(value.dwHour), 0), 23)
    minute = min(max(int(value.dwMinute), 0), 59)
    second = min(max(int(value.dwSecond), 0), 59)
    return datetime(year, month, day, hour, minute, second)


@dataclass(slots=True)
class LoginResult:
    user_id: int
    start_channel: int
    analog_channels: int
    digital_start_channel: int
