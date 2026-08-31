"""
P2-6 MCP OAuth 测试（client_credentials + PKCE + per-call 解析）
"""

import asyncio
import json

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
