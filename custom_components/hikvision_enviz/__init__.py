"""The Hikvision Enviz Camera integration."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .hikvision_api import HikvisionEnvizAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CAMERA]

def install_system_dependencies():
    """Install required system dependencies."""
    try:
        # 检查并安装必要的系统依赖
        os.system("apk update")
        os.system("apk add libc6-compat build-base opencv")
        return True
    except Exception as e:
        _LOGGER.error("Failed to install system dependencies: %s", str(e))
        return False

def copy_lib_files(hass: HomeAssistant):
    """Copy library files to system lib directory."""
    try:
        # 首先安装系统依赖
        if not install_system_dependencies():
            _LOGGER.error("Failed to install system dependencies")
            return False
            
        # 获取插件lib目录路径
        component_path = Path(__file__).parent
        lib_path = component_path / "lib"
        
        # 目标系统lib目录
        system_lib = "/lib"
        
        if not os.path.exists(system_lib):
            os.makedirs(system_lib)
            
        # 复制所有.so文件
        for file in lib_path.glob("*.so*"):
            dest_file = Path(system_lib) / file.name
            if not dest_file.exists():
                shutil.copy2(str(file), str(dest_file))
                os.chmod(str(dest_file), 0o755)
                _LOGGER.info("Copied %s to system lib", file.name)
                
        # 复制HCNetSDKCom
        sdk_com_path = Path(system_lib) / "HCNetSDKCom"
        if not sdk_com_path.exists():
            shutil.copytree(str(lib_path / "HCNetSDKCom"), str(sdk_com_path))
            _LOGGER.info("Copied HCNetSDKCom directory to system lib")
            
        return True
            
    except Exception as e:
        _LOGGER.error("Failed to copy library files: %s", str(e))
        return False

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Hikvision Enviz component."""
    hass.data.setdefault(DOMAIN, {})
    
    # 复制依赖库文件
    if not copy_lib_files(hass):
        _LOGGER.error("Failed to setup required libraries")
        return False
        
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hikvision Enviz Camera from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    api = HikvisionEnvizAPI(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )

    try:
        if not await api.connect():
            return False
    except Exception as e:
        _LOGGER.error("Failed to connect to Hikvision camera: %s", str(e))
        return False

    hass.data[DOMAIN][entry.entry_id] = api

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        api = hass.data[DOMAIN].pop(entry.entry_id)
        await api.disconnect()

    return unload_ok 