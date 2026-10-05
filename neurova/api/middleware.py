"""
FastAPI 中间件集合

包含:
- CORS 中间件
- 安全响应头中间件
- 请求ID中间件
- 日志中间件
- 速率限制中间件
- 认证中间件
"""

from neurova.core import config
from neurova.core.logger import get_logger
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """请求 ID 中间件 - 为每个请求生成唯一 ID"""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class LoggingMiddleware(BaseHTTPMiddleware):
    """日志中间件 - 记录请求和响应信息"""

    def __init__(self, app: ASGIApp, log_body: bool = False):
        super().__init__(app)
        self.log_body = log_body

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = getattr(request.state, "request_id", "unknown")

        # 记录请求
        logger.info(
            f"[{request_id}] {request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params),
                "client": request.client.host if request.client else "unknown",
            },
        )

        # 执行请求
        try:
            response = await call_next(request)
        except Exception as e:
            logger.error(f"[{request_id}] Request failed: {e}", exc_info=True)
            raise

        # 记录响应
        duration = time.time() - start_time
        logger.info(
            f"[{request_id}] {response.status_code} ({duration:.3f}s)",
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "duration": duration,
            },
        )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件"""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 安全头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response


#: 外部 Agent 接入面的路径前缀。必须等于注册表里
#: `("neurova.api.endpoints.agent_communication_api", "/v1/agent-communication", ...)`
#: 一行加上 `/api` 根前缀后的实际挂载名——改挂载名时两处同批，否则外部渠道会静默
#: 退回内部档（额度变严，且没有任何报错）。
EXTERNAL_AGENT_PATH_PREFIX = "/api/v1/agent-communication"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """全站**唯一**的速率限制执行点。

    它在 handler 之前拦截，因此端点内不得再查一次额度——那永远轮不到触发，
    属"接了不生效"的断点（本中间件此前按 client IP 硬编码 120/分，端点级检查
    正是在它之后才可达）。额度取自 `core.firewall`（唯一事实源），按路径分渠道：
    外部 Agent 接入面走 externalAgent 档，其余走 internal 档。

    配额键优先用已解析出的身份，否则回退 client IP。不在这里另起一套 JWT 解析——
    那会成为仓内第三条凭证路径（`api/auth.py`、`api/deps.py`、memory 域旁路已足鉴）。
    """

    def __init__(self, app: ASGIApp, limiter=None):
        super().__init__(app)
        self._limiter = limiter

    def _resolveLimiter(self):
        if self._limiter is None:
            from neurova.core.firewall import get_firewall

            self._limiter = get_firewall()
        return self._limiter

    async def dispatch(self, request: Request, call_next):
        from neurova.core.firewall import (
            CHANNEL_EXTERNAL_AGENT,
            CHANNEL_INTERNAL,
            RATE_LIMIT_RETRY_AFTER_SECONDS,
        )

        channel = (
            CHANNEL_EXTERNAL_AGENT
            if request.url.path.startswith(EXTERNAL_AGENT_PATH_PREFIX)
            else CHANNEL_INTERNAL
        )
        quotaKey = getattr(request.state, "user_id", None) or (
            request.client.host if request.client else "unknown"
        )

        allowed, reason = self._resolveLimiter().check_rate_limit(quotaKey, channel)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"code": 4290, "message": reason},
                headers={"Retry-After": str(RATE_LIMIT_RETRY_AFTER_SECONDS)},
            )

        return await call_next(request)


# 兜底默认值：开发端口 + Tauri v2 桌面壳 WebView origin
# （Windows 打包态为 http://tauri.localhost；https 变体覆盖 useHttpsScheme 场景）
DEFAULT_CORS_ORIGINS = [
    "http://localhost:8100",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:8100",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://tauri.localhost",
    "https://tauri.localhost",
]


def _load_cors_origins_from_config(config_file=None) -> list:
    """
    从配置文件加载 CORS origins

    优先级:
    1. 环境变量 NEUROVA_CORS_ORIGINS
    2. 配置文件 config/cors.json
    3. 默认值

    Args:
        config_file: 配置文件路径；None 时使用仓库 config/cors.json（测试可注入临时路径）
    """
    import json as _json
    from pathlib import Path

    # 1. 检查环境变量
    cors_origins_env = config.get("NEUROVA_CORS_ORIGINS", "")
    if cors_origins_env:
        return [o.strip() for o in cors_origins_env.split(",") if o.strip()]

    # 2. 检查配置文件
    if config_file is None:
        config_file = Path(__file__).parent.parent.parent / "config" / "cors.json"
    if Path(config_file).exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                # 注意：变量名用 cors_config，避免遮蔽模块级 config
                cors_config = _json.load(f)
                if "origins" in cors_config and cors_config["origins"]:
                    return cors_config["origins"]
        except Exception as e:
            logger.warning("Failed to load CORS config from file: %s", e)

    # 3. 默认值
    return list(DEFAULT_CORS_ORIGINS)


def setup_middleware(app: FastAPI) -> None:
    """
    设置所有中间件

    Args:
        app: FastAPI 应用实例
    """
    # CORS 配置 — 支持环境变量、配置文件、默认值三种方式
    cors_origins = _load_cors_origins_from_config()

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID"],
    )

    # 安全响应头
    app.add_middleware(SecurityHeadersMiddleware)

    # 请求 ID
    app.add_middleware(RequestIDMiddleware)

    # 日志
    app.add_middleware(LoggingMiddleware)

    # 速率限制（全站唯一执行点；额度取自 core.firewall，不再在此硬编码）
    app.add_middleware(RateLimitMiddleware)

    # 全局鉴权白名单 (BUG AUDIT S-08 收口)：默认 off 完全惰性；
    # NEUROVA_GLOBAL_AUTH=shadow 记录匿名访问取证 / enforce 白名单外强制凭证。
    # 先于限流/日志拒绝未认证请求。
    from neurova.api.global_auth import GlobalAuthMiddleware

    app.add_middleware(GlobalAuthMiddleware)

    # HTTP 请求时长 (P1-6)：纯 ASGI，route label 用路由模板（不用原始 path，
    # 否则 /items/1 与 /items/2 各成一条时间线，基数爆炸）。
    #
    # 刻意注册在**最外层**（最后注册 = 最外层）：实测若放在 GlobalAuth 内层，
    # enforce 模式下的 401 拒绝请求完全进不了指标（GlobalAuth 在外层直接返回，
    # 请求永远到不了内层中间件）—— 于是"401 洪峰"在观测面上是空白。放最外层
    # 后覆盖"全部入站 HTTP 请求"，且不改变任何鉴权行为（本中间件不做鉴权）。
    from neurova.api.http_metrics import HttpMetricsMiddleware

    app.add_middleware(HttpMetricsMiddleware)

    logger.info("Middleware setup complete")
