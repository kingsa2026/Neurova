from __future__ import annotations

"""
Neurova 模块化启动系统

核心组件:
- Module: 所有模块的基类
- ModuleState: 模块状态枚举
- DependencyResolver: 依赖解析器
- ModuleRegistry: 模块注册表

设计原则:
1. 声明式注册 - 模块通过配置声明自己的依赖
2. 依赖解析 - 拓扑排序确保启动顺序正确
3. 生命周期管理 - 支持初始化、启动、停止、清理
"""

import enum
import logging
import threading
import time
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Type

logger = logging.getLogger(__name__)


class ModuleState(enum.Enum):
    """模块状态"""

    CREATED = "created"  # 已创建
    INITIALIZED = "initialized"  # 已初始化
    STARTING = "starting"  # 启动中
    RUNNING = "running"  # 运行中
    STOPPING = "stopping"  # 停止中
    STOPPED = "stopped"  # 已停止
    ERROR = "error"  # 错误


@dataclass
class ModuleInfo:
    """模块信息"""

    name: str
    module_class: Type["Module"]
    dependencies: List[str] = field(default_factory=list)
    description: str = ""
    version: str = "1.0.0"
    state: ModuleState = ModuleState.CREATED
    instance: Optional["Module"] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None


@dataclass
class StartupResult:
    """启动结果"""

    success: bool
    modules_started: List[str] = field(default_factory=list)
    modules_failed: List[str] = field(default_factory=list)
    errors: Dict[str, str] = field(default_factory=dict)
    duration: float = 0.0


class Module(ABC):
    """
    模块基类 - 所有系统模块的抽象基类

    子类需要实现:
    - name: 模块名称
    - _on_init(): 初始化逻辑
    - _on_start(): 启动逻辑
    - _on_stop(): 停止逻辑
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, event_bus=None, **kwargs):
        self._config = config or {}
        self._event_bus = event_bus
        self._state = ModuleState.CREATED
        self._logger = logging.getLogger(f"neurova.module.{self.name}")
        self._lock = threading.RLock()

    @property
    def name(self) -> str:
        """模块名称"""
        return self.__class__.__name__

    @property
    def state(self) -> ModuleState:
        """模块状态"""
        return self._state

    def _log(self, level: str, message: str, **kwargs) -> None:
        """记录日志"""
        log_func = getattr(self._logger, level, self._logger.info)
        log_func(f"[{self.name}] {message}", **kwargs)

    def log_error(self, message: str, **kwargs) -> None:
        """记录错误"""
        self._log("error", message, **kwargs)

    def initialize(self) -> bool:
        """初始化模块"""
        with self._lock:
            if self._state != ModuleState.CREATED:
                return self._state == ModuleState.INITIALIZED
            try:
                self._state = ModuleState.INITIALIZED
                self._on_init()
                self._log("info", "Module initialized")
                return True
            except Exception as e:
                self._state = ModuleState.ERROR
                self.log_error(f"Initialization failed: {e}")
                return False

    def start(self) -> bool:
        """启动模块"""
        with self._lock:
            if self._state not in (ModuleState.INITIALIZED, ModuleState.STOPPED):
                return self._state == ModuleState.RUNNING
            try:
                self._state = ModuleState.STARTING
                self._on_start()
                self._state = ModuleState.RUNNING
                self._log("info", "Module started")
                return True
            except Exception as e:
                self._state = ModuleState.ERROR
                self.log_error(f"Start failed: {e}")
                return False

    def stop(self) -> bool:
        """停止模块"""
        with self._lock:
            if self._state != ModuleState.RUNNING:
                return True
            try:
                self._state = ModuleState.STOPPING
                self._on_stop()
                self._state = ModuleState.STOPPED
                self._log("info", "Module stopped")
                return True
            except Exception as e:
                self._state = ModuleState.ERROR
                self.log_error(f"Stop failed: {e}")
                return False

    def _on_init(self) -> None:
        """初始化钩子 - 子类重写"""

    def _on_start(self) -> None:
        """启动钩子 - 子类重写"""

    def _on_stop(self) -> None:
        """停止钩子 - 子类重写"""


class DependencyResolver:
    """
    依赖解析器 - 拓扑排序确保模块按依赖顺序启动
    """

    def __init__(self):
        self._modules: Dict[str, ModuleInfo] = {}

    def register(self, info: ModuleInfo) -> None:
        """注册模块"""
        self._modules[info.name] = info

    def resolve_order(self) -> List[str]:
        """
        拓扑排序 - 返回按依赖顺序排列的模块名列表

        Returns:
            模块名列表（依赖在前，依赖者在后）

        Raises:
            ValueError: 如果存在循环依赖
        """
        visited: Set[str] = set()
        stack: Set[str] = set()
        order: List[str] = []

        def _dfs(name: str) -> None:
            if name in stack:
                raise ValueError(f"Circular dependency detected involving '{name}'")
            if name in visited:
                return
            stack.add(name)
            info = self._modules.get(name)
            if info:
                for dep in info.dependencies:
                    if dep in self._modules:
                        _dfs(dep)
            stack.discard(name)
            visited.add(name)
            order.append(name)

        for name in self._modules:
            if name not in visited:
                _dfs(name)

        return order

    def check_dependencies(self, name: str) -> List[str]:
        """检查指定模块的缺失依赖"""
        info = self._modules.get(name)
        if not info:
            return []
        return [dep for dep in info.dependencies if dep not in self._modules]

    def get_module_info(self, name: str) -> Optional[ModuleInfo]:
        """获取模块信息"""
        return self._modules.get(name)

    def get_all_modules(self) -> Dict[str, ModuleInfo]:
        """获取所有已注册模块"""
        return dict(self._modules)


class ModuleRegistry:
    """
    模块注册表 - 管理模块实例和生命周期
    """

    def __init__(self):
        self._resolver = DependencyResolver()
        self._instances: Dict[str, Module] = {}
        self._lock = threading.RLock()

    @property
    def resolver(self) -> DependencyResolver:
        return self._resolver

    def register(self, name: str, module_class: Type[Module], dependencies: List[str] = None, **kwargs) -> None:
        """注册模块"""
        info = ModuleInfo(
            name=name,
            module_class=module_class,
            dependencies=dependencies or [],
            **kwargs,
        )
        self._resolver.register(info)

    def create_instance(self, name: str, config: Dict[str, Any] = None) -> Optional[Module]:
        """创建模块实例"""
        info = self._resolver.get_module_info(name)
        if not info:
            logger.warning("Module '%s' not registered", name)
            return None
        try:
            instance = info.module_class(config=config)
            info.instance = instance
            with self._lock:
                self._instances[name] = instance
            return instance
        except Exception as e:
            info.state = ModuleState.ERROR
            info.error = str(e)
            logger.error("Failed to create instance of '%s': %s", name, e)
            return None

    def get_instance(self, name: str) -> Optional[Module]:
        """获取模块实例"""
        return self._instances.get(name)

    def start_all(self) -> StartupResult:
        """按依赖顺序启动所有模块"""
        start_time = time.time()
        result = StartupResult(success=True)

        try:
            order = self._resolver.resolve_order()
        except ValueError as e:
            result.success = False
            result.errors["resolver"] = str(e)
            return result

        for name in order:
            info = self._resolver.get_module_info(name)
            if not info:
                continue

            # 创建实例
            instance = self._instances.get(name)
            if not instance:
                instance = self.create_instance(name)
            if not instance:
                result.modules_failed.append(name)
                result.errors[name] = f"Failed to create instance"
                continue

            # 初始化
            if not instance.initialize():
                result.modules_failed.append(name)
                result.errors[name] = f"Initialization failed"
                continue

            # 启动
            if not instance.start():
                result.modules_failed.append(name)
                result.errors[name] = f"Start failed"
                continue

            result.modules_started.append(name)
            info.started_at = datetime.now(timezone.utc)

        if result.modules_failed:
            result.success = False

        result.duration = time.time() - start_time
        return result

    def stop_all(self) -> None:
        """按反向顺序停止所有模块"""
        try:
            order = self._resolver.resolve_order()
        except ValueError:
            order = list(self._instances.keys())

        for name in reversed(order):
            instance = self._instances.get(name)
            if instance:
                try:
                    instance.stop()
                except Exception as e:
                    logger.error("Error stopping module '%s': %s", name, e)
