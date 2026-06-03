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

from dataclasses import dataclass, field
import enum
import time
import typing
from typing import Any, Dict, Generic, List, Optional, TypeVar

from enum import Enum

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
