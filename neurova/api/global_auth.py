"""
全局鉴权白名单机制 (BUG AUDIT S-08 收口)

审计原判：app.py 无全局 dependencies，端点是否鉴权全靠手写 Depends，
新端点默认裸奔（清点基线 2026-09-11：478 OPEN / 356 已锁）。

本模块提供路径白名单 + 三态开关（环境变量 NEUROVA_GLOBAL_AUTH）：

- ``off``（默认，未设置）: 中间件完全惰性，零行为变化（只提升不下降）；
- ``shadow``: 非白名单路径的匿名访问按路径去重记 INFO 日志，
  为"前端全量调用审计"提供证据（哪些路径仍被匿名消费）；
- ``enforce``: 非白名单路径必须持有效 Bearer JWT 或 X-Service-Token，
  否则 401（信封与 APIError 处理器同形：code/message/timestamp）。

鉴权判定复用 neurova.api.auth 的 verify_access_token 与服务令牌契约
（单一事实源），WebSocket scope 直接透传（WS 鉴权由端点自管）。
白名单为精确路径匹配，不做前缀扩散，防止 /auth/login-evil 类绕过。
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Set

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 首启/登录链路（桌面端注册即管理员、登录、验证码、找回密码）
# + 运维可观测（健康检查/指标/状态）+ 前端错误上报（公开写入设计）。
PUBLIC_EXACT_PATHS: Set[str] = {
    # 健康与运维
    "/health",
    "/health/detailed",
    "/metrics",
    "/api/v1/status",
    "/test",
    # FastAPI 文档
    "/docs",
    "/redoc",
    "/openapi.json",
    # 认证链路（/api/v1/auth/me 等不在内，仍需鉴权）
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/register",
    "/api/v1/auth/register/send-code",
    "/api/v1/auth/register/verify-code",
    "/api/v1/auth/setup-status",
    "/api/v1/auth/recover-password",
    # 前端错误自动上报（匿名写入设计）
    "/api/v1/frontend/errors",
}

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"
_VALID_MODES = (MODE_OFF, MODE_SHADOW, MODE_ENFORCE)

# shadow 模式取证集合：进程内路径级去重，避免日志洪水；跨 app 实例聚合
_SHADOW_SEEN: Set[str] = set()


def get_global_auth_mode() -> str:
    """读取全局鉴权模式（每请求读取，便于测试与热切换）"""
    raw = (os.environ.get("NEUROVA_GLOBAL_AUTH") or "").strip().lower()
    return raw if raw in _VALID_MODES else MODE_OFF


def is_public_path(path: str) -> bool:
    """精确白名单匹配（不做前缀扩散）"""
    return path in PUBLIC_EXACT_PATHS


def shadow_audit_paths() -> List[str]:
    """shadow 模式已记录的匿名访问路径（去重排序）"""
    return sorted(_SHADOW_SEEN)


def reset_shadow_audit() -> None:
    """清空 shadow 取证记录（测试/运维用）"""
    _SHADOW_SEEN.clear()


class GlobalAuthMiddleware:
    """纯 ASGI 全局鉴权白名单中间件（SSE/流式安全，不走 BaseHTTPMiddleware）"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        mode = get_global_auth_mode()
        if mode == MODE_OFF:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # CORS 预检先于鉴权放行；白名单精确放行
        if scope.get("method", "").upper() == "OPTIONS" or is_public_path(path):
            await self.app(scope, receive, send)
            return

        headers = _headers_dict(scope)
        identity = _authenticate(headers)
        if identity is not None:
            await self.app(scope, receive, send)
            return

        if mode == MODE_SHADOW:
            if path not in _SHADOW_SEEN:
                _SHADOW_SEEN.add(path)
                logger.info(
                    "全局鉴权 shadow 取证: 匿名访问受保护路径 %s %s",
                    scope.get("method", "?"),
                    path,
                )
            await self.app(scope, receive, send)
            return

        # enforce：401，信封与 APIError 处理器同形
        body = (
            b'{"code":"AUTH_FAILED","message":"Not authenticated",'
            b'"timestamp":' + str(time.time()).encode() + b"}"
        )
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _headers_dict(scope) -> Dict[str, str]:
    """ASGI headers → 小写键字典"""
    out: Dict[str, str] = {}
    for raw_key, raw_val in scope.get("headers") or []:
        try:
            out[raw_key.decode("latin-1").lower()] = raw_val.decode("latin-1")
        except Exception:
            continue
    return out


def _authenticate(headers: Dict[str, str]) -> Optional[Dict]:
    """验证 Bearer JWT 或 X-Service-Token；有效返回身份，无效/缺失返回 None。

    复用 neurova.api.auth 契约（单一事实源），不在本模块重复实现。
    """
    # 延迟导入：auth.py 较重，仅 enforce/shadow 校验时加载
    from neurova.api.auth import verify_access_token, service_token_matches

    if service_token_matches(headers.get("x-service-token", "")):
        return {
            "user_id": "system",
            "username": "service",
            "role": "admin",
            "auth_source": "service_token",
        }

    authorization = headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        payload = verify_access_token(authorization[7:].strip())
        if payload:
            sub = payload.get("sub", "unknown")
            return {
                "user_id": sub,
                "username": payload.get("username", "unknown"),
                "role": payload.get("role", "user"),
                "neuser_id": payload.get("neuser_id") or sub,
            }
    return None
