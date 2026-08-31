from __future__ import annotations

"""
Infrastructure Manager - 基础设施管理器（脊髓）

所有 Agent 共用的基础设施，负责：
- Service Manager（服务管理）
- Provider Manager（LLM 提供商管理）
- Event Bus（事件总线）
- Config Manager（配置管理）

采用单例模式，确保多个 Agent 共用同一套基础设施。
"""

import datetime
import json
from neurova.core.logger import get_logger
import threading
import typing
from dataclasses import dataclass, field
from pathlib import Path

# core imports
from neurova.core.event_bus import EventBus
from neurova.core.service_manager import ServiceManager
from neurova.llm.provider_manager import LLMProviderManager, get_provider_manager

logger = get_logger(__name__)


@dataclass
class InfrastructureConfig:
    """基础设施配置"""

    config_path: Path = field(default_factory=lambda: Path("config/infrastructure.json"))
    auto_start: bool = True
    enable_event_bus: bool = True
    enable_service_manager: bool = True
    enable_provider_manager: bool = True
    log_level: str = "INFO"
    max_workers: int = 4

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "config_path": str(self.config_path),
            "auto_start": self.auto_start,
            "enable_event_bus": self.enable_event_bus,
            "enable_service_manager": self.enable_service_manager,
            "enable_provider_manager": self.enable_provider_manager,
            "log_level": self.log_level,
            "max_workers": self.max_workers,
        }

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "InfrastructureConfig":
        """从字典创建配置"""
        config = cls()
        if "config_path" in data:
            config.config_path = Path(data["config_path"])
        if "auto_start" in data:
            config.auto_start = data["auto_start"]
        if "enable_event_bus" in data:
            config.enable_event_bus = data["enable_event_bus"]
        if "enable_service_manager" in data:
            config.enable_service_manager = data["enable_service_manager"]
        if "enable_provider_manager" in data:
            config.enable_provider_manager = data["enable_provider_manager"]
        if "log_level" in data:
            config.log_level = data["log_level"]
        if "max_workers" in data:
            config.max_workers = data["max_workers"]
        return config


class InfrastructureManager:
    """
    基础设施管理器

    单例模式，管理所有基础设施组件。
    """

    _instance: typing.Optional["InfrastructureManager"] = None
    _lock = threading.RLock()

    def __new__(cls, config: InfrastructureConfig = None):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, config: InfrastructureConfig = None):
        if self._initialized:
            return

        self._config = config or InfrastructureConfig()
        self._event_bus: typing.Optional[EventBus] = None
        self._provider_manager: typing.Optional[LLMProviderManager] = None
        self._service_manager: typing.Optional[ServiceManager] = None
        self._running = False
        self._start_time: typing.Optional[datetime.datetime] = None
        self._lock = threading.RLock()

        # 初始化组件
        self._init_components()

        self._initialized = True
        logger.info("InfrastructureManager 初始化完成")

    def _init_components(self) -> None:
        """初始化基础设施组件"""
        with self._lock:
            # 初始化事件总线
            if self._config.enable_event_bus:
                self._event_bus = EventBus()
                logger.debug("EventBus 初始化完成")

            # 初始化服务管理器
            if self._config.enable_service_manager:
                self._service_manager = ServiceManager()
                logger.debug("ServiceManager 初始化完成")

            # 初始化 Provider Manager
            if self._config.enable_provider_manager:
                self._provider_manager = get_provider_manager()
                logger.debug("LLMProviderManager 初始化完成")

    async def start(self) -> None:
        """启动基础设施"""
        if self._running:
            logger.warning("InfrastructureManager 已经在运行")
            return

        with self._lock:
            try:
                # 启动事件总线
                if self._event_bus:
                    self._event_bus.start()

                # 启动 Provider Manager
                if self._provider_manager:
                    await self._provider_manager.initialize()

                self._running = True
                self._start_time = datetime.datetime.now()
                logger.info("InfrastructureManager 启动成功")

            except Exception as e:
                logger.error("InfrastructureManager 启动失败: %s", e)
                raise

    async def stop(self) -> None:
        """停止基础设施"""
        if not self._running:
            logger.warning("InfrastructureManager 未在运行")
            return

        with self._lock:
            try:
                # 停止事件总线
                if self._event_bus:
                    self._event_bus.stop()

                # 停止 Provider Manager
                if self._provider_manager:
                    await self._provider_manager.shutdown()

                self._running = False
                logger.info("InfrastructureManager 停止成功")

            except Exception as e:
                logger.error("InfrastructureManager 停止失败: %s", e)
                raise

    def get_event_bus(self) -> typing.Optional[EventBus]:
        """获取事件总线"""
        return self._event_bus

    def get_provider_manager(self) -> typing.Optional[LLMProviderManager]:
        """获取 Provider Manager"""
        return self._provider_manager

    def create_service_manager(self, config: typing.Dict[str, typing.Any] = None) -> ServiceManager:
        """创建服务管理器"""
        with self._lock:
            if self._service_manager is None:
                self._service_manager = ServiceManager(config)
                logger.debug("ServiceManager 创建完成")
            return self._service_manager

    def get_service_manager(self) -> typing.Optional[ServiceManager]:
        """获取服务管理器"""
        return self._service_manager

    async def health_check(self) -> typing.Dict[str, typing.Any]:
        """健康检查"""
        status = {
            "status": "healthy" if self._running else "stopped",
            "timestamp": datetime.datetime.now().isoformat(),
            "components": {},
        }

        # 检查事件总线
        if self._event_bus:
            status["components"]["event_bus"] = {
                "status": "running" if self._event_bus._running else "stopped",
                "subscribers": len(self._event_bus._subscribers),
            }

        # 检查 Provider Manager
        if self._provider_manager:
            try:
                providers = self._provider_manager.list_providers()
                status["components"]["provider_manager"] = {"status": "running", "providers": len(providers)}
            except Exception as e:
                status["components"]["provider_manager"] = {"status": "error", "error": str(e)}

        # 检查服务管理器
        if self._service_manager:
            status["components"]["service_manager"] = {
                "status": "running",
                "services": len(self._service_manager._services),
            }

        return status

    def update_config(self, new_config: typing.Dict[str, typing.Any]) -> None:
        """更新配置"""
        with self._lock:
            self._config = InfrastructureConfig.from_dict(new_config)
            logger.info("配置已更新")

    def save_config(self) -> None:
        """保存配置到文件"""
        try:
            config_path = self._config.config_path
            config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self._config.to_dict(), f, indent=2, ensure_ascii=False)

            logger.info("配置已保存到: %s", config_path)

        except Exception as e:
            logger.error("保存配置失败: %s", e)
            raise

    def load_config(self) -> None:
        """从文件加载配置"""
        try:
            config_path = self._config.config_path
            if not config_path.exists():
                logger.warning("配置文件不存在: %s", config_path)
                return

            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._config = InfrastructureConfig.from_dict(data)
            logger.info("配置已从 %s 加载", config_path)

        except Exception as e:
            logger.error("加载配置失败: %s", e)
            raise

    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running

    def uptime(self) -> typing.Optional[float]:
        """运行时间（秒）"""
        if not self._running or not self._start_time:
            return None
        return (datetime.datetime.now() - self._start_time).total_seconds()

    def get_status(self) -> typing.Dict[str, typing.Any]:
        """获取状态信息"""
        return {
            "running": self._running,
            "uptime": self.uptime(),
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "config": self._config.to_dict(),
            "components": {
                "event_bus": self._event_bus is not None,
                "provider_manager": self._provider_manager is not None,
                "service_manager": self._service_manager is not None,
            },
        }


# 工厂函数
_infrastructure_manager: typing.Optional[InfrastructureManager] = None
_infrastructure_manager_lock = __import__('threading').Lock()


def get_infrastructure_manager(config: InfrastructureConfig = None) -> InfrastructureManager:
    """获取基础设施管理器单例"""
    global _infrastructure_manager
    if _infrastructure_manager is None:
        # P3-e：DCL——InfrastructureManager 持后台资源，不可双创建
        with _infrastructure_manager_lock:
            if _infrastructure_manager is None:
                _infrastructure_manager = InfrastructureManager(config)
    return _infrastructure_manager


def reset_infrastructure_manager() -> None:
    """重置基础设施管理器（用于测试）"""
    global _infrastructure_manager
    _infrastructure_manager = None
