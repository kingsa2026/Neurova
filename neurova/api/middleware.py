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

from neurova.api import cors_policy
from neurova.core.logger import get_logger
import os
import threading
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


#: 访问日志脱敏的参数名片段（审计 §3.1-19：?access_token= 类令牌不落日志）。
#: 命中任一片段（子串匹配，覆盖 access_token/refresh_token/api_key 等）即掩码。
_SENSITIVE_QUERY_FRAGMENTS = ("token", "secret", "password", "credential", "authorization", "signature", "key")


def redactQuery(query_string: str) -> str:
    """访问日志用的 query 脱敏：敏感参数只记"名字=<masked:N>"（N=原值长度），
    非敏感参数原样保留，排障可读性不降。"""
    if not query_string:
        return ""
    import urllib.parse as _up

    pairs = []
    for part in query_string.split("&"):
        key, _, value = part.partition("=")
        try:
            name = _up.unquote_plus(key).lower()
        except Exception:  # noqa: BLE001 - 解不动就按原名判
            name = key.lower()
        if any(fragment in name for fragment in _SENSITIVE_QUERY_FRAGMENTS):
            pairs.append(f"{key}=<masked:{len(value)}>")
        else:
            pairs.append(part)
    return "&".join(pairs)


class LoggingMiddleware(BaseHTTPMiddleware):
    """日志中间件 - 记录请求和响应信息"""

    def __init__(self, app: ASGIApp, log_body: bool = False):
        super().__init__(app)
        self.log_body = log_body

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = getattr(request.state, "request_id", "unknown")

        # 记录请求（query 经 redactQuery 脱敏——?access_token= 不落日志）
        logger.info(
            f"[{request_id}] {request.method} {request.url.path}",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": redactQuery(str(request.query_params)),
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


#: HSTS 开关（拍板 D-S4）：仅当 `NEUROVA_FORCE_HTTPS=1` 时下发 Strict-Transport-Security。
#: 发 HSTS 等于向浏览器承诺全站 HTTPS，本地明文调试环境不得发，否则 http 访问被强转。
HSTS_FORCE_HTTPS_ENV = "NEUROVA_FORCE_HTTPS"
HSTS_HEADER_VALUE = "max-age=31536000; includeSubDomains"

#: 每个响应都必带的安全头（HSTS 除外，受上面的开关控制）。
#: CSP 只落 `frame-ancestors 'none'`——本仓 API 无 HTML 面，防的是被第三方页面 iframe 嵌套。
BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "frame-ancestors 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全响应头中间件。

    必须装配在**最外层**（见 setup_middleware）：安全头属于响应出口面，与请求
    是否通过鉴权/限流无关，GlobalAuth/RateLimit 的 401/429 短路响应同样要盖到。
    HSTS 按 env 开关每请求读取（与 global_auth 的模式读取同惯例，便于测试与热切换）。
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        for name, value in BASE_SECURITY_HEADERS.items():
            response.headers[name] = value

        if (os.environ.get(HSTS_FORCE_HTTPS_ENV) or "").strip() == "1":
            response.headers["Strict-Transport-Security"] = HSTS_HEADER_VALUE

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

    def __init__(self, app: ASGIApp, limiter=None, identityTtlSeconds: float = 60.0):
        super().__init__(app)
        self._limiter = limiter
        self._identityTtlSeconds = identityTtlSeconds
        self._identityCache: dict = {}
        self._identityLock = threading.RLock()

    def _resolveLimiter(self):
        if self._limiter is None:
            from neurova.core.firewall import get_firewall

            self._limiter = get_firewall()
        return self._limiter

    def _quotaKey(self, request: Request) -> str:
        """配额键：已解析出的登录名，否则回退 client IP。

        必须用 username 而不是 user_id：组归属查的是登录名，而 token 里的
        user_id/neuser_id 是数字账号 id，喂错即静默查不到组（档位形同未接）。
        身份解析复用 global_auth 那份公开契约，不在这里另起一条凭证路径。
        """
        headers = dict(request.headers)
        credential = headers.get("authorization") or headers.get("x-service-token") or ""
        if not credential:
            return request.client.host if request.client else "unknown"

        now = time.time()
        with self._identityLock:
            hit = self._identityCache.get(credential)
            if hit and hit[1] > now:
                return hit[0] or (request.client.host if request.client else "unknown")

        from neurova.api.global_auth import authenticateRequest

        identity = authenticateRequest(headers)
        username = identity.get("username") if identity else None
        if username in (None, "unknown"):
            username = None

        with self._identityLock:
            if len(self._identityCache) > 4096:
                self._identityCache = {
                    key: value for key, value in self._identityCache.items() if value[1] > now
                }
            self._identityCache[credential] = (username, now + self._identityTtlSeconds)

        return username or (request.client.host if request.client else "unknown")

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

        allowed, reason = self._resolveLimiter().check_rate_limit(
            self._quotaKey(request), channel
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"code": 4290, "message": reason},
                headers={"Retry-After": str(RATE_LIMIT_RETRY_AFTER_SECONDS)},
            )

        return await call_next(request)


def setup_middleware(app: FastAPI) -> None:
    """
    设置所有中间件

    Args:
        app: FastAPI 应用实例
    """
    # CORS 四项口径全取自单源（origins 走 env > 配置文件 > 默认三级）。
    # 此前本模块自持一份 8 项白名单，与 endpoints/settings 那份逐字重复；
    # 而 `config/cors.json` 里的 allow_credentials 只有面板在读、装配处写死 True——
    # 管理员改了这一格却改不动生效值，故这里连凭证开关一起取生效口径。
    corsCfg = cors_policy.effectiveConfig()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=corsCfg["origins"],
        allow_credentials=corsCfg["allow_credentials"],
        allow_methods=list(cors_policy.ALLOW_METHODS),
        allow_headers=list(cors_policy.ALLOW_HEADERS),
    )

    # 请求 ID
    app.add_middleware(RequestIDMiddleware)

    # 日志
    app.add_middleware(LoggingMiddleware)

    # 限流额度唯一事实源 = core.firewall；组档位（人用渠道）在此装配注入，
    # 因为 core 不能 import auth（user_group_model 反向依赖 core.logger/data_root）。
    from neurova.api.group_rate_quota import groupRatePerMinute
    from neurova.core.firewall import get_firewall

    get_firewall().setRateQuotaResolver(groupRatePerMinute)

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

    # 安全响应头（S6 移层）：注册在**最外层**（最后注册 = 最外层）。原先挂在 CORS
    # 之后的内层，GlobalAuth/RateLimit 的 401/429 短路响应根本到不了它——未带 token
    # 的 401 一只安全头都没有。安全头属于响应出口面，与鉴权/限流结果无关，必须盖住
    # 全部响应；本中间件只补头不短路，不改变 CORS/限流/鉴权任何既有语义。
    app.add_middleware(SecurityHeadersMiddleware)

    logger.info("Middleware setup complete")
