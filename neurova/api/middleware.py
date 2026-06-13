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

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件"""

    def __init__(self, app: ASGIApp, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self._requests: dict = {}  # IP -> [timestamps]
        self._cleanup_interval = 60
        self._last_cleanup = time.time()

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        # 清理过期记录
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup_old_requests(now)
            self._last_cleanup = now

        # 检查速率
        if client_ip not in self._requests:
            self._requests[client_ip] = []

        # 移除超过1分钟的记录
        self._requests[client_ip] = [t for t in self._requests[client_ip] if now - t < 60]

        if len(self._requests[client_ip]) >= self.requests_per_minute:
            return JSONResponse(
                status_code=429,
                content={"code": 4290, "message": "Rate limit exceeded"},
            )

        self._requests[client_ip].append(now)

        response = await call_next(request)
        return response

    def _cleanup_old_requests(self, now: float):
        """清理过期的请求记录"""
        expired_ips = []
        for ip, timestamps in self._requests.items():
            self._requests[ip] = [t for t in timestamps if now - t < 60]
            if not self._requests[ip]:
                expired_ips.append(ip)
        for ip in expired_ips:
            del self._requests[ip]


def _load_cors_origins_from_config() -> list:
    """
    从配置文件加载 CORS origins

    优先级:
    1. 环境变量 NEUROVA_CORS_ORIGINS
    2. 配置文件 config/cors.json
    3. 默认值
    """
    import json as _json
    import os as _os
    from pathlib import Path

    # 1. 检查环境变量
    cors_origins_env = _os.getenv("NEUROVA_CORS_ORIGINS", "")
    if cors_origins_env:
        return [o.strip() for o in cors_origins_env.split(",") if o.strip()]

    # 2. 检查配置文件
    config_file = Path(__file__).parent.parent.parent / "config" / "cors.json"
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = _json.load(f)
                if "origins" in config and config["origins"]:
                    return config["origins"]
        except Exception as e:
            logger.warning("Failed to load CORS config from file: %s", e)

    # 3. 默认值（包含前端 dev server 端口 8100）
    return [
        "http://localhost:8100",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:8100",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]


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

    # 速率限制
    app.add_middleware(RateLimitMiddleware, requests_per_minute=120)

    logger.info("Middleware setup complete")
