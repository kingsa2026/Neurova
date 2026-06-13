"""
动态API路由器

支持插件在运行时动态注册和注销API端点
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class APIEndpoint:
    """API端点数据类"""

    path: str
    method: str  # GET, POST, PUT, DELETE, etc.
    handler: Callable
    plugin_name: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    response_model: Optional[type] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "path": self.path,
            "method": self.method,
            "plugin_name": self.plugin_name,
            "description": self.description,
            "tags": self.tags,
            "parameters": self.parameters,
            "response_model": self.response_model.__name__ if self.response_model else None,
        }


class APIRouter:
    """
    动态API路由器

    支持插件在运行时动态注册和注销API端点。
    """

    def __init__(self, config: Dict[str, Any] = None):
        """
        初始化API路由器

        Args:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()

        # 端点注册表: {path: {method: APIEndpoint}}
        self._endpoints: Dict[str, Dict[str, APIEndpoint]] = {}

        # 插件端点映射: {plugin_name: [endpoint_key, ...]}
        self._plugin_endpoints: Dict[str, List[str]] = {}

        logger.info("APIRouter 初始化完成")

    def register_endpoint(self, endpoint: APIEndpoint) -> bool:
        """
        注册API端点

        Args:
            endpoint: API端点

        Returns:
            是否注册成功
        """
        with self._lock:
            try:
                path = endpoint.path
                method = endpoint.method.upper()

                # 检查路径是否已存在
                if path not in self._endpoints:
                    self._endpoints[path] = {}

                # 检查方法是否已存在
                if method in self._endpoints[path]:
                    logger.warning("端点已存在，将覆盖: %s %s", method, path)

                # 注册端点
                self._endpoints[path][method] = endpoint

                # 更新插件端点映射
                plugin_name = endpoint.plugin_name
                if plugin_name not in self._plugin_endpoints:
                    self._plugin_endpoints[plugin_name] = []

                endpoint_key = f"{method}:{path}"
                if endpoint_key not in self._plugin_endpoints[plugin_name]:
                    self._plugin_endpoints[plugin_name].append(endpoint_key)

                logger.info("注册API端点: %s %s (插件: %s)", method, path, plugin_name)
                return True

            except Exception as e:
                logger.error("注册API端点失败: %s", e)
                return False

    def unregister_endpoint(self, path: str, method: str) -> bool:
        """
        注销API端点

        Args:
            path: API路径
            method: HTTP方法

        Returns:
            是否注销成功
        """
        with self._lock:
            try:
                method = method.upper()

                if path not in self._endpoints:
                    logger.warning("路径不存在: %s", path)
                    return False

                if method not in self._endpoints[path]:
                    logger.warning("方法不存在: %s %s", method, path)
                    return False

                # 获取端点信息
                endpoint = self._endpoints[path][method]
                plugin_name = endpoint.plugin_name

                # 移除端点
                del self._endpoints[path][method]

                # 清理空路径
                if not self._endpoints[path]:
                    del self._endpoints[path]

                # 更新插件端点映射
                endpoint_key = f"{method}:{path}"
                if plugin_name in self._plugin_endpoints:
                    if endpoint_key in self._plugin_endpoints[plugin_name]:
                        self._plugin_endpoints[plugin_name].remove(endpoint_key)

                    # 清理空插件
                    if not self._plugin_endpoints[plugin_name]:
                        del self._plugin_endpoints[plugin_name]

                logger.info("注销API端点: %s %s", method, path)
                return True

            except Exception as e:
                logger.error("注销API端点失败: %s", e)
                return False

    def unregister_plugin_endpoints(self, plugin_name: str) -> int:
        """
        注销插件的所有端点

        Args:
            plugin_name: 插件名称

        Returns:
            注销的端点数量
        """
        with self._lock:
            if plugin_name not in self._plugin_endpoints:
                logger.warning("插件不存在: %s", plugin_name)
                return 0

            # 获取插件端点列表
            endpoint_keys = self._plugin_endpoints[plugin_name].copy()
            count = 0

            # 逐个注销
            for endpoint_key in endpoint_keys:
                method, path = endpoint_key.split(":", 1)
                if self.unregister_endpoint(path, method):
                    count += 1

            logger.info("注销插件 %s 的 %s 个端点", plugin_name, count)
            return count

    def get_endpoint(self, path: str, method: str) -> Optional[APIEndpoint]:
        """
        获取API端点

        Args:
            path: API路径
            method: HTTP方法

        Returns:
            API端点，不存在返回 None
        """
        with self._lock:
            method = method.upper()

            if path not in self._endpoints:
                return None

            return self._endpoints[path].get(method)

    def get_endpoints(self, path: str = None, method: str = None) -> List[APIEndpoint]:
        """
        获取API端点列表

        Args:
            path: API路径过滤
            method: HTTP方法过滤

        Returns:
            API端点列表
        """
        with self._lock:
            endpoints = []

            for p, methods in self._endpoints.items():
                if path and p != path:
                    continue

                for m, endpoint in methods.items():
                    if method and m != method.upper():
                        continue

                    endpoints.append(endpoint)

            return endpoints

    def get_endpoints_by_plugin(self, plugin_name: str) -> List[APIEndpoint]:
        """
        获取插件的所有端点

        Args:
            plugin_name: 插件名称

        Returns:
            API端点列表
        """
        with self._lock:
            if plugin_name not in self._plugin_endpoints:
                return []

            endpoints = []
            for endpoint_key in self._plugin_endpoints[plugin_name]:
                method, path = endpoint_key.split(":", 1)
                endpoint = self.get_endpoint(path, method)
                if endpoint:
                    endpoints.append(endpoint)

            return endpoints

    def get_openapi_spec(self, title: str = "Neurova API", version: str = "1.0.0") -> Dict[str, Any]:
        """
        生成OpenAPI规范

        Args:
            title: API标题
            version: API版本

        Returns:
            OpenAPI规范字典
        """
        with self._lock:
            paths = {}
            tags = set()

            for path, methods in self._endpoints.items():
                paths[path] = {}

                for method, endpoint in methods.items():
                    # 收集标签
                    for tag in endpoint.tags:
                        tags.add(tag)

                    # 构建路径项
                    path_item = {
                        "summary": endpoint.description,
                        "tags": endpoint.tags,
                        "operationId": f"{method.lower()}_{path.replace('/', '_')}",
                        "responses": {
                            "200": {
                                "description": "成功",
                                "content": {"application/json": {"schema": {"type": "object"}}},
                            }
                        },
                    }

                    # 添加参数
                    if endpoint.parameters:
                        path_item["parameters"] = []
                        for name, param_info in endpoint.parameters.items():
                            path_item["parameters"].append(
                                {
                                    "name": name,
                                    "in": param_info.get("in", "query"),
                                    "required": param_info.get("required", False),
                                    "schema": param_info.get("schema", {"type": "string"}),
                                }
                            )

                    # 添加请求体
                    if method in ["POST", "PUT", "PATCH"]:
                        path_item["requestBody"] = {"content": {"application/json": {"schema": {"type": "object"}}}}

                    paths[path][method.lower()] = path_item

            # 构建OpenAPI规范
            spec = {
                "openapi": "3.0.0",
                "info": {"title": title, "version": version, "description": "Neurova 动态API"},
                "paths": paths,
                "tags": [{"name": tag} for tag in sorted(tags)],
            }

            return spec

    def get_status(self) -> Dict[str, Any]:
        """
        获取路由器状态

        Returns:
            状态字典
        """
        with self._lock:
            total_endpoints = sum(len(methods) for methods in self._endpoints.values())

            return {
                "total_paths": len(self._endpoints),
                "total_endpoints": total_endpoints,
                "plugins": {name: len(keys) for name, keys in self._plugin_endpoints.items()},
                "methods": self._get_method_counts(),
            }

    def _get_method_counts(self) -> Dict[str, int]:
        """
        获取HTTP方法统计

        Returns:
            方法计数字典
        """
        counts: Dict[str, int] = {}

        for methods in self._endpoints.values():
            for method in methods:
                counts[method] = counts.get(method, 0) + 1

        return counts
