"""
Workspace - Encapsulates a complete independent agent runtime for Neurova

Each Workspace represents a standalone agent workspace with its own:
- MemoryManager
- ServiceManager
- Configuration
- Working directory
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class Workspace:
    """
    Agent 工作空间

    封装一个完整的 Agent 运行时环境，包括记忆、服务、配置等。
    """

    def __init__(
        self,
        workspace_id: str,
        data_dir: Path,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            workspace_id: 工作空间唯一标识
            data_dir: 数据目录
            config: 配置
        """
        self._workspace_id = workspace_id
        self._data_dir = Path(data_dir)
        self._config = config or {}
        self._lock = threading.RLock()

        # 管理器引用
        self._memory_manager: Optional[Any] = None
        self._channel_manager: Optional[Any] = None
        self._skill_manager: Optional[Any] = None
        self._project_manager: Optional[Any] = None
        self._cron_manager: Optional[Any] = None

        # 可复用服务
        self._reusable_services: Dict[str, Any] = {}

        # 状态
        self._started = False

        # 确保目录存在
        self._data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def workspace_id(self) -> str:
        """工作空间ID"""
        return self._workspace_id

    @property
    def data_dir(self) -> Path:
        """数据目录"""
        return self._data_dir

    @property
    def config(self) -> Dict[str, Any]:
        """配置"""
        return self._config

    @property
    def memory_manager(self) -> Optional[Any]:
        """记忆管理器"""
        return self._memory_manager

    @memory_manager.setter
    def memory_manager(self, value: Any) -> None:
        self._memory_manager = value

    @property
    def channel_manager(self) -> Optional[Any]:
        """渠道管理器"""
        return self._channel_manager

    @channel_manager.setter
    def channel_manager(self, value: Any) -> None:
        self._channel_manager = value

    @property
    def skill_manager(self) -> Optional[Any]:
        """技能管理器"""
        return self._skill_manager

    @skill_manager.setter
    def skill_manager(self, value: Any) -> None:
        self._skill_manager = value

    @property
    def project_manager(self) -> Optional[Any]:
        """项目管理器"""
        return self._project_manager

    @project_manager.setter
    def project_manager(self, value: Any) -> None:
        self._project_manager = value

    @property
    def cron_manager(self) -> Optional[Any]:
        """定时任务管理器"""
        return self._cron_manager

    @cron_manager.setter
    def cron_manager(self, value: Any) -> None:
        self._cron_manager = value

    @property
    def started(self) -> bool:
        """是否已启动"""
        return self._started

    def set_manager(self, name: str, manager: Any) -> None:
        """
        设置管理器

        Args:
            name: 管理器名称 (memory, channel, skill, project, cron)
            manager: 管理器实例
        """
        with self._lock:
            setter_map = {
                "memory": lambda m: setattr(self, "_memory_manager", m),
                "channel": lambda m: setattr(self, "_channel_manager", m),
                "skill": lambda m: setattr(self, "_skill_manager", m),
                "project": lambda m: setattr(self, "_project_manager", m),
                "cron": lambda m: setattr(self, "_cron_manager", m),
            }

            setter = setter_map.get(name)
            if setter:
                setter(manager)
                logger.info("Set manager '%s' for workspace '%s'", name, self._workspace_id)
            else:
                # 存储为自定义管理器
                self._reusable_services[name] = manager
                logger.info("Set custom manager '%s' for workspace '%s'", name, self._workspace_id)

    def _register_services(self) -> None:
        """注册内部服务"""
        # 注册可复用服务到各个管理器

    def start(self) -> bool:
        """
        启动工作空间

        Returns:
            是否启动成功
        """
        if self._started:
            logger.warning("Workspace '%s' already started", self._workspace_id)
            return True

        try:
            with self._lock:
                # 1. 注册服务
                self._register_services()

                # 2. 启动记忆管理器
                if self._memory_manager and hasattr(self._memory_manager, "start"):
                    self._memory_manager.start()

                # 3. 启动渠道管理器
                if self._channel_manager and hasattr(self._channel_manager, "start"):
                    self._channel_manager.start()

                # 4. 启动定时任务管理器
                if self._cron_manager and hasattr(self._cron_manager, "start"):
                    self._cron_manager.start()

                self._started = True

            logger.info("Workspace '%s' started", self._workspace_id)
            return True

        except Exception as e:
            logger.error("Failed to start workspace '%s': %s", self._workspace_id, e)
            return False

    def stop(self) -> bool:
        """
        停止工作空间

        Returns:
            是否停止成功
        """
        if not self._started:
            return True

        try:
            with self._lock:
                # 按相反顺序停止
                if self._cron_manager and hasattr(self._cron_manager, "stop"):
                    self._cron_manager.stop()

                if self._channel_manager and hasattr(self._channel_manager, "stop"):
                    self._channel_manager.stop()

                if self._memory_manager and hasattr(self._memory_manager, "stop"):
                    self._memory_manager.stop()

                self._started = False

            logger.info("Workspace '%s' stopped", self._workspace_id)
            return True

        except Exception as e:
            logger.error("Failed to stop workspace '%s': %s", self._workspace_id, e)
            return False

    def get_reusable_services(self) -> Dict[str, Any]:
        """获取可复用服务"""
        with self._lock:
            return dict(self._reusable_services)

    def set_reusable_services(self, services: Dict[str, Any]) -> None:
        """设置可复用服务"""
        with self._lock:
            self._reusable_services.update(services)

    def get_status(self) -> Dict[str, Any]:
        """获取工作空间状态"""
        with self._lock:
            return {
                "workspace_id": self._workspace_id,
                "data_dir": str(self._data_dir),
                "started": self._started,
                "managers": {
                    "memory": self._memory_manager is not None,
                    "channel": self._channel_manager is not None,
                    "skill": self._skill_manager is not None,
                    "project": self._project_manager is not None,
                    "cron": self._cron_manager is not None,
                },
                "reusable_services": list(self._reusable_services.keys()),
            }


# 全局工作空间管理
_workspaces: Dict[str, Workspace] = {}
_workspace_lock = threading.Lock()


def get_workspace(workspace_id: str) -> Optional[Workspace]:
    """获取工作空间"""
    with _workspace_lock:
        return _workspaces.get(workspace_id)


def create_workspace(
    workspace_id: str,
    data_dir: Path,
    config: Optional[Dict[str, Any]] = None,
) -> Workspace:
    """创建工作空间"""
    with _workspace_lock:
        if workspace_id in _workspaces:
            raise ValueError(f"Workspace '{workspace_id}' already exists")

        workspace = Workspace(
            workspace_id=workspace_id,
            data_dir=data_dir,
            config=config,
        )
        _workspaces[workspace_id] = workspace
        return workspace


def list_workspaces() -> List[str]:
    """列出所有工作空间"""
    with _workspace_lock:
        return list(_workspaces.keys())


def remove_workspace(workspace_id: str) -> bool:
    """移除工作空间"""
    with _workspace_lock:
        workspace = _workspaces.pop(workspace_id, None)
        if workspace:
            workspace.stop()
            return True
        return False


def reset_workspaces() -> None:
    """重置所有工作空间（用于测试）"""
    global _workspaces
    with _workspace_lock:
        for ws in _workspaces.values():
            ws.stop()
        _workspaces = {}
