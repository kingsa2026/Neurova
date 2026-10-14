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

from neurova.auth.auth_protocol import AuthProtocol

from neurova.api.error_codes import ErrorCodes

from neurova.interfaces import api_standard

__all__ = ["APIError", "APIResponse", "APIVersion", "AuthProtocol", "ErrorCodes", "api_standard"]
