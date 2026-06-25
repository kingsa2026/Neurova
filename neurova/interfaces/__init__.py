"""
Neurova interfaces package - Unified API interface standards
"""

from neurova.core.logger import get_logger
logger = get_logger(__name__)

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

try:
    from neurova.auth.auth_protocol import AuthProtocol
except ImportError:
    AuthProtocol = None  # type: ignore[assignment,misc]

try:
    from neurova.api.error_codes import ErrorCodes
except ImportError:
    ErrorCodes = None  # type: ignore[assignment,misc]

try:
    from neurova.interfaces import api_standard
except ImportError:
    api_standard = None  # type: ignore[assignment]

__all__ = ["APIError", "APIResponse", "APIVersion", "AuthProtocol", "ErrorCodes", "api_standard"]
