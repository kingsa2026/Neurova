"""
插件API注册器

插件使用此类注册自己的API端点
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class PluginEndpoint:
    """插件注册的API端点"""
    plugin_id: str
    path: str
    method: str  # GET, POST, PUT, DELETE, PATCH
    handler: Callable
    description: str = ""
    tags: List[str] = field(default_factory=list)
    auth_required: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "path": self.path,
            "method": self.method.upper(),
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
        self._endpoints: Dict[str, PluginEndpoint] = {}  # key: "{method}:{path}"
        self._plugin_endpoints: Dict[str, Set[str]] = {}  # plugin_id -> set of keys
    
    def register_route(
        self,
        plugin_id: str,
        path: str,
        method: str,
        handler: Callable,
        description: str = "",
        tags: Optional[List[str]] = None,
        auth_required: bool = True,
    ) -> bool:
        """
        注册一个API端点
        
        Args:
            plugin_id: 插件ID
            path: API路径 (e.g., "/api/plugins/my-plugin/data")
            method: HTTP方法
            handler: 处理函数 (FastAPI route handler)
            description: 端点描述
            tags: API标签
            auth_required: 是否需要认证
            
        Returns:
            True if registered successfully, False if path conflict
        """
        method_upper = method.upper()
        key = f"{method_upper}:{path}"
        
        with self._lock:
            # 检查冲突
            if key in self._endpoints:
                existing = self._endpoints[key]
                if existing.plugin_id != plugin_id:
                    logger.warning(
                        f"Path conflict: {method_upper} {path} already registered by plugin '{existing.plugin_id}'"
                    )
                    return False
            
            endpoint = PluginEndpoint(
                plugin_id=plugin_id,
                path=path,
                method=method_upper,
                handler=handler,
                description=description,
                tags=tags or [],
                auth_required=auth_required,
            )
            
            self._endpoints[key] = endpoint
            
            if plugin_id not in self._plugin_endpoints:
                self._plugin_endpoints[plugin_id] = set()
            self._plugin_endpoints[plugin_id].add(key)
            
            logger.debug(f"Registered route: {method_upper} {path} for plugin '{plugin_id}'")
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
                logger.debug(f"Unregistered {count} routes for plugin '{plugin_id}'")
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
    
    def has_endpoint(self, method: str, path: str) -> bool:
        """检查端点是否已注册"""
        key = f"{method.upper()}:{path}"
        with self._lock:
            return key in self._endpoints
    
    def get_endpoint(self, method: str, path: str) -> Optional[PluginEndpoint]:
        """获取端点详情"""
        key = f"{method.upper()}:{path}"
        with self._lock:
            return self._endpoints.get(key)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            plugin_counts = {
                pid: len(keys) for pid, keys in self._plugin_endpoints.items()
            }
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
