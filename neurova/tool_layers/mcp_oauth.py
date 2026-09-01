"""
MCP OAuth2 客户端凭证流 + PKCE 授权码流（P2-6/P3-b，对标 QP 教训：凭据每次调用时解析）

- client_credentials 机器对机器流（无需浏览器，可端到端测试）
- 授权码 + PKCE 流（P3-b：授权 URL 构建 → 浏览器跳转 → 本地环回回调捕获
  → code+verifier 换 token → 入缓存供 per-call 解析）
- token 缓存带过期时间，提前 60s 刷新
- 401 → 强制刷新 → 重试一次（由 mcp_client.call_tool 驱动）

安全语义（QP 烘焙坑规避）：access token **每次调用时解析**——
缓存命中直接返回，过期即刷新；绝不在连接建立时烘焙进长期对象。

授权码流安全要点：
- state 单次随机（CSRF 防护），回调不匹配即中止，绝不换 token
- 回调仅允许环回地址（RFC 8252），拒绝非环回 redirect_uri
- 回调服务器一次性捕获，超时即弃（默认 300s）
- access_token 经 PKCE verifier 换取；public client 可不带 client_secret
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

logger = logging.getLogger(__name__)

# token 提前刷新余量（秒）
_REFRESH_MARGIN_S = 60.0

# 授权码流默认等待回调超时（秒）
_AUTH_DEFAULT_TIMEOUT_S = 300.0

# 允许作为回调监听的环回主机名（RFC 8252 loopback）
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class OAuthTokenError(Exception):
    """OAuth token 获取/刷新失败"""


def generate_pkce_pair() -> Tuple[str, str]:
    """生成 PKCE (verifier, challenge_s256) 对。"""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(
    authorization_url: str,
    client_id: str,
    redirect_uri: str,
    scope: str = "",
    state: str = "",
    code_challenge: str = "",
) -> str:
    """构建授权端点 URL（RFC 6749 §4.1.1 + RFC 7636 S256）。"""
    params: Dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    if scope:
        params["scope"] = scope
    if state:
        params["state"] = state
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    sep = "&" if "?" in authorization_url else "?"
    return f"{authorization_url}{sep}{urlencode(params)}"


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

    def get_cached_token(self) -> Optional[str]:
        """返回仍有效的缓存 token（过期/无缓存返回 None）。授权码流无刷新端点，
        过期即 None，由调用方决定重新走授权。"""
        cached = self._cached
        if cached and cached["expires_at"] - _REFRESH_MARGIN_S > time.monotonic():
            return cached["access_token"]
        return None

    async def fetch_token_by_code(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> str:
        """授权码换 token（RFC 6749 §4.1.3），成功后写入缓存供 per-call 解析。"""
        import httpx

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        # P3-b：DCR 产物的 registration_access_token → Bearer 保护 token 端点；
        # 无则回退 Basic（confidential client）/ 无头（public client）
        extra_auth = getattr(self, "_extra_auth_header", None)
        if extra_auth:
            headers.update(extra_auth)
        elif self.client_secret:
            headers["Authorization"] = _basic_auth_header(self.client_id, self.client_secret)

        transport = self._transport
        if transport is not None:
            resp = await transport.post(self.token_url, data=data, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_s) as hc:
                resp = await hc.post(self.token_url, data=data, headers=headers)

        if resp.status_code != 200:
            raise OAuthTokenError(
                f"token endpoint {self.token_url} 返回 {resp.status_code}: {resp.text[:200]}"
            )
        payload = resp.json()
        if "access_token" not in payload:
            raise OAuthTokenError(f"token 响应缺少 access_token: {payload}")

        expires_in = float(payload.get("expires_in", 3600))
        self._cached = {
            "access_token": payload["access_token"],
            "expires_at": time.monotonic() + expires_in,
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

    grant_type 感知：
    - client_credentials（默认）：缓存失效自动重取
    - authorization_code：无刷新能力，只用缓存中的有效 token；
      无 token / 过期 → OAuthTokenError 并提示重新授权

    Returns:
        access token 字符串，或 None（无 OAuth 配置）
    Raises:
        OAuthTokenError: 配置了 OAuth 但获取失败
    """
    if not oauth_config:
        return None
    cache = get_token_cache(server_id)
    grant_type = (oauth_config.get("grant_type") or "client_credentials").strip()

    if grant_type == "authorization_code":
        provider = cache.get_or_create(server_id, oauth_config)
        token = provider.get_cached_token()
        if token is None:
            if force_refresh:
                raise OAuthTokenError(
                    "authorization_code 流不支持静默刷新（无 refresh token）：请重新授权"
                )
            raise OAuthTokenError(
                "尚未授权或授权已过期：请先调用 run_authorization_code_flow 完成浏览器授权"
            )
        return token

    provider = cache.get_or_create(server_id, oauth_config)
    return await provider.get_access_token(force_refresh=force_refresh)


class OAuthCallbackServer:
    """一次性本地环回回调服务器（RFC 8252）：捕获 IdP 重定向 query。

    线程模型：HTTPServer 在守护线程 serve_forever；捕获到回调即置结果并
    返回 200 页面；wait() 供主流程带超时等待。
    """

    def __init__(self, host: str = "127.0.0.1") -> None:
        self._host = host
        self.port: int = 0
        self.params: Dict[str, str] = {}
        self.error: Optional[str] = None
        self._done = threading.Event()
        self._httpd: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        server = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
                parsed = urlparse(self.path)
                if parsed.path.rstrip("/") not in {"", "/callback"}:
                    self.send_response(404)
                    self.end_headers()
                    return
                qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                if "error" in qs:
                    server.error = qs["error"]
                else:
                    server.params = qs
                server._done.set()
                body = b"<html><body><h3>Authorization received.</h3>You can close this window.</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # 静默默认日志
                pass

        # 端口 0 = 内核分配临时端口（环回一次性回调，无固定端口冲突）
        self._httpd = HTTPServer((self._host, 0), _Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def redirect_uri(self) -> str:
        return f"http://{self._host}:{self.port}/callback"

    def wait(self, timeout_s: float) -> bool:
        """等待回调到达；超时返回 False。"""
        return self._done.wait(timeout_s)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


def _is_loopback_redirect_uri(redirect_uri: str) -> bool:
    """RFC 8252：授权码流回调仅允许环回地址（防回调劫持到远端）。"""
    try:
        parsed = urlparse(redirect_uri)
    except Exception:
        return False
    if parsed.scheme != "http":
        return False
    return parsed.hostname in _LOOPBACK_HOSTS


async def _register_client_dynamically(
    registration_endpoint: str,
    redirect_uri: str,
    scope: str,
    client_name: str,
    transport: Optional[Any] = None,
) -> tuple:
    """RFC 7591 动态客户端注册（P3-b）。

    POST registration_endpoint：
    - client_name = neurova-mcp-<server_id>
    - grant_types = ["authorization_code", "refresh_token"]
    - token_endpoint_auth_method = "none"（public client，PKCE 保护）
    - redirect_uris = [环回回调地址]

    Returns:
        (client_id, client_secret 或 "", registration_access_token 或 "")

    Raises:
        OAuthTokenError: 注册端点非 200 / 响应缺 client_id
    """
    import httpx

    payload = {
        "client_name": client_name,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "redirect_uris": [redirect_uri],
    }
    if scope:
        payload["scope"] = scope

    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    if transport is not None:
        resp = await transport.post(registration_endpoint, data=payload, headers=headers)
    else:
        async with httpx.AsyncClient(timeout=10.0) as hc:
            resp = await hc.post(registration_endpoint, json=payload, headers=headers)

    if resp.status_code != 201 and resp.status_code != 200:
        raise OAuthTokenError(
            f"动态客户端注册失败（RFC 7591）：{registration_endpoint} 返回 "
            f"{resp.status_code}: {str(resp.text)[:200]}"
        )
    body = resp.json()
    if not body.get("client_id"):
        raise OAuthTokenError(
            f"动态客户端注册响应缺少 client_id: {str(body)[:200]}"
        )
    return (
        body["client_id"],
        body.get("client_secret") or "",
        body.get("registration_access_token") or "",
    )


async def run_authorization_code_flow(
    server_id: str,
    oauth_config: Dict[str, Any],
    timeout_s: float = _AUTH_DEFAULT_TIMEOUT_S,
    transport: Optional[Any] = None,
    opener: Optional[Callable[[str], bool]] = None,
) -> str:
    """P3-b 核心 API：完整授权码流（浏览器跳转 → 回调 → 换 token → 入缓存）。

    步骤：
    1. 校验 oauth_config（authorization_url/token_url/client_id 必需；
       redirect_uri 若显式提供必须环回——显式非环回直接拒绝）
    2. 生成 PKCE 对 + 单次随机 state
    3. 启动本地环回回调服务器（临时端口）
    4. 构建授权 URL 并经 opener 打开浏览器（默认 webbrowser.open）
    5. 等待回调（超时 OAuthTokenError）；error 响应即中止
    6. state 校验（CSRF）——不匹配绝不换 token
    7. code + verifier 换 token，写入 per-call 解析缓存

    Args:
        server_id: MCP server 标识（缓存键）
        oauth_config: 服务端 OAuth 配置
        timeout_s: 等待用户完成浏览器授权的超时
        transport: 注入式 HTTP transport（测试桩）
        opener: 注入式浏览器打开函数（测试桩）；默认 webbrowser.open

    Returns:
        access token
    """
    import webbrowser

    authorization_url = oauth_config.get("authorization_url")
    token_url = oauth_config.get("token_url")
    registration_endpoint = oauth_config.get("registration_endpoint")
    client_id = oauth_config.get("client_id")
    if not authorization_url or not token_url:
        raise ValueError(
            "authorization_code 流需要 authorization_url / token_url 配置"
        )
    if not client_id and not registration_endpoint:
        raise ValueError(
            "authorization_code 流需要 client_id 配置；无预配置 client_id 时 "
            "必须提供 registration_endpoint 以走 RFC 7591 动态客户端注册（DCR）"
        )

    explicit_redirect = oauth_config.get("redirect_uri") or ""
    if explicit_redirect and not _is_loopback_redirect_uri(explicit_redirect):
        raise ValueError(
            f"redirect_uri 必须是环回地址（RFC 8252），拒绝: {explicit_redirect}"
        )

    scope = oauth_config.get("scope", "")

    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(24)

    callback = OAuthCallbackServer()
    callback.start()
    try:
        redirect_uri = explicit_redirect or callback.redirect_uri

        # P3-b：DCR（RFC 7591）——无预配置 client_id 时在回调端口确定后
        # 动态注册 public client，注册产物回填（redirect_uri 需在注册时已知）
        registration_access_token: Optional[str] = None
        _dcr_client_secret: Optional[str] = None
        if not client_id:
            client_id, _dcr_client_secret, registration_access_token = (
                await _register_client_dynamically(
                    registration_endpoint, redirect_uri, scope,
                    client_name=f"neurova-mcp-{server_id}",
                    transport=transport,
                )
            )
            logger.info("MCP DCR 完成 (server=%s): client_id=%s", server_id, client_id)
        _dcr_outcome = {
            "client_id": client_id,
            "client_secret": _dcr_client_secret,
            "registration_access_token": registration_access_token,
        }

        auth_url = build_authorization_url(
            authorization_url,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
            code_challenge=challenge,
        )

        open_fn = opener or (lambda url: webbrowser.open(url))
        opened = open_fn(auth_url)
        if not opened:
            raise OAuthTokenError(f"无法打开浏览器进行授权: {auth_url}")
        logger.info("已打开浏览器等待 MCP 授权 (server=%s): %.120s", server_id, auth_url)

        if not callback.wait(timeout_s):
            raise OAuthTokenError(
                f"等待授权回调超时（{timeout_s}s）：用户未在浏览器完成授权"
            )

        if callback.error:
            raise OAuthTokenError(f"授权被拒绝或失败: {callback.error}")

        if callback.params.get("state") != state:
            raise OAuthTokenError("授权回调 state 不匹配（可能的 CSRF），已中止换 token")

        code = callback.params.get("code")
        if not code:
            raise OAuthTokenError(f"授权回调缺少 code: {list(callback.params)}")

        # DCR 产物回填进 oauth_config（get_or_create 以此构造 provider）
        oauth_config["client_id"] = _dcr_outcome["client_id"]
        if _dcr_outcome.get("client_secret"):
            oauth_config["client_secret"] = _dcr_outcome["client_secret"]

        provider = get_token_cache(server_id).get_or_create(server_id, oauth_config)
        provider._transport = transport  # 测试注入通道；生产走 httpx
        # registration_access_token 下发时 token 端点以 Bearer 保护
        if _dcr_outcome.get("registration_access_token"):
            provider._extra_auth_header = {
                "Authorization": f"Bearer {_dcr_outcome['registration_access_token']}"
            }
        return await provider.fetch_token_by_code(code, verifier, redirect_uri)
    finally:
        callback.stop()
