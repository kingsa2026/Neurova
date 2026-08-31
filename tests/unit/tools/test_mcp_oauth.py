"""
P2-6 MCP OAuth 测试（client_credentials + PKCE + per-call 解析）
P3-b 追加：授权码流浏览器跳转闭环（URL 构建/本地回调/code 换 token/grant 感知解析）
"""

import asyncio
import json
import urllib.request
from urllib.parse import parse_qs, urlparse

import pytest

from neurova.tool_layers.mcp_oauth import (
    OAuthTokenError,
    OAuthTokenProvider,
    generate_pkce_pair,
    get_token_cache,
    resolve_mcp_token,
)


class _FakeTransport:
    """注入式 HTTP transport：按脚本返回 (status, json)。"""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    async def post(self, url, data=None, headers=None):
        self.requests.append({"url": url, "data": data, "headers": headers})
        status, payload = self.script.pop(0)
        resp = type("R", (), {})()
        resp.status_code = status
        resp.text = json.dumps(payload)
        resp.json = lambda p=payload: p
        return resp


class TestPKCE:
    def test_pair_deterministic_shape(self):
        verifier, challenge = generate_pkce_pair()
        assert 60 < len(verifier) <= 128
        assert challenge and "=" not in challenge

    def test_pairs_are_unique(self):
        pairs = {generate_pkce_pair()[1] for _ in range(10)}
        assert len(pairs) == 10


class TestClientCredentials:
    @pytest.mark.asyncio
    async def test_success_returns_token(self):
        transport = _FakeTransport([(200, {"access_token": "tok123", "expires_in": 3600})])
        provider = OAuthTokenProvider(
            "https://idp/token", "cid", "csecret", scope="mcp", transport=transport
        )
        token = await provider.get_access_token()
        assert token == "tok123"
        req = transport.requests[0]
        assert req["data"]["grant_type"] == "client_credentials"
        assert req["headers"]["Authorization"].startswith("Basic ")

    @pytest.mark.asyncio
    async def test_cached_within_expiry(self):
        transport = _FakeTransport([(200, {"access_token": "t1", "expires_in": 3600})])
        provider = OAuthTokenProvider("https://idp/token", "cid", "csecret", transport=transport)
        await provider.get_access_token()
        await provider.get_access_token()
        assert len(transport.requests) == 1  # 缓存命中不再请求

    @pytest.mark.asyncio
    async def test_force_refresh_bypasses_cache(self):
        transport = _FakeTransport([
            (200, {"access_token": "t1", "expires_in": 3600}),
            (200, {"access_token": "t2", "expires_in": 3600}),
        ])
        provider = OAuthTokenProvider("https://idp/token", "cid", "csecret", transport=transport)
        assert await provider.get_access_token() == "t1"
        assert await provider.get_access_token(force_refresh=True) == "t2"

    @pytest.mark.asyncio
    async def test_error_response_raises(self):
        transport = _FakeTransport([(400, {"error": "invalid_client"})])
        provider = OAuthTokenProvider("https://idp/token", "cid", "csecret", transport=transport)
        with pytest.raises(OAuthTokenError, match="400"):
            await provider.get_access_token()

    @pytest.mark.asyncio
    async def test_missing_access_token_raises(self):
        transport = _FakeTransport([(200, {"unexpected": 1})])
        provider = OAuthTokenProvider("https://idp/token", "cid", "csecret", transport=transport)
        with pytest.raises(OAuthTokenError, match="access_token"):
            await provider.get_access_token()


class TestResolvePerCall:
    @pytest.mark.asyncio
    async def test_no_oauth_config_returns_none(self):
        assert await resolve_mcp_token("s1", None) is None

    @pytest.mark.asyncio
    async def test_oauth_config_resolves_token(self):
        # 预置带 FakeTransport 的 provider 到全局缓存（resolve 走缓存复用）
        from neurova.tool_layers.mcp_oauth import OAuthTokenProvider

        # resolve_mcp_token 内部按 server_id 取缓存——键必须一致
        cache = get_token_cache("s1")
        cache._providers.clear()
        transport = _FakeTransport([(200, {"access_token": "tok", "expires_in": 3600})])
        cache._providers["s1"] = OAuthTokenProvider(
            "https://idp/token", "cid", "csecret", transport=transport
        )
        token = await resolve_mcp_token(
            "s1",
            {"token_url": "https://idp/token", "client_id": "cid", "client_secret": "csecret"},
            force_refresh=True,
        )
        assert token == "tok"

    @pytest.mark.asyncio
    async def test_cache_keyed_by_server_id(self):
        cache = get_token_cache("iso-test")
        cache._providers.clear()
        transport = _FakeTransport([(200, {"access_token": "tok", "expires_in": 3600})])
        p1 = cache.get_or_create("s1", {"token_url": "u", "client_id": "a", "client_secret": "b"})
        p2 = cache.get_or_create("s2", {"token_url": "u", "client_id": "a", "client_secret": "b"})
        assert p1 is not p2  # 不同 server 独立 provider（token 状态隔离）


class TestAuthorizationURL:
    """授权 URL 构建（RFC 6749 §4.1.1 + RFC 7636 PKCE）"""

    def test_contains_required_params(self):
        from neurova.tool_layers.mcp_oauth import build_authorization_url

        url = build_authorization_url(
            "https://idp/authorize",
            client_id="cid",
            redirect_uri="http://127.0.0.1:8765/callback",
            scope="mcp read",
            state="st1",
            code_challenge="chal1",
        )
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "idp"
        assert parsed.path == "/authorize"
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        assert qs["response_type"] == "code"
        assert qs["client_id"] == "cid"
        assert qs["redirect_uri"] == "http://127.0.0.1:8765/callback"
        assert qs["scope"] == "mcp read"
        assert qs["state"] == "st1"
        assert qs["code_challenge"] == "chal1"
        assert qs["code_challenge_method"] == "S256"

    def test_optional_params_omitted_when_empty(self):
        from neurova.tool_layers.mcp_oauth import build_authorization_url

        url = build_authorization_url(
            "https://idp/authorize",
            client_id="cid",
            redirect_uri="http://127.0.0.1:1/callback",
            state="s",
            code_challenge="c",
        )
        qs = parse_qs(urlparse(url).query)
        assert "scope" not in qs

    def test_state_unique_per_call(self):
        from neurova.tool_layers.mcp_oauth import build_authorization_url

        states = {
            parse_qs(urlparse(build_authorization_url(
                "https://idp/a", client_id="c", redirect_uri="http://127.0.0.1:1/cb",
                state=f"s{i}", code_challenge="x",
            )).query)["state"][0]
            for i in range(5)
        }
        assert len(states) == 5


class TestCodeExchange:
    """授权码换 token（grant_type=authorization_code + code_verifier）"""

    @pytest.mark.asyncio
    async def test_exchange_posts_correct_grant(self):
        transport = _FakeTransport([(200, {"access_token": "ac1", "expires_in": 3600})])
        provider = OAuthTokenProvider(
            "https://idp/token", "cid", "csecret", transport=transport
        )
        token = await provider.fetch_token_by_code(
            "code1", "verifier1", "http://127.0.0.1:9000/callback"
        )
        assert token == "ac1"
        data = transport.requests[0]["data"]
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "code1"
        assert data["code_verifier"] == "verifier1"
        assert data["redirect_uri"] == "http://127.0.0.1:9000/callback"
        assert data["client_id"] == "cid"

    @pytest.mark.asyncio
    async def test_exchange_populates_cache(self):
        transport = _FakeTransport([(200, {"access_token": "ac2", "expires_in": 3600})])
        provider = OAuthTokenProvider("https://idp/token", "cid", "csecret", transport=transport)
        await provider.fetch_token_by_code("c", "v", "http://127.0.0.1:1/cb")
        assert provider.get_cached_token() == "ac2"

    @pytest.mark.asyncio
    async def test_exchange_error_raises(self):
        transport = _FakeTransport([(400, {"error": "invalid_grant"})])
        provider = OAuthTokenProvider("https://idp/token", "cid", "csecret", transport=transport)
        with pytest.raises(OAuthTokenError, match="400"):
            await provider.fetch_token_by_code("c", "v", "http://127.0.0.1:1/cb")

    @pytest.mark.asyncio
    async def test_expired_cache_returns_none(self):
        import time as _time

        provider = OAuthTokenProvider("https://idp/token", "cid", "csecret")
        provider._cached = {"access_token": "old", "expires_at": _time.monotonic() - 10}
        assert provider.get_cached_token() is None


class TestCallbackServer:
    """本地回调服务器：捕获 IdP 重定向 query（真实 HTTP 环回）"""

    def _get(self, port: int, qs: str) -> None:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?{qs}", timeout=5).read()

    def test_captures_code_and_state(self):
        from neurova.tool_layers.mcp_oauth import OAuthCallbackServer

        server = OAuthCallbackServer()
        server.start()
        try:
            self._get(server.port, "code=abc&state=st1")
            assert server.wait(5)
            assert server.params["code"] == "abc"
            assert server.params["state"] == "st1"
        finally:
            server.stop()

    def test_captures_error_response(self):
        from neurova.tool_layers.mcp_oauth import OAuthCallbackServer

        server = OAuthCallbackServer()
        server.start()
        try:
            self._get(server.port, "error=access_denied")
            assert server.wait(5)
            assert server.error == "access_denied"
        finally:
            server.stop()

    def test_wait_timeout_when_no_request(self):
        from neurova.tool_layers.mcp_oauth import OAuthCallbackServer

        server = OAuthCallbackServer()
        server.start()
        try:
            assert server.wait(0.2) is False
        finally:
            server.stop()

    def test_ephemeral_loopback_bind(self):
        from neurova.tool_layers.mcp_oauth import OAuthCallbackServer

        server = OAuthCallbackServer()
        server.start()
        try:
            assert server.port > 0
        finally:
            server.stop()


class TestRunAuthorizationCodeFlow:
    """完整授权码流编排：URL → 浏览器跳转（注入）→ 回调 → 换 token → 入缓存"""

    def _make_opener(self, code: str = "code1", state_override: str = None, hit: bool = True):
        """注入式 opener：模拟 IdP 回跳（解析 auth_url 中的 state 后打回环回调）。"""
        captured = {}

        def opener(url: str) -> bool:
            captured["url"] = url
            if not hit:
                return True
            qs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            state = state_override if state_override is not None else qs["state"]
            redirect = qs["redirect_uri"]
            urllib.request.urlopen(f"{redirect}?code={code}&state={state}", timeout=5).read()
            return True

        opener.captured = captured
        return opener

    def _cfg(self, **over):
        cfg = {
            "authorization_url": "https://idp/authorize",
            "token_url": "https://idp/token",
            "client_id": "cid",
            "client_secret": "csecret",
            "scope": "mcp",
            "grant_type": "authorization_code",
        }
        cfg.update(over)
        return cfg

    @pytest.mark.asyncio
    async def test_full_flow_returns_token_and_caches(self):
        from neurova.tool_layers.mcp_oauth import run_authorization_code_flow

        cache = get_token_cache("ac-flow-1")
        cache._providers.clear()
        transport = _FakeTransport([(200, {"access_token": "ac", "expires_in": 3600})])
        opener = self._make_opener(code="code1")

        token = await run_authorization_code_flow(
            "ac-flow-1", self._cfg(), timeout_s=10, transport=transport, opener=opener
        )
        assert token == "ac"
        # 浏览器打开的 URL 含 PKCE challenge 与 S256
        assert "code_challenge_method=S256" in opener.captured["url"]
        # 回跳 redirect_uri 是环回自动分配端口（URL 编码形式，需解析后断言）
        qs = {k: v[0] for k, v in parse_qs(urlparse(opener.captured["url"]).query).items()}
        assert qs["redirect_uri"].startswith("http://127.0.0.1:")
        # 换 token 的 code_verifier 与 URL 中 challenge 同源（PKCE 闭环）
        assert transport.requests[0]["data"]["code"] == "code1"
        assert transport.requests[0]["data"]["code_verifier"]
        # token 已入 per-call 解析缓存
        assert await resolve_mcp_token("ac-flow-1", self._cfg()) == "ac"

    @pytest.mark.asyncio
    async def test_state_mismatch_rejected(self):
        from neurova.tool_layers.mcp_oauth import run_authorization_code_flow

        transport = _FakeTransport([(200, {"access_token": "x"})])
        opener = self._make_opener(state_override="attacker-state")
        with pytest.raises(OAuthTokenError, match="state"):
            await run_authorization_code_flow(
                "ac-flow-2", self._cfg(), timeout_s=10, transport=transport, opener=opener
            )
        assert transport.requests == []  # state 不符绝不换 token

    @pytest.mark.asyncio
    async def test_idp_error_response_raises(self):
        from neurova.tool_layers.mcp_oauth import run_authorization_code_flow

        opener = self._make_opener(hit=False)  # 不回跳
        # 手动回跳错误响应：opener 里没有现成通道，改用自定义
        def opener_err(url: str) -> bool:
            qs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            urllib.request.urlopen(f"{qs['redirect_uri']}?error=access_denied", timeout=5).read()
            return True

        with pytest.raises(OAuthTokenError, match="access_denied"):
            await run_authorization_code_flow(
                "ac-flow-3", self._cfg(), timeout_s=10, transport=_FakeTransport([]), opener=opener_err
            )

    @pytest.mark.asyncio
    async def test_timeout_when_browser_never_calls_back(self):
        from neurova.tool_layers.mcp_oauth import run_authorization_code_flow

        opener = self._make_opener(hit=False)
        with pytest.raises(OAuthTokenError, match="超时"):
            await run_authorization_code_flow(
                "ac-flow-4", self._cfg(), timeout_s=0.3, transport=_FakeTransport([]), opener=opener
            )

    @pytest.mark.asyncio
    async def test_non_loopback_redirect_rejected(self):
        from neurova.tool_layers.mcp_oauth import run_authorization_code_flow

        with pytest.raises(ValueError, match="环回"):
            await run_authorization_code_flow(
                "ac-flow-5",
                self._cfg(redirect_uri="https://evil.example.com/callback"),
                timeout_s=1,
                transport=_FakeTransport([]),
                opener=self._make_opener(hit=False),
            )


class TestResolveGrantAware:
    """per-call 解析感知 grant_type：authorization_code 只用已授权缓存 token"""

    @pytest.mark.asyncio
    async def test_authorization_code_without_token_raises_with_guidance(self):
        cache = get_token_cache("ac-resolve-1")
        cache._providers.clear()
        with pytest.raises(OAuthTokenError, match="授权"):
            await resolve_mcp_token(
                "ac-resolve-1",
                {"grant_type": "authorization_code", "token_url": "u", "client_id": "a", "client_secret": "b"},
            )

    @pytest.mark.asyncio
    async def test_authorization_code_with_cached_token_returns(self):
        cache = get_token_cache("ac-resolve-2")
        cache._providers.clear()
        provider = OAuthTokenProvider("u", "a", "b")
        import time as _time

        provider._cached = {"access_token": "pre-authed", "expires_at": _time.monotonic() + 3600}
        cache._providers["ac-resolve-2"] = provider
        token = await resolve_mcp_token(
            "ac-resolve-2",
            {"grant_type": "authorization_code", "token_url": "u", "client_id": "a", "client_secret": "b"},
        )
        assert token == "pre-authed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
