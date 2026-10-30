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


class StateValuesStore:
    """「一个对象自己的键值状态袋」——全仓**唯一**实装（§6-409 批 O-3 收口）。

    为什么收成一份、收成哪一份：同一功能原先有三处——这里（存 `_state_values`，**在役**：
    `IdleTimeTracker` 写 6 个键、`tests/unit/memory/test_sleep_loop_wiring.py:111` 读回）、
    `memory_layer/sleep.py` 的同名两行（存 `self._state`，该 dict 全仓只被那三行用到）、
    以及 `plugins/base_plugin.py` 那份**坏的**转发（调 `StateManager.get_state(plugin_id,…)`，
    而 `core/state_manager.py` 的真 API 是 `get(key,default)`/`set(key,value)`，那两个方法从未存在；
    `_state_manager` 也从不被注入）。按教义第 7 条比完取长补短后只剩一处实现被三族共用。

    名字为什么不叫 `get_state`/`set_state`：那一对在本仓属于**状态机**——
    `BaseModule.get_state()` 返回 `ModuleState`、`set_state(ModuleState)` 还会发
    `module.state_changed` 事件。键值袋与状态机共用一个名字，正是 `BasePlugin` 那份错位接缝
    能被写下却没被看见的土壤。

    字段由宿主类的 `__init__` 建（`self._state_values = {}`）——`BaseModule` 一直这么做，
    两个混入方各把自己那行留着（`SleepConsolidation` 原来那份叫 `self._state`，全仓只被
    那三行用到，随本批一起改名收口）。不做惰性创建：那等于把"记得初始化"换成
    "记得每次读都兜一层"，仍然是一种要靠自觉的口径。
    """

    def set_state_value(self, key: str, value: Any) -> None:
        """写入本对象的一个状态值（写了就必须读得回来——见判据的闭环要求）。"""
        self._state_values[key] = value

    def get_state_value(self, key: str, default: Any = None) -> Any:
        """读本对象的一个状态值；缺失返回 `default`，不抛。"""
        return self._state_values.get(key, default)


class BaseModule(StateValuesStore, ABC):
    """基础模块基类

    所有模块的抽象基类，定义了标准的生命周期方法。
    键值状态袋（`set_state_value`/`get_state_value`）由 `StateValuesStore` 提供，不在这里另写一份。
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

        # 允许通过参数覆盖类属性
        if module_id:
            self.MODULE_ID = module_id
        if name:
            self.MODULE_NAME = name
        if version:
            self.MODULE_VERSION = version

        self._logger = logging.getLogger(f"{self.MODULE_ID}")

        # 状态值存储（读写都在 `StateValuesStore` 那一份实现里）
        self._state_values: Dict[str, Any] = {}

        # 本实例在总线上留下的订阅（`(总线, 订阅)` 对）：`stop()` 据此逐条退订。
        # 存对象而不是只存事件名——同一事件上可能挂多次，按名退会漏或退错。
        self._eventSubscriptions: list = []

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
        """广播落点：委托 `core/event_bus.resolveEventBus`（唯一形状，见那里的注释）。

        原形态是 `event_bus=None` + `if self._event_bus:`，而全仓**没有任何一处**传非
        None（`idle_tracker.py:91`、`provider_manager.py:509` 都只是形参转发），于是
        `initialize/start/stop` 的每一次状态变更与 `idle_tracker.py` 的 `phase.changed`
        都只写在日志里，总线上一片空白——而 `api/endpoints/logs.py` 读的恰是这条总线。
        """
        from neurova.core.event_bus import resolveEventBus

        return resolveEventBus(self._event_bus)

    def subscribe_event(self, event_name: str, handler) -> None:
        """订阅事件——基类唯一的订阅入口。

        此前 `BaseModule` 只有 `emit_event` 没有订阅面，于是
        `context/injector.py:36-69` 的降级替身给自己配了一套私有 `_event_handlers`
        （第三份总线，且 handler 异常被 `except Exception: pass` 吞掉）。订阅能力
        收在基类这一份，子类不再自带平行实现。

        **订阅必须与 `stop()` 成对**：总线上存的是 handler 本体，bound method 持有
        `self` ⇒ 只要不退订，模块就被总线钉着、整张对象图（含原生内存）永远不回收。
        故本口把每条订阅落在 `self._eventSubscriptions` 上，由 `unsubscribeAllEvents()`
        逐条退订；子类不必、也不该各自记得退订。
        """
        subscription = self._resolveEventBus().subscribe(
            event_name, handler, module_name=self.MODULE_ID
        )
        self._eventSubscriptions.append((self._resolveEventBus(), subscription))

    def unsubscribeAllEvents(self) -> int:
        """退掉本模块在总线上留下的**全部**订阅，返回条数。

        为什么按 `Subscription` 对象逐条退、而不是 `unsubscribe_module(MODULE_ID)`：
        `MODULE_ID` 是**类级**常量（`context.unified_injector` 这类），同一进程里同时
        活着的两个同类型实例共用一个 ID——按模块名整片清理会把另一个活着的实例的订阅
        一起退掉。逐条退订只碰本实例自己持有的那几条。

        幂等：重复调用只会把清单清空一次，第二次返回 0。
        """
        released = 0
        pending, self._eventSubscriptions = self._eventSubscriptions, []
        for bus, subscription in pending:
            try:
                if bus.unsubscribe(subscription.event_name, subscription.handler):
                    released += 1
            except Exception as e:  # noqa: BLE001 - 退订失败不阻断关停链
                self._logger.warning(
                    "Module %s: 退订 %s 失败: %s", self.MODULE_ID, subscription.event_name, e
                )
        return released

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
            try:
                self.on_stop()
            finally:
                # 退订放进 finally：`on_stop` 抛错时模块同样已经不再运行，订阅若留在总线上
                # 就是"停了的模块还在收事件"，且它的整张对象图被钉住（受保护子集每档建一次
                # app 的内存单向上涨）。先退订再落状态——落状态是最便宜的收尾。
                self.unsubscribeAllEvents()
            self.set_state(ModuleState.STOPPED)
        except Exception as e:
            # on_stop 抛错或落 STOPPED 失败都必须落 ERROR——4d0e0df1 把退订收进
            # finally 时，异常穿出了第一段，落 ERROR 的分支变为不可达，态停在
            # STOPPING（回归由 test_stop_error 钉住）。
            self.set_state(ModuleState.ERROR)
            raise


__all__ = [
    "ModuleState",
    "BaseModule",
]
