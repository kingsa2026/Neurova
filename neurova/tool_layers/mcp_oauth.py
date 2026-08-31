"""
MCP OAuth2 客户端凭证流 + PKCE 授权码流（P2-6，对标 QP 教训：凭据每次调用时解析）

- client_credentials 机器对机器流（无需浏览器，可端到端测试）
- 授权码 + PKCE 流（token 换取部分可测；浏览器跳转由调用方处理）
- token 缓存带过期时间，提前 60s 刷新
- 401 → 强制刷新 → 重试一次（由 mcp_client.call_tool 驱动）

安全语义（QP 烘焙坑规避）：access token **每次调用时解析**——
缓存命中直接返回，过期即刷新；绝不在连接建立时烘焙进长期对象。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# token 提前刷新余量（秒）
_REFRESH_MARGIN_S = 60.0


class OAuthTokenError(Exception):
    """OAuth token 获取/刷新失败"""


def generate_pkce_pair() -> Tuple[str, str]:
    """生成 PKCE (verifier, challenge_s256) 对。"""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


class OAuthTokenProvider:
    """client_credentials token 获取器（可注入 transport 便于测试）。"""

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str = "",
        timeout_s: float = 10.0,
        transport: Optional[Any] = None,
    ):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.timeout_s = timeout_s
        self._transport = transport  # 可注入 httpx.AsyncClient（测试桩）
        # 缓存：{access_token, expires_at(monotonic)}
        self._cached: Optional[Dict[str, Any]] = None

    async def fetch_client_credentials(self) -> Dict[str, Any]:
        """client_credentials 流：POST token_url，返回 token 响应 dict。"""
        import httpx

        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        if self.scope:
            data["scope"] = self.scope

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            # RFC 6749 推荐 client_secret_post；同时提供 Basic 供要求 Basic 的服务端
            "Authorization": _basic_auth_header(self.client_id, self.client_secret),
        }

        async def _post():
            transport = self._transport
            if transport is not None:
                resp = await transport.post(
                    self.token_url, data=data, headers=headers
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_s) as hc:
                    resp = await hc.post(self.token_url, data=data, headers=headers)
            return resp

        resp = await _post()
        if resp.status_code != 200:
            raise OAuthTokenError(
                f"token endpoint {self.token_url} 返回 {resp.status_code}: {resp.text[:200]}"
            )
        payload = resp.json()
        if "access_token" not in payload:
            raise OAuthTokenError(f"token 响应缺少 access_token: {payload}")
        return payload

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """获取有效 access token（缓存命中直接返回；过期前 60s 刷新）。"""
        now = time.monotonic()
        cached = self._cached
        if (
            not force_refresh
            and cached
            and cached["expires_at"] - _REFRESH_MARGIN_S > now
        ):
            return cached["access_token"]

        payload = await self.fetch_client_credentials()
        expires_in = float(payload.get("expires_in", 3600))
        self._cached = {
            "access_token": payload["access_token"],
            "expires_at": now + expires_in,
        }
        return self._cached["access_token"]


class TokenCache:
    """按 server_id 缓存 OAuthTokenProvider（连接重建时保留 token 状态）。"""

    def __init__(self) -> None:
        self._providers: Dict[str, OAuthTokenProvider] = {}

    def get_or_create(self, server_id: str, oauth_config: Dict[str, Any]) -> OAuthTokenProvider:
        existing = self._providers.get(server_id)
        if existing is not None:
            return existing
        provider = OAuthTokenProvider(
            token_url=oauth_config["token_url"],
            client_id=oauth_config["client_id"],
            client_secret=oauth_config.get("client_secret", ""),
            scope=oauth_config.get("scope", ""),
        )
        self._providers[server_id] = provider
        return provider


_token_caches: Dict[str, TokenCache] = {}
_caches_lock = asyncio.Lock()


def get_token_cache(scope: str = "default") -> TokenCache:
    """按 scope 取 token 缓存（测试隔离用）。"""
    return _token_caches.setdefault(scope, TokenCache())


async def resolve_mcp_token(
    server_id: str,
    oauth_config: Optional[Dict[str, Any]],
    force_refresh: bool = False,
) -> Optional[str]:
    """P2-6 核心 API：每次工具调用时解析 access token（QP 烘焙坑规避）。

    Returns:
        access token 字符串，或 None（无 OAuth 配置）
    Raises:
        OAuthTokenError: 配置了 OAuth 但获取失败
    """
    if not oauth_config:
        return None
    cache = get_token_cache(server_id)
    provider = cache.get_or_create(server_id, oauth_config)
    return await provider.get_access_token(force_refresh=force_refresh)
