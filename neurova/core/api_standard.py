from __future__ import annotations

"""
统一 API 接口标准 - 定义模块与后端交互的契约

功能:
- 请求/响应格式定义
- 错误码规范
- 认证协议
- 版本管理
"""

import enum
import time
import typing
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, List, Optional, TypeVar

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class APIVersion(enum.Enum):
    """API版本枚举"""

    V1 = "v1"
    V2 = "v2"
    V3 = "v3"

    @classmethod
    def latest(cls) -> "APIVersion":
        """获取最新版本"""
        return cls.V3

    @classmethod
    def from_string(cls, version_str: str) -> "APIVersion":
        """从字符串创建版本"""
        try:
            return cls(version_str.lower())
        except ValueError:
            raise ValueError(f"不支持的API版本: {version_str}")


class HTTPMethod(enum.Enum):
    """HTTP方法枚举"""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


@dataclass
class APIRequest:
    """API请求数据类"""

    method: HTTPMethod
    path: str
    headers: Dict[str, str] = field(default_factory=dict)
    query_params: Dict[str, str] = field(default_factory=dict)
    body: Optional[Any] = None
    version: APIVersion = APIVersion.V3
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    user_id: Optional[str] = None
    auth_token: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "method": self.method.value,
            "path": self.path,
            "headers": self.headers,
            "query_params": self.query_params,
            "body": self.body,
            "version": self.version.value,
            "request_id": self.request_id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
        }


@dataclass
class APIResponse:
    """API响应数据类"""

    status_code: int = 200
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    request_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    headers: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {"status_code": self.status_code, "timestamp": self.timestamp, "headers": self.headers}

        if self.data is not None:
            result["data"] = self.data

        if self.error is not None:
            result["error"] = self.error

        if self.error_code is not None:
            result["error_code"] = self.error_code

        if self.request_id is not None:
            result["request_id"] = self.request_id

        return result

    @classmethod
    def success(cls, data: Any = None, request_id: str = None) -> "APIResponse":
        """创建成功响应"""
        return cls(status_code=200, data=data, request_id=request_id)

    @classmethod
    def error(cls, status_code: int, error: str, error_code: str = None, request_id: str = None) -> "APIResponse":
        """创建错误响应"""
        return cls(status_code=status_code, error=error, error_code=error_code, request_id=request_id)

    @classmethod
    def not_found(cls, resource: str = "资源", request_id: str = None) -> "APIResponse":
        """创建404响应"""
        return cls.error(status_code=404, error=f"{resource}不存在", error_code="NOT_FOUND", request_id=request_id)

    @classmethod
    def unauthorized(cls, request_id: str = None) -> "APIResponse":
        """创建401响应"""
        return cls.error(status_code=401, error="未授权访问", error_code="UNAUTHORIZED", request_id=request_id)

    @classmethod
    def forbidden(cls, request_id: str = None) -> "APIResponse":
        """创建403响应"""
        return cls.error(status_code=403, error="禁止访问", error_code="FORBIDDEN", request_id=request_id)

    @classmethod
    def bad_request(cls, error: str = "请求参数错误", request_id: str = None) -> "APIResponse":
        """创建400响应"""
        return cls.error(status_code=400, error=error, error_code="BAD_REQUEST", request_id=request_id)

    @classmethod
    def internal_error(cls, error: str = "内部服务器错误", request_id: str = None) -> "APIResponse":
        """创建500响应"""
        return cls.error(status_code=500, error=error, error_code="INTERNAL_ERROR", request_id=request_id)


T = TypeVar("T")


@dataclass
class PageRequest(Generic[T]):
    """分页请求数据类"""

    page: int = 1
    page_size: int = 20
    sort_by: Optional[str] = None
    sort_order: str = "asc"  # asc or desc
    filters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "page": self.page,
            "page_size": self.page_size,
            "sort_by": self.sort_by,
            "sort_order": self.sort_order,
            "filters": self.filters,
        }

    @property
    def offset(self) -> int:
        """计算偏移量"""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """获取限制数量"""
        return self.page_size


@dataclass
class PageResponse(Generic[T]):
    """分页响应数据类"""

    items: List[T] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0

    def __post_init__(self):
        """初始化后计算总页数"""
        if self.page_size > 0:
            self.total_pages = (self.total + self.page_size - 1) // self.page_size

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
        }

    @classmethod
    def create(cls, items: List[T], total: int, page: int, page_size: int) -> "PageResponse[T]":
        """创建分页响应"""
        return cls(items=items, total=total, page=page, page_size=page_size)


@dataclass
class AuthToken:
    """认证令牌数据类"""

    token: str
    user_id: str
    expires_at: float
    issued_at: float = field(default_factory=time.time)
    scopes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "token": self.token,
            "user_id": self.user_id,
            "expires_at": self.expires_at,
            "issued_at": self.issued_at,
            "scopes": self.scopes,
            "metadata": self.metadata,
        }

    @property
    def is_expired(self) -> bool:
        """检查令牌是否过期"""
        return time.time() > self.expires_at

    @property
    def remaining_seconds(self) -> float:
        """获取剩余秒数"""
        return max(0, self.expires_at - time.time())

    def has_scope(self, scope: str) -> bool:
        """检查是否有指定权限"""
        return scope in self.scopes


class APIClient(ABC):
    """API客户端抽象基类"""

    def __init__(self, base_url: str, auth_token: Optional[AuthToken] = None):
        """
        初始化API客户端

        Args:
            base_url: 基础URL
            auth_token: 认证令牌
        """
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.default_headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}

    @abstractmethod
    async def request(
        self,
        method: HTTPMethod,
        path: str,
        headers: Dict[str, str] = None,
        query_params: Dict[str, str] = None,
        body: Any = None,
    ) -> APIResponse:
        """
        发送API请求

        Args:
            method: HTTP方法
            path: 请求路径
            headers: 请求头
            query_params: 查询参数
            body: 请求体

        Returns:
            API响应
        """

    async def get(self, path: str, params: Dict[str, str] = None) -> APIResponse:
        """GET请求"""
        return await self.request(HTTPMethod.GET, path, query_params=params)

    async def post(self, path: str, body: Any = None) -> APIResponse:
        """POST请求"""
        return await self.request(HTTPMethod.POST, path, body=body)

    async def put(self, path: str, body: Any = None) -> APIResponse:
        """PUT请求"""
        return await self.request(HTTPMethod.PUT, path, body=body)

    async def delete(self, path: str) -> APIResponse:
        """DELETE请求"""
        return await self.request(HTTPMethod.DELETE, path)

    async def patch(self, path: str, body: Any = None) -> APIResponse:
        """PATCH请求"""
        return await self.request(HTTPMethod.PATCH, path, body=body)

    def _get_auth_headers(self) -> Dict[str, str]:
        """获取认证头"""
        headers = {}

        if self.auth_token and not self.auth_token.is_expired:
            headers["Authorization"] = f"Bearer {self.auth_token.token}"

        return headers

    def _build_url(self, path: str) -> str:
        """构建完整URL"""
        return f"{self.base_url}/{path.lstrip('/')}"


class ModuleAPI(ABC):
    """模块API抽象基类"""

    def __init__(self, module_name: str, version: APIVersion = APIVersion.V3):
        """
        初始化模块API

        Args:
            module_name: 模块名称
            version: API版本
        """
        self.module_name = module_name
        self.version = version
        self._endpoints: Dict[str, Dict[str, Any]] = {}

    @abstractmethod
    async def handle_request(self, request: APIRequest) -> APIResponse:
        """
        处理API请求

        Args:
            request: API请求

        Returns:
            API响应
        """

    def register_endpoint(self, path: str, method: HTTPMethod, handler: typing.Callable, description: str = "") -> None:
        """
        注册端点

        Args:
            path: 端点路径
            method: HTTP方法
            handler: 处理函数
            description: 描述
        """
        endpoint_key = f"{method.value}:{path}"
        self._endpoints[endpoint_key] = {"path": path, "method": method, "handler": handler, "description": description}
        logger.debug("注册端点: %s", endpoint_key)

    def get_endpoints(self) -> Dict[str, Dict[str, Any]]:
        """获取所有端点"""
        return self._endpoints.copy()

    def get_endpoint(self, path: str, method: HTTPMethod) -> Optional[Dict[str, Any]]:
        """
        获取端点

        Args:
            path: 端点路径
            method: HTTP方法

        Returns:
            端点信息
        """
        endpoint_key = f"{method.value}:{path}"
        return self._endpoints.get(endpoint_key)

    def get_openapi_spec(self) -> Dict[str, Any]:
        """
        获取OpenAPI规范

        Returns:
            OpenAPI规范字典
        """
        paths = {}

        for endpoint_key, endpoint_info in self._endpoints.items():
            path = endpoint_info["path"]
            method = endpoint_info["method"].value.lower()

            if path not in paths:
                paths[path] = {}

            paths[path][method] = {
                "summary": endpoint_info["description"],
                "operationId": f"{method}_{path.replace('/', '_')}",
                "responses": {
                    "200": {"description": "成功", "content": {"application/json": {"schema": {"type": "object"}}}}
                },
            }

        return {
            "openapi": "3.0.0",
            "info": {
                "title": f"{self.module_name} API",
                "version": self.version.value,
                "description": f"{self.module_name} 模块API",
            },
            "paths": paths,
        }
