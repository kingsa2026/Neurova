"""
插件API注册器

插件使用此类注册自己的API端点
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = get_logger(__name__)


@dataclass
class PluginEndpoint:
    """插件注册的API端点"""

    plugin_id: str
    path: str
    method: str  # GET, POST, PUT, DELETE, PATCH
    handler: Callable
    # 清单里声明的 handler 方法名。解析不出实体时（`handler=None`）拒绝消息必须点得出
    # **作者写的那个名字**，只给 `None` 的话插件作者无从知道自己的声明哪里拼错了。
    handler_name: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
    auth_required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "path": self.path,
            "method": self.method.upper(),
            "handler_name": self.handler_name,
            "description": self.description,
            "tags": self.tags,
            "auth_required": self.auth_required,
        }


class PluginAPIRegistry:
    """
    插件API注册器

    管理插件注册的自定义API端点，支持：
    - 注册/注销端点
    - 按插件查询
    - 端点冲突检测
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._endpoints: Dict[str, PluginEndpoint] = {}  # key: "{method}:{plugin_id}:{path}"
        self._plugin_endpoints: Dict[str, Set[str]] = {}  # plugin_id -> set of keys

    @staticmethod
    def _key(method: str, plugin_id: str, path: str) -> str:
        """键必须带 plugin_id。原实现按 `METHOD:path` 收，而 `path` 现在是**各自命名空间里的
        相对路径**（`status`/`stats` 这种名字每个插件都会用）——不带归属时，第二个声明同名相对路径
        的插件会被第一个静默拒收（`register_route` 只 return False + 一条 warning），
        「我声明的端点没挂上」这件事在注册器这层就丢了成因。真正的跨边界遮蔽只发生在
        **全路径**上，那一层由 `plugin_route_mount` 按活 app 的路由表判（`path_conflict`）。
        """
        return "%s:%s:%s" % (method.upper(), plugin_id, path)

    def register_route(
        self,
        plugin_id: str,
        path: str,
        method: str,
        handler: Callable,
        handler_name: str = "",
        description: str = "",
        tags: Optional[List[str]] = None,
        auth_required: bool = True,
    ) -> bool:
        """
        注册一个API端点

        Args:
            plugin_id: 插件ID
            path: 插件自身命名空间内的相对路径 (e.g., "status" → /api/v1/plugin-api/{id}/status)
            method: HTTP方法
            handler: 处理函数 (FastAPI route handler)
            description: 端点描述
            tags: API标签
            auth_required: 是否需要认证（挂载侧**不采信 false**，见 `plugin_route_mount`）

        Returns:
            True 注册成功；False 同一插件内该 method:path 已被占（重复声明）
        """
        method_upper = method.upper()
        key = self._key(method, plugin_id, path)

        with self._lock:
            # 冲突只可能是**同一插件重复声明**（跨插件由各自命名空间隔离，与核心路由的冲突
            # 在挂载侧按活 app 的路由表判）；重复声明要响亮，不能后写悄悄覆盖前写
            if key in self._endpoints:
                logger.warning(
                    "插件 '%s' 重复声明端点 %s %s——后者被拒，不会覆盖前者",
                    plugin_id, method_upper, path)
                return False

            endpoint = PluginEndpoint(
                plugin_id=plugin_id,
                path=path,
                method=method_upper,
                handler=handler,
                handler_name=handler_name or getattr(handler, "__name__", "") or "",
                description=description,
                tags=tags or [],
                auth_required=auth_required,
            )

            self._endpoints[key] = endpoint

            if plugin_id not in self._plugin_endpoints:
                self._plugin_endpoints[plugin_id] = set()
            self._plugin_endpoints[plugin_id].add(key)

            logger.debug("Registered route: %s %s for plugin '%s'", method_upper, path, plugin_id)
            return True

    def unregister_plugin(self, plugin_id: str) -> int:
        """
        注销插件的所有端点

        Returns:
            注销的端点数量
        """
        with self._lock:
            keys = self._plugin_endpoints.pop(plugin_id, set())
            count = 0
            for key in keys:
                if key in self._endpoints:
                    del self._endpoints[key]
                    count += 1

            if count > 0:
                logger.debug("Unregistered %s routes for plugin '%s'", count, plugin_id)
            return count

    def unregister_all(self) -> int:
        """注销所有端点"""
        with self._lock:
            count = len(self._endpoints)
            self._endpoints.clear()
            self._plugin_endpoints.clear()
            return count

    def get_registered_endpoints(
        self,
        plugin_id: Optional[str] = None,
        method: Optional[str] = None,
    ) -> List[PluginEndpoint]:
        """获取注册的端点列表"""
        with self._lock:
            endpoints = list(self._endpoints.values())

        if plugin_id:
            endpoints = [e for e in endpoints if e.plugin_id == plugin_id]
        if method:
            method_upper = method.upper()
            endpoints = [e for e in endpoints if e.method == method_upper]

        return sorted(endpoints, key=lambda e: (e.path, e.method))

    def get_plugin_endpoints(self, plugin_id: str) -> List[PluginEndpoint]:
        """获取指定插件的所有端点"""
        return self.get_registered_endpoints(plugin_id=plugin_id)

    def has_endpoint(self, method: str, path: str, plugin_id: Optional[str] = None) -> bool:
        """检查端点是否已注册（不给 plugin_id 时问的是「有没有任何插件占了这条相对路径」。）"""
        with self._lock:
            if plugin_id is not None:
                return self._key(method, plugin_id, path) in self._endpoints
            return any(key.startswith("%s:" % method.upper()) and key.endswith(":%s" % path)
                       for key in self._endpoints)

    def get_endpoint(self, method: str, path: str,
                     plugin_id: Optional[str] = None) -> Optional[PluginEndpoint]:
        """获取端点详情（同 `has_endpoint` 的两种问法）。"""
        with self._lock:
            if plugin_id is not None:
                return self._endpoints.get(self._key(method, plugin_id, path))
            for key, endpoint in self._endpoints.items():
                if endpoint.method == method.upper() and endpoint.path == path:
                    return endpoint
        return None

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            plugin_counts = {pid: len(keys) for pid, keys in self._plugin_endpoints.items()}
            method_counts: Dict[str, int] = {}
            for endpoint in self._endpoints.values():
                method_counts[endpoint.method] = method_counts.get(endpoint.method, 0) + 1

            return {
                "total_endpoints": len(self._endpoints),
                "total_plugins": len(self._plugin_endpoints),
                "endpoints_per_plugin": plugin_counts,
                "endpoints_per_method": method_counts,
            }


# 全局单例
_plugin_api_registry: Optional[PluginAPIRegistry] = None
_registry_lock = threading.Lock()


def get_plugin_api_registry() -> PluginAPIRegistry:
    """获取全局插件API注册器单例"""
    global _plugin_api_registry
    if _plugin_api_registry is None:
        with _registry_lock:
            if _plugin_api_registry is None:
                _plugin_api_registry = PluginAPIRegistry()
    return _plugin_api_registry


def reset_plugin_api_registry() -> None:
    """重置全局注册器（用于测试）"""
    global _plugin_api_registry
    with _registry_lock:
        _plugin_api_registry = None
