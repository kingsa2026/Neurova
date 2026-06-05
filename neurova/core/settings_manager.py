from __future__ import annotations

"""
系统设置管理器 - Settings Manager

提供系统设置的统一管理：
1. 用户语言偏好
2. 时区设置
3. 用户工作空间管理
"""

import json
import logging
import os
from pathlib import Path
import threading
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class SettingsManager:
    """
    系统设置管理器
    
    管理用户语言偏好、时区设置和工作空间配置。
    支持持久化到 JSON 文件。
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化设置管理器
        
        Args:
            config: 配置字典，包含 data_dir 等配置
        """
        self._lock = threading.RLock()
        self._config = config or {}
        
        # 默认设置
        self._settings: Dict[str, Any] = {
            "language": "zh-CN",
            "timezone": "Asia/Shanghai",
            "workspace": None,
            "theme": "light",
            "font_size": 14,
            "auto_save": True,
            "notifications": True,
            "debug_mode": False
        }
        
        # 数据目录
        self._data_dir = Path(self._config.get("data_dir", "data"))
        self._settings_file = self._data_dir / "settings.json"
        
        # 确保目录存在
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载保存的设置
        self._load_settings()
        
        logger.info("SettingsManager 初始化完成")
    
    def _load_settings(self) -> None:
        """从文件加载设置"""
        try:
            if self._settings_file.exists():
                with open(self._settings_file, 'r', encoding='utf-8') as f:
                    saved_settings = json.load(f)
                    # 合并设置，保留默认值
                    self._settings.update(saved_settings)
                logger.debug(f"从文件加载设置: {self._settings_file}")
        except Exception as e:
            logger.error(f"加载设置失败: {e}")
    
    def _save_settings_sync(self) -> None:
        """同步保存设置到文件"""
        try:
            with open(self._settings_file, 'w', encoding='utf-8') as f:
                json.dump(self._settings, f, ensure_ascii=False, indent=2)
            logger.debug(f"设置已保存到: {self._settings_file}")
        except Exception as e:
            logger.error(f"保存设置失败: {e}")
    
    async def _save_settings(self) -> None:
        """异步保存设置到文件（内部使用同步版本）"""
        self._save_settings_sync()
    
    def get_user_language(self, user_id: str = "default") -> str:
        """
        获取用户语言偏好
        
        Args:
            user_id: 用户ID，默认为"default"
            
        Returns:
            语言代码，如 "zh-CN", "en-US"
        """
        with self._lock:
            key = f"user_{user_id}_language"
            return self._settings.get(key, self._settings.get("language", "zh-CN"))
    
    def set_user_language(self, language: str, user_id: str = "default") -> bool:
        """
        设置用户语言偏好
        
        Args:
            language: 语言代码
            user_id: 用户ID
            
        Returns:
            是否设置成功
        """
        with self._lock:
            try:
                key = f"user_{user_id}_language"
                self._settings[key] = language
                self._save_settings_sync()
                logger.info(f"用户 {user_id} 语言设置为: {language}")
                return True
            except Exception as e:
                logger.error(f"设置语言失败: {e}")
                return False
    
    def get_user_timezone(self, user_id: str = "default") -> str:
        """
        获取用户时区设置
        
        Args:
            user_id: 用户ID
            
        Returns:
            时区字符串，如 "Asia/Shanghai"
        """
        with self._lock:
            key = f"user_{user_id}_timezone"
            return self._settings.get(key, self._settings.get("timezone", "Asia/Shanghai"))
    
    def set_user_timezone(self, timezone: str, user_id: str = "default") -> bool:
        """
        设置用户时区
        
        Args:
            timezone: 时区字符串
            user_id: 用户ID
            
        Returns:
            是否设置成功
        """
        with self._lock:
            try:
                key = f"user_{user_id}_timezone"
                self._settings[key] = timezone
                self._save_settings_sync()
                logger.info(f"用户 {user_id} 时区设置为: {timezone}")
                return True
            except Exception as e:
                logger.error(f"设置时区失败: {e}")
                return False
    
    def get_user_workspace(self, user_id: str = "default") -> Optional[str]:
        """
        获取用户工作空间路径
        
        Args:
            user_id: 用户ID
            
        Returns:
            工作空间路径，未设置返回 None
        """
        with self._lock:
            key = f"user_{user_id}_workspace"
            return self._settings.get(key, self._settings.get("workspace"))
    
    def set_user_workspace(self, workspace: str, user_id: str = "default") -> bool:
        """
        设置用户工作空间
        
        Args:
            workspace: 工作空间路径
            user_id: 用户ID
            
        Returns:
            是否设置成功
        """
        with self._lock:
            try:
                key = f"user_{user_id}_workspace"
                self._settings[key] = workspace
                self._save_settings_sync()
                logger.info(f"用户 {user_id} 工作空间设置为: {workspace}")
                return True
            except Exception as e:
                logger.error(f"设置工作空间失败: {e}")
                return False
    
    def get_all_settings(self, user_id: str = "default") -> Dict[str, Any]:
        """
        获取用户所有设置
        
        Args:
            user_id: 用户ID
            
        Returns:
            设置字典
        """
        with self._lock:
            result = {}
            # 获取默认设置
            for key in ["language", "timezone", "workspace", "theme", "font_size", 
                       "auto_save", "notifications", "debug_mode"]:
                user_key = f"user_{user_id}_{key}"
                result[key] = self._settings.get(user_key, self._settings.get(key))
            return result
    
    def update_settings(self, settings: Dict[str, Any], user_id: str = "default") -> bool:
        """
        批量更新用户设置
        
        Args:
            settings: 要更新的设置字典
            user_id: 用户ID
            
        Returns:
            是否更新成功
        """
        with self._lock:
            try:
                for key, value in settings.items():
                    if key in ["language", "timezone", "workspace", "theme", 
                              "font_size", "auto_save", "notifications", "debug_mode"]:
                        user_key = f"user_{user_id}_{key}"
                        self._settings[user_key] = value
                
                self._save_settings_sync()
                logger.info(f"用户 {user_id} 设置已更新")
                return True
            except Exception as e:
                logger.error(f"更新设置失败: {e}")
                return False
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        获取单个设置值
        
        Args:
            key: 设置键名
            default: 默认值
            
        Returns:
            设置值
        """
        with self._lock:
            return self._settings.get(key, default)
    
    def set_setting(self, key: str, value: Any) -> bool:
        """
        设置单个设置值
        
        Args:
            key: 设置键名
            value: 设置值
            
        Returns:
            是否设置成功
        """
        with self._lock:
            try:
                self._settings[key] = value
                self._save_settings_sync()
                return True
            except Exception as e:
                logger.error(f"设置值失败: {e}")
                return False
    
    def reset_settings(self, user_id: str = "default") -> bool:
        """
        重置用户设置为默认值
        
        Args:
            user_id: 用户ID
            
        Returns:
            是否重置成功
        """
        with self._lock:
            try:
                # 移除用户特定设置
                keys_to_remove = [k for k in self._settings.keys() 
                                 if k.startswith(f"user_{user_id}_")]
                for key in keys_to_remove:
                    del self._settings[key]
                
                self._save_settings_sync()
                logger.info(f"用户 {user_id} 设置已重置为默认值")
                return True
            except Exception as e:
                logger.error(f"重置设置失败: {e}")
                return False
    
    def _on_init(self) -> None:
        """模块初始化回调"""
        logger.debug("SettingsManager 模块初始化")
    
    def _on_start(self) -> None:
        """模块启动回调"""
        logger.debug("SettingsManager 模块启动")
    
    def _on_stop(self) -> None:
        """模块停止回调"""
        # 保存设置
        self._save_settings_sync()
        logger.debug("SettingsManager 模块停止")


# 全局实例管理
_settings_manager: Optional[SettingsManager] = None
_manager_lock = threading.Lock()


def get_settings_manager(config: Dict[str, Any] = None) -> SettingsManager:
    """
    获取设置管理器全局实例
    
    Args:
        config: 配置字典
        
    Returns:
        SettingsManager 实例
    """
    global _settings_manager
    if _settings_manager is None:
        with _manager_lock:
            if _settings_manager is None:
                _settings_manager = SettingsManager(config)
    return _settings_manager


def reset_settings_manager() -> None:
    """
    重置设置管理器全局实例
    """
    global _settings_manager
    with _manager_lock:
        if _settings_manager is not None:
            _settings_manager._on_stop()
        _settings_manager = None