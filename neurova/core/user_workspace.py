"""
Neurova 用户工作空间数据隔离管理器

功能:
1. 每个用户独立的工作空间目录
2. 用户数据完全隔离
3. 动态创建和切换用户工作空间
4. 与 language、时区系统集成
"""

import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import threading
import typing
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class UserWorkspace:
    """
    用户工作空间
    
    管理单个用户的独立工作空间目录。
    """
    
    def __init__(self, user_id: str, base_path: Path, config: Dict[str, Any] = None):
        """
        初始化用户工作空间
        
        Args:
            user_id: 用户ID
            base_path: 基础路径
            config: 配置字典
        """
        self.user_id = user_id
        self.base_path = base_path
        self._config = config or {}
        
        # 用户工作空间根目录
        self.root_path = base_path / user_id
        
        # 确保目录存在
        self._ensure_directories()
        
        # 加载配置
        self._user_config = self._load_config()
        
        logger.debug(f"用户工作空间初始化: {user_id}")
    
    def _ensure_directories(self) -> None:
        """确保目录结构存在"""
        directories = [
            self.root_path,
            self.root_path / "database",
            self.root_path / "memory",
            self.root_path / "projects",
            self.root_path / "skills",
            self.root_path / "channels",
            self.root_path / "workflows",
            self.root_path / "attachments",
            self.root_path / "logs",
            self.root_path / "cache"
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
    
    def _load_config(self) -> Dict[str, Any]:
        """
        加载用户配置
        
        Returns:
            配置字典
        """
        config_file = self.root_path / "config.json"
        
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载用户配置失败: {e}")
        
        # 返回默认配置
        return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """
        获取默认配置
        
        Returns:
            默认配置字典
        """
        return {
            "language": "zh-CN",
            "timezone": "Asia/Shanghai",
            "theme": "light",
            "font_size": 14,
            "auto_save": True,
            "notifications": True,
            "debug_mode": False,
            "created_at": self._get_current_time(),
            "last_active": self._get_current_time()
        }
    
    def save_config(self) -> None:
        """保存用户配置"""
        config_file = self.root_path / "config.json"
        
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(self._user_config, f, ensure_ascii=False, indent=2)
            logger.debug(f"用户配置已保存: {self.user_id}")
        except Exception as e:
            logger.error(f"保存用户配置失败: {e}")
    
    def get_config(self, key: str = None, default: Any = None) -> Any:
        """
        获取配置
        
        Args:
            key: 配置键名
            default: 默认值
            
        Returns:
            配置值
        """
        if key is None:
            return self._user_config.copy()
        
        return self._user_config.get(key, default)
    
    def set_config(self, key: str, value: Any) -> None:
        """
        设置配置
        
        Args:
            key: 配置键名
            value: 配置值
        """
        self._user_config[key] = value
        self.save_config()
    
    def _get_current_time(self) -> str:
        """
        获取当前时间字符串
        
        Returns:
            ISO格式时间字符串
        """
        return datetime.datetime.now().isoformat()
    
    @property
    def database_path(self) -> Path:
        """数据库路径"""
        return self.root_path / "database"
    
    @property
    def memory_path(self) -> Path:
        """记忆存储路径"""
        return self.root_path / "memory"
    
    @property
    def projects_path(self) -> Path:
        """项目路径"""
        return self.root_path / "projects"
    
    @property
    def skills_path(self) -> Path:
        """技能路径"""
        return self.root_path / "skills"
    
    @property
    def channels_path(self) -> Path:
        """渠道路径"""
        return self.root_path / "channels"
    
    @property
    def workflows_path(self) -> Path:
        """工作流路径"""
        return self.root_path / "workflows"
    
    @property
    def attachments_path(self) -> Path:
        """附件路径"""
        return self.root_path / "attachments"
    
    @property
    def logs_path(self) -> Path:
        """日志路径"""
        return self.root_path / "logs"
    
    @property
    def cache_path(self) -> Path:
        """缓存路径"""
        return self.root_path / "cache"
    
    def delete(self) -> bool:
        """
        删除工作空间
        
        Returns:
            是否删除成功
        """
        try:
            if self.root_path.exists():
                shutil.rmtree(self.root_path)
                logger.info(f"用户工作空间已删除: {self.user_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"删除用户工作空间失败: {e}")
            return False
    
    def get_size(self) -> int:
        """
        获取工作空间大小
        
        Returns:
            大小（字节）
        """
        total_size = 0
        
        try:
            for path in self.root_path.rglob("*"):
                if path.is_file():
                    total_size += path.stat().st_size
        except Exception as e:
            logger.error(f"计算工作空间大小失败: {e}")
        
        return total_size


class UserWorkspaceManager:
    """
    用户工作空间管理器
    
    管理所有用户的独立工作空间。
    """
    
    def __init__(self, base_path: Path, config: Dict[str, Any] = None):
        """
        初始化用户工作空间管理器
        
        Args:
            base_path: 基础路径
            config: 配置字典
        """
        self.base_path = Path(base_path)
        self._config = config or {}
        self._lock = threading.RLock()
        
        # 工作空间缓存
        self._workspaces: Dict[str, UserWorkspace] = {}
        
        # 确保基础目录存在
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"UserWorkspaceManager 初始化，基础路径: {self.base_path}")
    
    def get_workspace(self, user_id: str) -> UserWorkspace:
        """
        获取用户工作空间
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户工作空间
        """
        with self._lock:
            if user_id not in self._workspaces:
                # 创建新工作空间
                workspace = UserWorkspace(user_id, self.base_path, self._config)
                self._workspaces[user_id] = workspace
            
            return self._workspaces[user_id]
    
    def create_workspace(self, user_id: str) -> UserWorkspace:
        """
        创建用户工作空间
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户工作空间
        """
        with self._lock:
            if user_id in self._workspaces:
                logger.warning(f"工作空间已存在: {user_id}")
                return self._workspaces[user_id]
            
            workspace = UserWorkspace(user_id, self.base_path, self._config)
            self._workspaces[user_id] = workspace
            
            logger.info(f"创建用户工作空间: {user_id}")
            return workspace
    
    def delete_workspace(self, user_id: str) -> bool:
        """
        删除用户工作空间
        
        Args:
            user_id: 用户ID
            
        Returns:
            是否删除成功
        """
        with self._lock:
            if user_id not in self._workspaces:
                logger.warning(f"工作空间不存在: {user_id}")
                return False
            
            workspace = self._workspaces[user_id]
            success = workspace.delete()
            
            if success:
                del self._workspaces[user_id]
            
            return success
    
    def list_workspaces(self) -> List[str]:
        """
        列出所有工作空间
        
        Returns:
            用户ID列表
        """
        with self._lock:
            # 从文件系统扫描
            workspaces = []
            
            if self.base_path.exists():
                for item in self.base_path.iterdir():
                    if item.is_dir():
                        workspaces.append(item.name)
            
            return sorted(workspaces)
    
    def get_all_workspaces(self) -> Dict[str, UserWorkspace]:
        """
        获取所有工作空间
        
        Returns:
            工作空间字典
        """
        with self._lock:
            # 确保所有工作空间都已加载
            for user_id in self.list_workspaces():
                if user_id not in self._workspaces:
                    self._workspaces[user_id] = UserWorkspace(user_id, self.base_path, self._config)
            
            return self._workspaces.copy()
    
    def workspace_exists(self, user_id: str) -> bool:
        """
        检查工作空间是否存在
        
        Args:
            user_id: 用户ID
            
        Returns:
            是否存在
        """
        with self._lock:
            workspace_path = self.base_path / user_id
            return workspace_path.exists() and workspace_path.is_dir()
    
    def get_workspace_stats(self) -> Dict[str, Any]:
        """
        获取工作空间统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            workspaces = self.list_workspaces()
            total_size = 0
            
            for user_id in workspaces:
                workspace = self.get_workspace(user_id)
                total_size += workspace.get_size()
            
            return {
                "total_workspaces": len(workspaces),
                "total_size": total_size,
                "base_path": str(self.base_path),
                "workspaces": workspaces
            }


# 全局实例管理
_workspace_manager: Optional[UserWorkspaceManager] = None
_manager_lock = threading.Lock()


def get_workspace_manager(base_path: Path = None, config: Dict[str, Any] = None) -> UserWorkspaceManager:
    """
    获取全局工作空间管理器实例
    
    Args:
        base_path: 基础路径
        config: 配置字典
        
    Returns:
        UserWorkspaceManager 实例
    """
    global _workspace_manager
    if _workspace_manager is None:
        with _manager_lock:
            if _workspace_manager is None:
                if base_path is None:
                    base_path = Path("data/workspaces")
                _workspace_manager = UserWorkspaceManager(base_path, config)
    return _workspace_manager


def init_workspace_manager(base_path: Path, config: Dict[str, Any] = None) -> UserWorkspaceManager:
    """
    初始化全局工作空间管理器
    
    Args:
        base_path: 基础路径
        config: 配置字典
        
    Returns:
        UserWorkspaceManager 实例
    """
    global _workspace_manager
    with _manager_lock:
        if _workspace_manager is not None:
            logger.warning("UserWorkspaceManager 已初始化，将重新创建")
        
        _workspace_manager = UserWorkspaceManager(base_path, config)
        return _workspace_manager


def reset_workspace_manager() -> None:
    """
    重置全局工作空间管理器
    """
    global _workspace_manager
    with _manager_lock:
        _workspace_manager = None