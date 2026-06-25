from __future__ import annotations

"""
Neurova 启动管理器

核心功能:
1. 加载启动配置
2. 注册模块
3. 解析依赖关系
4. 按正确顺序启动模块
5. 生命周期管理
6. 健康检查
"""

from neurova.core.logger import get_logger
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Type

from neurova.core.event_bus import get_event_bus
from neurova.core.module_system import (
    Module,
    ModuleRegistry,
    StartupResult,
)

logger = get_logger(__name__)


@dataclass
class StartupConfig:
    """启动配置"""

    startup_timeout: float = 60.0
    health_check_interval: float = 30.0
    auto_recovery: bool = True
    log_level: str = "INFO"
    data_dir: str = "data"
    config_file: str = "startup.json"


class StartupManager:
    """
    启动管理器

    管理系统模块的启动、停止和健康检查。
    """

    def __init__(self, config: Optional[StartupConfig] = None):
        self._config = config or StartupConfig()
        self._registry = ModuleRegistry()
        self._event_bus = get_event_bus()
        self._started = False
        self._start_time: Optional[float] = None
        self._shutdown_hooks: List[Callable] = []
        self._lock = threading.RLock()
        logger.info("StartupManager initialized")

    @property
    def config(self) -> StartupConfig:
        return self._config

    @property
    def registry(self) -> ModuleRegistry:
        return self._registry

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def uptime(self) -> float:
        if self._start_time:
            return time.time() - self._start_time
        return 0.0

    def register_module(
        self,
        name: str,
        module_class: Type[Module],
        dependencies: List[str] = None,
        **kwargs,
    ) -> None:
        """注册模块"""
        self._registry.register(name, module_class, dependencies, **kwargs)
        logger.info("Registered module: %s", name)

    def register_module_class(
        self, module_class: Type[Module], name: str = None, dependencies: List[str] = None
    ) -> None:
        """通过类注册模块"""
        module_name = name or module_class.__name__
        self.register_module(module_name, module_class, dependencies)

    def register_shutdown_hook(self, hook: Callable) -> None:
        """注册关闭钩子"""
        self._shutdown_hooks.append(hook)

    def start(self) -> StartupResult:
        """
        启动所有模块

        Returns:
            启动结果
        """
        if self._started:
            logger.warning("StartupManager already started")
            return StartupResult(success=True)

        logger.info("Starting Neurova system...")
        self._start_time = time.time()

        # 发布启动事件
        self._event_bus.publish("system.starting", source="StartupManager")

        # 启动所有模块
        result = self._registry.start_all()

        if result.success:
            self._started = True
            logger.info("System started successfully in %.2fs", result.duration)
            logger.info("Modules started: %s", result.modules_started)
            self._event_bus.publish("system.started", data=result, source="StartupManager")
        else:
            logger.error("System startup failed: %s", result.errors)
            self._event_bus.publish("system.startup_failed", data=result, source="StartupManager")

        return result

    def stop(self) -> None:
        """停止所有模块"""
        if not self._started:
            return

        logger.info("Stopping Neurova system...")
        self._event_bus.publish("system.stopping", source="StartupManager")

        # 执行关闭钩子
        for hook in self._shutdown_hooks:
            try:
                hook()
            except Exception as e:
                logger.error("Shutdown hook error: %s", e)

        # 停止所有模块
        self._registry.stop_all()

        self._started = False
        logger.info("System stopped")
        self._event_bus.publish("system.stopped", source="StartupManager")

    def get_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        modules = {}
        for name, info in self._registry.resolver.get_all_modules().items():
            modules[name] = {
                "state": info.state.value,
                "error": info.error,
                "started_at": info.started_at.isoformat() if info.started_at else None,
            }

        return {
            "started": self._started,
            "uptime": self.uptime,
            "modules": modules,
            "total_modules": len(modules),
        }

    def get_module_instance(self, name: str) -> Optional[Module]:
        """获取模块实例"""
        return self._registry.get_instance(name)


# 全局单例
_global_startup_manager: Optional[StartupManager] = None
_manager_lock = threading.Lock()


def get_startup_manager() -> StartupManager:
    """获取全局启动管理器"""
    global _global_startup_manager
    if _global_startup_manager is None:
        with _manager_lock:
            if _global_startup_manager is None:
                _global_startup_manager = StartupManager()
    return _global_startup_manager


def reset_startup_manager() -> None:
    """重置全局启动管理器（主要用于测试）"""
    global _global_startup_manager
    with _manager_lock:
        if _global_startup_manager is not None:
            _global_startup_manager.stop()
        _global_startup_manager = None
