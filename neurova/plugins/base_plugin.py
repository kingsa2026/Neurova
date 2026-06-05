from __future__ import annotations

"""
插件基类 - Base Plugin Class

提供插件开发的基础接口。所有插件应继承此类或使用 BaseModule 接口。
"""

from abc import ABC, abstractmethod
import logging
import typing

from neurova.core.logger import LogLevel
from neurova.plugins.plugin_manifest import (
    PluginManifest,
    PluginType,
    PluginPermission,
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
    def from_dict(cls, data: typing.Dict[str, typing.Any]) -> 'APIEndpoint':
        """从字典创建"""
        return cls(
            method=data.get("method", "GET"),
            path=data.get("path", ""),
            handler_name=data.get("handler_name", ""),
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
        
        self._logger.info(f"初始化插件: {self.name} v{self.version}")
        await self.on_initialize()
        self._initialized = True
    
    async def start(self) -> None:
        """启动插件"""
        if not self._initialized:
            await self.initialize()
        
        if self._running:
            return
        
        self._logger.info(f"启动插件: {self.name}")
        await self.on_start()
        self._running = True
    
    async def stop(self) -> None:
        """停止插件"""
        if not self._running:
            return
        
        self._logger.info(f"停止插件: {self.name}")
        await self.on_stop()
        self._running = False
    
    async def destroy(self) -> None:
        """销毁插件"""
        if self._running:
            await self.stop()
        
        self._logger.info(f"销毁插件: {self.name}")
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
        """订阅事件
        
        Args:
            event_name: 事件名称
            handler: 事件处理函数
        """
        if self._event_bus:
            self._event_bus.subscribe(event_name, handler)
        else:
            self._logger.warning(f"事件总线未设置，无法订阅事件: {event_name}")
    
    def unsubscribe(self, event_name: str, handler: typing.Callable) -> None:
        """取消订阅事件
        
        Args:
            event_name: 事件名称
            handler: 事件处理函数
        """
        if self._event_bus:
            self._event_bus.unsubscribe(event_name, handler)
    
    def publish_event(self, event_name: str, data: typing.Any = None) -> None:
        """发布事件
        
        Args:
            event_name: 事件名称
            data: 事件数据
        """
        if self._event_bus:
            self._event_bus.publish(event_name, data)
        else:
            self._logger.warning(f"事件总线未设置，无法发布事件: {event_name}")
    
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
        self._logger.debug(f"注册 API 端点: {endpoint}")
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(plugin_id='{self.plugin_id}', version='{self.version}')"