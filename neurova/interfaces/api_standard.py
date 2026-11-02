from __future__ import annotations

"""
Neurova 统一 API 接口标准

定义:
1. 统一请求/响应格式
2. 错误码规范
3. 认证协议
4. API 版本管理

所有 API 模块都必须遵循此标准，确保接口一致性。
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

T = TypeVar("T")


class APIVersion(str, Enum):
    """API 版本"""

    V1 = "v1"
    V2 = "v2"


class ErrorCodes(int, Enum):
    """统一错误码"""

    SUCCESS = 0
    UNKNOWN_ERROR = 1000
    AUTH_FAILED = 2000
    TOKEN_EXPIRED = 2001
    PERMISSION_DENIED = 2002
    NOT_FOUND = 3000
    VALIDATION_ERROR = 4000
    RATE_LIMITED = 4290
    SERVER_ERROR = 5000
    INTERNAL_ERROR = 5001

    # Agent 相关错误码
    AGENT_NOT_INITIALIZED = 6001
    AGENT_NOT_FOUND = 6002
    AGENT_NOT_READY = 6003

    # 记忆系统错误码
    MEMORY_OPERATION_FAILED = 7001
    MEMORY_NOT_FOUND = 7002
    MEMORY_SEARCH_FAILED = 7003
    MEMORY_INVALID_CONTENT = 7004


#: 码 → 默认文案（批 G2）。抛出点必须给具体的 message；这里兜的是"抛出点
#: 没给话"的那一形——信封里出现空 message 比出现默认文案更伤（前端把
#: detail 原样显示给用户）。表与 ErrorCodes 同文件同源：加码必须同步加文案
#: （守卫 tests/unit/api/test_apiErrorCodesHaveDefaultCopy.py 缺一即红）。
DEFAULT_ERROR_MESSAGES: Dict["ErrorCodes", str] = {
    ErrorCodes.SUCCESS: "success",
    ErrorCodes.UNKNOWN_ERROR: "未知错误，请稍后重试",
    ErrorCodes.AUTH_FAILED: "认证失败，请重新登录",
    ErrorCodes.TOKEN_EXPIRED: "登录已过期，请重新登录",
    ErrorCodes.PERMISSION_DENIED: "没有执行此操作的权限",
    ErrorCodes.NOT_FOUND: "请求的资源不存在",
    ErrorCodes.VALIDATION_ERROR: "请求参数不合法",
    ErrorCodes.RATE_LIMITED: "请求过于频繁，请稍后再试",
    ErrorCodes.SERVER_ERROR: "服务器开小差了，请稍后重试",
    ErrorCodes.INTERNAL_ERROR: "内部错误，请稍后重试",
    ErrorCodes.AGENT_NOT_INITIALIZED: "智能体尚未初始化完成，请稍后再试",
    ErrorCodes.AGENT_NOT_FOUND: "指定的智能体不存在",
    ErrorCodes.AGENT_NOT_READY: "智能体尚未就绪，请稍后再试",
    ErrorCodes.MEMORY_OPERATION_FAILED: "记忆操作未能完成，请稍后重试",
    ErrorCodes.MEMORY_NOT_FOUND: "找不到那条记忆",
    ErrorCodes.MEMORY_SEARCH_FAILED: "记忆检索未能完成，请稍后重试",
    ErrorCodes.MEMORY_INVALID_CONTENT: "记忆内容不合规，无法写入",
}


@dataclass
class APIResponse(Generic[T]):
    """统一 API 响应格式"""

    code: int = ErrorCodes.SUCCESS
    message: str = "success"
    data: Optional[T] = None
    timestamp: float = field(default_factory=time.time)
    request_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "code": self.code,
            "message": self.message,
            "timestamp": self.timestamp,
        }
        if self.data is not None:
            result["data"] = self.data
        if self.request_id:
            result["request_id"] = self.request_id
        return result


class APIError(Exception):
    """API 错误异常类

    用于在 API 端点中抛出结构化错误，包含错误码和消息。
    支持工厂方法快速创建常见错误。
    """

    def __init__(self, code: int, message: str, data: Any = None):
        """
        初始化 APIError

        Args:
            code: 错误码
            message: 错误消息
            data: 附加数据
        """
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> Dict[str, Any]:
        """转换为错误响应字典"""
        result = {
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        return result

    @classmethod
    def not_found(cls, message: str = "资源不存在") -> "APIError":
        """创建 NOT_FOUND 错误"""
        return cls(ErrorCodes.NOT_FOUND, message)

    @classmethod
    def agent_not_found(cls, agent_id: str) -> "APIError":
        """创建 Agent 未找到错误"""
        return cls(ErrorCodes.AGENT_NOT_FOUND, f"Agent 不存在: {agent_id}")

    @classmethod
    def agent_not_initialized(cls, message: str = "Agent 未初始化") -> "APIError":
        """创建 Agent 未初始化错误"""
        return cls(ErrorCodes.AGENT_NOT_INITIALIZED, message)

    @classmethod
    def internal(cls, message: str = "内部服务器错误") -> "APIError":
        """创建内部服务器错误"""
        return cls(ErrorCodes.INTERNAL_ERROR, message)

    @classmethod
    def validation(cls, message: str = "验证错误") -> "APIError":
        """创建验证错误"""
        return cls(ErrorCodes.VALIDATION_ERROR, message)

    @classmethod
    def auth_failed(cls, message: str = "认证失败") -> "APIError":
        """创建认证失败错误"""
        return cls(ErrorCodes.AUTH_FAILED, message)

    @classmethod
    def permission_denied(cls, message: str = "权限不足") -> "APIError":
        """创建权限不足错误"""
        return cls(ErrorCodes.PERMISSION_DENIED, message)

    @classmethod
    def memory_operation_failed(cls, message: str = "记忆操作失败") -> "APIError":
        """创建记忆操作失败错误"""
        return cls(ErrorCodes.MEMORY_OPERATION_FAILED, message)

    @classmethod
    def memory_not_found(cls, message: str = "记忆未找到") -> "APIError":
        """创建记忆未找到错误"""
        return cls(ErrorCodes.MEMORY_NOT_FOUND, message)


def success_response(data: Any = None, message: str = "success", request_id: str = "") -> Dict[str, Any]:
    """
    成功响应快捷函数

    Args:
        data: 响应数据
        message: 成功消息
        request_id: 请求 ID

    Returns:
        格式化的成功响应字典
    """
    return APIResponse(
        code=ErrorCodes.SUCCESS,
        message=message,
        data=data,
        request_id=request_id,
    ).to_dict()


def error_response(
    code: int = ErrorCodes.UNKNOWN_ERROR,
    message: str = "error",
    data: Any = None,
    request_id: str = "",
) -> Dict[str, Any]:
    """
    错误响应快捷函数

    Args:
        code: 错误码
        message: 错误消息
        data: 附加数据
        request_id: 请求 ID

    Returns:
        格式化的错误响应字典
    """
    return APIResponse(
        code=code,
        message=message,
        data=data,
        request_id=request_id,
    ).to_dict()


def paginate_response(
    items: List[Any],
    total: int,
    page: int = 1,
    page_size: int = 20,
    request_id: str = "",
) -> Dict[str, Any]:
    """
    分页响应

    Args:
        items: 当前页数据
        total: 总记录数
        page: 当前页码
        page_size: 每页大小
        request_id: 请求 ID

    Returns:
        包含分页信息的响应字典
    """
    return success_response(
        data={
            "items": items,
            "pagination": {
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
            },
        },
        request_id=request_id,
    )
