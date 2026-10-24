from __future__ import annotations

"""
插件基类 - Base Plugin Class

提供插件开发的基础接口。所有插件应继承此类或使用 BaseModule 接口。
"""

import logging
import typing
from abc import ABC, abstractmethod

from neurova.core.base_module import StateValuesStore
from neurova.core.logger import LogLevel
from neurova.plugins import plugin_permissions
from neurova.plugins.plugin_manifest import (
    PluginFrameworkSurface,
    PluginManifest,
    PluginType,
    SemVersion,
)


class APIEndpoint:
    """API 端点描述符"""

    def __init__(
        self,
        method: str,
        path: str,
        handler_name: str,
        description: str = "",
        tags: typing.List[str] = None,
    ):
        """初始化 API 端点

        Args:
            method: HTTP 方法 (GET, POST, PUT, DELETE 等)
            path: API 路径
            handler_name: 处理函数名称
            description: 端点描述
            tags: 标签列表
        """
        self.method = method
        self.path = path
        self.handler_name = handler_name
        self.description = description
        self.tags = tags or []

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "method": self.method,
            "path": self.path,
            "handler_name": self.handler_name,
            "description": self.description,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> "APIEndpoint":
        """从字典创建（清单里那份端点声明的唯一入口形状）。

        handler 键同时接受 `handler_name` 与 `handler`：前者是本仓代码一直用的名字，
        后者是 `docs/01-architecture/06-plugin-cli-system.md` 示例里写的。两种拼写在
        **这一处**归一（不是两处各认各的，教义第 6 条）；归一之后取不到即
        `handler_name=""`，由挂载侧按 `handler_missing` 响亮拒绝，不静默跳过。
        """
        return cls(
            method=data.get("method", "GET"),
            path=data.get("path", ""),
            handler_name=data.get("handler_name") or data.get("handler", ""),
            description=data.get("description", ""),
            tags=data.get("tags", []),
        )

    def __repr__(self) -> str:
        return f"APIEndpoint({self.method} {self.path})"


class BasePlugin(StateValuesStore, ABC):
    """
    所有后端插件的基础抽象类

    与 `BaseModule` 同族但**不共享构造链**（一个是进程内模块、一个是第三方装载物）；
    共用的是同一份键值状态袋实装 `StateValuesStore`（`set_state_value`/`get_state_value`）。
    扩展了 BaseModule，增加了:
    - API 端点注册能力
    - 前后端资源声明
    - 插件元数据扩展
    """

    # 子类必须声明的元数据
    plugin_type: PluginType = PluginType.FUNCTIONAL
    api_endpoints: typing.List[APIEndpoint] = []
    frontend_resources: typing.List[str] = []
    # 框架中介面声明（事件总线两档）。能力面（文件/网络/命令/模型/存储…）不在插件侧另立词汇：
    # 单点是 skills 那套 `permissions`（键 ∈ `KNOWN_CAPABILITY_KEYS`，拦点在 `tool_executor`）。
    framework_surfaces: typing.List[PluginFrameworkSurface] = []

    def __init__(self, manifest: PluginManifest):
        """初始化插件

        Args:
            manifest: 插件清单
        """
        self._manifest = manifest
        self._initialized = False
        self._running = False
        self._logger = logging.getLogger(f"plugin.{manifest.plugin_id}")
        self._event_bus = None
        # 键值状态袋的字段名与 `BaseModule` 同一口径（唯一实装在
        # `core/base_module.StateValuesStore`）；这里只建容器，不再另写一份读写。
        self._state_values: typing.Dict[str, typing.Any] = {}

    @property
    def plugin_id(self) -> str:
        """插件 ID"""
        return self._manifest.plugin_id

    @property
    def name(self) -> str:
        """插件名称"""
        return self._manifest.name

    @property
    def version(self) -> SemVersion:
        """插件版本"""
        return self._manifest.version

    @property
    def description(self) -> str:
        """插件描述"""
        return self._manifest.description

    @property
    def manifest(self) -> PluginManifest:
        """插件清单"""
        return self._manifest

    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized

    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running

    @property
    def event_bus(self):
        """显式注入的总线（覆盖通道）；没注入时由 `_resolveEventBus()` 现取全局单例。"""
        return self._event_bus

    @event_bus.setter
    def event_bus(self, value):
        """覆盖通道：特殊装配与测试用。生产侧**不要求**有人来设它——不设也走得通。"""
        self._event_bus = value

    def _resolveEventBus(self):
        """总线落点的唯一形状：注入优先，未注入**调用时现取**全局单例。

        与 `core/base_module.py:_resolveEventBus` 是同一个委托（单源在
        `core/event_bus.resolveEventBus`），不各写一份。改前这里是
        `if self._event_bus:`，而生产侧从没有人给它赋值（`plugin_manager.py` 里连
        `event_bus` 这个词都不出现，全仓赋值点只有三处测试）⇒ **已通过权限确认的插件**
        调 `publish_event()`，效果只是打一条 warning，然后什么都没发生（§6-412 批 P-4）。
        """
        from neurova.core.event_bus import resolveEventBus

        return resolveEventBus(self._event_bus)

    async def initialize(self) -> None:
        """初始化插件"""
        if self._initialized:
            return

        self._logger.info("初始化插件: %s v%s", self.name, self.version)
        await self.on_initialize()
        self._initialized = True

    async def start(self) -> None:
        """启动插件"""
        if not self._initialized:
            await self.initialize()

        if self._running:
            return

        self._logger.info("启动插件: %s", self.name)
        await self.on_start()
        self._running = True

    async def stop(self) -> None:
        """停止插件"""
        if not self._running:
            return

        self._logger.info("停止插件: %s", self.name)
        await self.on_stop()
        self._running = False

    async def destroy(self) -> None:
        """销毁插件"""
        if self._running:
            await self.stop()

        self._logger.info("销毁插件: %s", self.name)
        await self.on_destroy()
        self._initialized = False

    @abstractmethod
    async def on_initialize(self) -> None:
        """初始化回调: 注册事件监听器、加载配置"""
        ...

    @abstractmethod
    async def on_start(self) -> None:
        """启动回调: 注册 API 端点、启动后台任务"""
        ...

    @abstractmethod
    async def on_stop(self) -> None:
        """停止回调: 注销 API 端点、清理后台任务"""
        ...

    @abstractmethod
    async def on_destroy(self) -> None:
        """销毁回调: 释放资源"""
        ...

    def subscribe(self, event_name: str, handler: typing.Callable) -> None:
        """订阅事件（须 `read:events` 已被逐项确认）。

        判定顺序是刻意的：**先过权限门，再看总线在不在**。反过来的话，
        「忘了给插件设 event_bus」会把一次越权调用降成一条 warning，
        调用方拿到 None 继续跑（§6-126 那一族：把不同故障折成同一个结论）。
        """
        self._requirePermission(PluginFrameworkSurface.READ_EVENTS)
        self._resolveEventBus().subscribe(event_name, handler)

    def unsubscribe(self, event_name: str, handler: typing.Callable) -> None:
        """取消订阅事件（同 `read:events`——退订也是对他方事件面的操作）。"""
        self._requirePermission(PluginFrameworkSurface.READ_EVENTS)
        self._resolveEventBus().unsubscribe(event_name, handler)

    def publish_event(self, event_name: str, data: typing.Any = None) -> None:
        """发布事件（须 `emit:events` 已被逐项确认）。"""
        self._requirePermission(PluginFrameworkSurface.EMIT_EVENTS)
        self._resolveEventBus().publish(event_name, data)

    def _requirePermission(self, permission: PluginFrameworkSurface) -> None:
        """框架中介点的判定单点：未确认即抛 `PluginError("permission_not_granted")`。

        读的是 `plugin_permissions` 模块属性（不是 import 进来的名字副本），
        所以测试可以替换 `getPermissionStore` 而不必动文件落点。
        """
        if plugin_permissions.permissionIsGranted(self.plugin_id, permission):
            return
        from neurova.plugins.plugin_errors import PluginError

        spec = plugin_permissions.FRAMEWORK_SURFACE_MODEL[permission]
        raise PluginError(
            "permission_not_granted",
            "插件 %s 未被授予框架中介面 %s——它管的是：%s（强制点 %s）"
            % (self.plugin_id, permission.value, spec.unlocks, spec.enforcedAt))

    def log(self, level: LogLevel, message: str, **kwargs) -> None:
        """记录日志

        Args:
            level: 日志级别
            message: 日志消息
        """
        self._logger.log(level.value, message, **kwargs)

    def log_info(self, message: str, **kwargs) -> None:
        """记录信息日志"""
        self.log(LogLevel.INFO, message, **kwargs)

    def log_warning(self, message: str, **kwargs) -> None:
        """记录警告日志"""
        self.log(LogLevel.WARNING, message, **kwargs)

    def log_error(self, message: str, **kwargs) -> None:
        """记录错误日志"""
        self.log(LogLevel.ERROR, message, **kwargs)

    def _register_api_endpoint(self, endpoint: APIEndpoint) -> None:
        """注册 API 端点 (由子类实现)

        Args:
            endpoint: API 端点描述符
        """
        # 默认实现，子类可以覆盖
        self._logger.debug("注册 API 端点: %s", endpoint)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(plugin_id='{self.plugin_id}', version='{self.version}')"
