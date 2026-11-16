"""
Neurova interfaces package - Unified API interface standards
"""


# FastAPI 为可选依赖，缺失时提供 None 占位
try:
    from fastapi import HTTPException as APIError
except ImportError:
    APIError = None  # type: ignore[assignment,misc]

try:
    from fastapi.responses import JSONResponse as APIResponse
except ImportError:
    APIResponse = None  # type: ignore[assignment,misc]

try:
    from fastapi import FastAPI as APIVersion
except ImportError:
    APIVersion = None  # type: ignore[assignment,misc]

from neurova.api.error_codes import ErrorCodes

from neurova.interfaces import api_standard

# （S7 死码退役批）AuthProtocol 已随 auth/auth_protocol.py 退役摘除（P2：
# 零实现零消费的占位协议，此前却被当作"已接真"导出）。

__all__ = ["APIError", "APIResponse", "APIVersion", "ErrorCodes", "api_standard"]
