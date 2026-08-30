"""
全局异常处理器

将业务异常 ``APIError``（普通 Exception 子类）转换为标准 JSON 错误信封。
未注册处理器时，APIError 会穿透到 Starlette 兜底逻辑，变成纯文本 500，
导致"记忆不存在"这类本应 404 的业务错误也以 500 呈现。
"""

import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from neurova.interfaces.api_standard import APIError, ErrorCodes

# 业务错误码 → HTTP 状态码。未列出的错误码保持 500（与历史行为一致）。
_CODE_TO_HTTP_STATUS = {
    ErrorCodes.VALIDATION_ERROR: 400,
    ErrorCodes.MEMORY_INVALID_CONTENT: 400,
    ErrorCodes.AUTH_FAILED: 401,
    ErrorCodes.TOKEN_EXPIRED: 401,
    ErrorCodes.PERMISSION_DENIED: 403,
    ErrorCodes.NOT_FOUND: 404,
    ErrorCodes.AGENT_NOT_FOUND: 404,
    ErrorCodes.MEMORY_NOT_FOUND: 404,
    ErrorCodes.RATE_LIMITED: 429,
}


def register_error_handlers(app: FastAPI) -> None:
    """在应用上注册 APIError 全局处理器"""

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        status_code = _CODE_TO_HTTP_STATUS.get(exc.code, 500)
        body = {
            "code": exc.code,
            "message": exc.message,
            "timestamp": time.time(),
        }
        if exc.data is not None:
            body["data"] = exc.data
        return JSONResponse(status_code=status_code, content=body)
