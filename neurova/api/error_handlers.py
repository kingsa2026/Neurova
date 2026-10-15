"""
全局异常处理器

将业务异常 ``APIError``（普通 Exception 子类）转换为标准 JSON 错误信封。
未注册处理器时，APIError 会穿透到 Starlette 兜底逻辑，变成纯文本 500，
导致"记忆不存在"这类本应 404 的业务错误也以 500 呈现。
"""

import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from neurova.core.logger import get_logger
from neurova.interfaces.api_standard import APIError, ErrorCodes

logger = get_logger(__name__)

# 业务错误码 → HTTP 状态码。
# 原注释写着"未列出的错误码保持 500（与历史行为一致）"——那句就是病灶：默认落 500 等于
# **没人对失败表过态**。6001/6003/7001 一族说的是"服务还没就绪／子系统未启用"，
# 落成 500 会让调用方按"我方代码错了"去重试与报警，方向完全错；`memory` 的 search 端点
# 甚至曾捕住 6001 返回 200 空列表（教义第 2 条禁止的"把失败改写成成功形态"）。
# 现在每个声明过的码都必须二选一：进这张表，或进下面那份"按设计就是 5xx"的显式清单。
# 漏一个就有判据红：`tests/unit/api/test_MemoryReadFaceRefusesToPaintFailureAsSuccess.py`。
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
    # 未就绪 ≠ 出错：503 才带得出"等一会儿再来"的语义
    ErrorCodes.AGENT_NOT_INITIALIZED: 503,
    ErrorCodes.AGENT_NOT_READY: 503,
}

#: 按设计就该 5xx 的码（服务器自身故障）。列出来是为了让它"表过态"，不是为了走兜底。
#: `MEMORY_OPERATION_FAILED=7001` 在这里而不是 503 那张表里，是一条实测改判：它在本仓被**两用**
#: ——既报"记忆系统未启用"（未就绪）又报"添加/获取记忆失败: <异常>"（真故障）。把整个码映射成
#: 503 会把真故障报成"稍后再试"，调用方据此静默重试——比原来落 500 更糟（`test_internalFault
#: IsNotReportedAsVerdict` 三格当场抓住这件事）。未就绪那一用已由 `memory/base.py` 改抛
#: `AGENT_NOT_READY`（错码穿在对的状态上，修在产生它的一侧）。
_SERVER_FAULT_CODES = frozenset({
    ErrorCodes.UNKNOWN_ERROR,
    ErrorCodes.SERVER_ERROR,
    ErrorCodes.INTERNAL_ERROR,
    ErrorCodes.MEMORY_OPERATION_FAILED,
    ErrorCodes.MEMORY_SEARCH_FAILED,
})


def register_error_handlers(app: FastAPI) -> None:
    """在应用上注册 APIError 全局处理器"""

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        status_code = _CODE_TO_HTTP_STATUS.get(exc.code)
        if status_code is None:
            # 兜底仍保留（处理器不该因缺映射而 500 变成 500 文本页），但它必须**出声**：
            # 只有服务器故障清单里的码可以静默走 500，其余都是"声明与映射脱节"，当场点名。
            if exc.code not in _SERVER_FAULT_CODES:
                logger.warning(
                    "错误码 %s 未声明 HTTP 形态，按 500 呈现——请补进 _CODE_TO_HTTP_STATUS "
                    "或 _SERVER_FAULT_CODES", exc.code)
            status_code = 500
        body = {
            "code": exc.code,
            "message": exc.message,
            "timestamp": time.time(),
        }
        if exc.data is not None:
            body["data"] = exc.data
        return JSONResponse(status_code=status_code, content=body)
