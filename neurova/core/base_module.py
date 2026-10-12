"""
基础模块

提供所有模块的基类，定义生命周期方法和状态管理。
"""

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional


class ModuleState(Enum):
    """模块状态"""

    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class BaseModule(ABC):
    """基础模块基类

    所有模块的抽象基类，定义了标准的生命周期方法。
    """

    MODULE_ID: str = "base_module"
    MODULE_NAME: str = "Base Module"
    MODULE_VERSION: str = "1.0.0"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        event_bus=None,
        module_id: str = None,
        name: str = None,
        version: str = None,
        description: str = None,
        dependencies: list = None,
        **kwargs,
    ):
        self._config = config or {}
        # 总线在调用时现取（见 `_resolveEventBus`），不在构造期冻结：绑死之后，
        # 任何"重置全局单例"的动作（测试隔离、重启装配）都会让已建模块永远
        # 对着一条没人读的总线发事件——正是本文件过去恒走 None 分支的形态。
        self._event_bus = event_bus
        self._state = ModuleState.UNINITIALIZED
        self._state_manager = None
        self._log_manager = None
        self._error_handler = None

        # 允许通过参数覆盖类属性
        if module_id:
            self.MODULE_ID = module_id
        if name:
            self.MODULE_NAME = name
        if version:
            self.MODULE_VERSION = version

        self._logger = logging.getLogger(f"{self.MODULE_ID}")

        # 状态值存储
        self._state_values: Dict[str, Any] = {}

    def set_state_value(self, key: str, value: Any) -> None:
        """设置状态值"""
        self._state_values[key] = value

    def get_state_value(self, key: str, default: Any = None) -> Any:
        """获取状态值"""
        return self._state_values.get(key, default)

    def set_state(self, new_state: ModuleState) -> None:
        """设置模块状态"""
        old_state = self._state
        self._state = new_state
        self._logger.debug("State changed: %s -> %s", old_state.value, new_state.value)

        # 发送状态变更事件
        self._resolveEventBus().publish(
            "module.state_changed",
            {
                "module_id": self.MODULE_ID,
                "old_state": old_state.value,
                "new_state": new_state.value,
            },
            source=self.MODULE_ID,
        )

    def get_state(self) -> ModuleState:
        """获取模块状态"""
        return self._state

    def log_info(self, message: str) -> None:
        """记录信息日志"""
        self._logger.info(message)

    def log_debug(self, message: str) -> None:
        """记录调试日志"""
        self._logger.debug(message)

    def log_warning(self, message: str) -> None:
        """记录警告日志"""
        self._logger.warning(message)

    def log_error(self, message: str) -> None:
        """记录错误日志"""
        self._logger.error(message)

    def _resolveEventBus(self):
        """广播落点：注入优先，未注入回落到 `core/event_bus` 的唯一全局入口。

        原形态是 `event_bus=None` + `if self._event_bus:`，而全仓**没有任何一处**传非
        None（`idle_tracker.py:91`、`provider_manager.py:509` 都只是形参转发），于是
        `initialize/start/stop`(:144-177) 的每一次状态变更与 `idle_tracker.py:602` 的
        `phase.changed` 都只写在日志里，总线上一片空白——而
        `api/endpoints/logs.py:72` 读的恰是这条总线，写了没人读、读了恒为空，两头断点。
        每次调用现取（不冻结在构造期）与 `_settings_path()` 同一口径：绑死会让
        "重置全局单例"之后的模块对着一条已退役的总线发事件。
        """
        if self._event_bus is not None:
            return self._event_bus
        from neurova.core.event_bus import get_event_bus

        return get_event_bus()

    def subscribe_event(self, event_name: str, handler) -> None:
        """订阅事件——基类唯一的订阅入口。

        此前 `BaseModule` 只有 `emit_event` 没有订阅面，于是
        `context/injector.py:36-69` 的降级替身给自己配了一套私有 `_event_handlers`
        （第三份总线，且 handler 异常被 `except Exception: pass` 吞掉）。订阅能力
        收在基类这一份，子类不再自带平行实现。
        """
        self._resolveEventBus().subscribe(event_name, handler, module_name=self.MODULE_ID)

    def emit_event(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        """发送事件（载荷必带 `module_id`——订阅者据此归因，缺它事件就是无主的）"""
        self._resolveEventBus().publish(
            event_type,
            {
                "module_id": self.MODULE_ID,
                **(data or {}),
            },
            source=self.MODULE_ID,
        )

    @abstractmethod
    def on_initialize(self) -> None:
        """初始化模块"""

    @abstractmethod
    def on_start(self) -> None:
        """启动模块"""

    @abstractmethod
    def on_stop(self) -> None:
        """停止模块"""

    def initialize(self) -> None:
        """初始化模块（带状态管理）"""
        if self._state != ModuleState.UNINITIALIZED:
            self._logger.warning("Module %s already initialized", self.MODULE_ID)
            return

        self.set_state(ModuleState.INITIALIZING)
        try:
            self.on_initialize()
            self.set_state(ModuleState.INITIALIZED)
        except Exception as e:
            self.set_state(ModuleState.ERROR)
            raise

    def start(self) -> None:
        """启动模块（带状态管理）"""
        if self._state != ModuleState.INITIALIZED:
            self._logger.warning("Module %s not initialized", self.MODULE_ID)
            return

        self.set_state(ModuleState.STARTING)
        try:
            self.on_start()
            self.set_state(ModuleState.RUNNING)
        except Exception as e:
            self.set_state(ModuleState.ERROR)
            raise

    def stop(self) -> None:
        """停止模块（带状态管理）"""
        if self._state != ModuleState.RUNNING:
            self._logger.warning("Module %s not running", self.MODULE_ID)
            return

        self.set_state(ModuleState.STOPPING)
        try:
            self.on_stop()
            self.set_state(ModuleState.STOPPED)
        except Exception as e:
            self.set_state(ModuleState.ERROR)
            raise


__all__ = [
    "ModuleState",
    "BaseModule",
]
