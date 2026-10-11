from __future__ import annotations

"""
插件基类 - Base Plugin Class

提供插件开发的基础接口。所有插件应继承此类或使用 BaseModule 接口。
"""

import logging
import typing
from abc import ABC, abstractmethod

from neurova.core.logger import LogLevel
from neurova.plugins import plugin_permissions
from neurova.plugins.plugin_manifest import (
    PluginManifest,
    PluginPermission,
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


class BasePlugin(ABC):
    """
    所有后端插件的基础抽象类

    扩展了 BaseModule，增加了:
    - API 端点注册能力
    - 前后端资源声明
    - 插件元数据扩展
    """

    # 子类必须声明的元数据
    plugin_type: PluginType = PluginType.FUNCTIONAL
    api_endpoints: typing.List[APIEndpoint] = []
    frontend_resources: typing.List[str] = []
    required_permissions: typing.List[PluginPermission] = []

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
        self._state_manager = None

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
        """事件总线"""
        return self._event_bus

    @event_bus.setter
    def event_bus(self, value):
        """设置事件总线"""
        self._event_bus = value

    @property
    def state_manager(self):
        """状态管理器"""
        return self._state_manager

    @state_manager.setter
    def state_manager(self, value):
        """设置状态管理器"""
        self._state_manager = value

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
        self._requirePermission(PluginPermission.READ_EVENTS)
        if self._event_bus:
            self._event_bus.subscribe(event_name, handler)
        else:
            self._logger.warning("事件总线未设置，无法订阅事件: %s", event_name)

    def unsubscribe(self, event_name: str, handler: typing.Callable) -> None:
        """取消订阅事件（同 `read:events`——退订也是对他方事件面的操作）。"""
        self._requirePermission(PluginPermission.READ_EVENTS)
        if self._event_bus:
            self._event_bus.unsubscribe(event_name, handler)

    def publish_event(self, event_name: str, data: typing.Any = None) -> None:
        """发布事件（须 `emit:events` 已被逐项确认）。"""
        self._requirePermission(PluginPermission.EMIT_EVENTS)
        if self._event_bus:
            self._event_bus.publish(event_name, data)
        else:
            self._logger.warning("事件总线未设置，无法发布事件: %s", event_name)

    def _requirePermission(self, permission: PluginPermission) -> None:
        """框架中介点的判定单点：未确认即抛 `PluginError("permission_not_granted")`。

        读的是 `plugin_permissions` 模块属性（不是 import 进来的名字副本），
        所以测试可以替换 `getPermissionStore` 而不必动文件落点。
        """
        if plugin_permissions.permissionIsGranted(self.plugin_id, permission):
            return
        from neurova.plugins.plugin_errors import PluginError

        raise PluginError(
            "permission_not_granted",
            "插件 %s 未被授予 %s（该权限档位：%s）"
            % (self.plugin_id, permission.value,
               plugin_permissions.PERMISSION_MODEL[permission].tier.value))

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

    def get_state(self, key: str, default: typing.Any = None) -> typing.Any:
        """获取状态

        Args:
            key: 状态键
            default: 默认值

        Returns:
            状态值
        """
        if self._state_manager:
            return self._state_manager.get_state(self.plugin_id, key, default)
        return default

    def set_state(self, key: str, value: typing.Any) -> None:
        """设置状态

        Args:
            key: 状态键
            value: 状态值
        """
        if self._state_manager:
            self._state_manager.set_state(self.plugin_id, key, value)

    def _register_api_endpoint(self, endpoint: APIEndpoint) -> None:
        """注册 API 端点 (由子类实现)

        Args:
            endpoint: API 端点描述符
        """
        # 默认实现，子类可以覆盖
        self._logger.debug("注册 API 端点: %s", endpoint)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(plugin_id='{self.plugin_id}', version='{self.version}')"
