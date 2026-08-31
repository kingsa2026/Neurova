# -*- coding: utf-8 -*-
"""
P3-d MCP OAuth 授权码流 API 端点测试

端点：POST /v1/tool-layers/mcp-servers/{server_id}/oauth/authorize
语义：从 SharedConfigManager 读 config.oauth，要求 grant_type=authorization_code，
后端经 webbrowser.open 打开浏览器（本机应用=用户浏览器），等待环回回调换 token
并入 per-call 缓存；未认证 401（路由级依赖）、server 不存在 404、配置不符 400。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_p3d_oauth_endpoint")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_p3d_oauth_endpoint")

import json
import urllib.request
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import tool_layers

BASE = "/v1/tool-layers"

OAUTH_CFG = {
    "authorization_url": "https://idp.example.com/authorize",
    "token_url": "https://idp.example.com/token",
    "client_id": "cid",
    "client_secret": "csecret",
    "scope": "mcp",
    "grant_type": "authorization_code",
}


def _oauth_server_entry(oauth=OAUTH_CFG):
    return {
        "id": "remote-ac",
        "name": "Remote AC",
        "transport": "http",
        "url": "https://remote.example.com/mcp",
        "enabled": True,
        "config": {"oauth": oauth} if oauth is not None else {},
    }


class FakeManager:
    def __init__(self, entries):
        self._entries = list(entries)

    def get_mcp_server(self, sid):
        for e in self._entries:
            if e.get("id") == sid:
                return e
        return None

    def list_mcp_servers(self):
        return list(self._entries)


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(tool_layers.router, prefix=BASE)
    yield app


def _authed_client(app):
    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1",
        "username": "user1",
        "role": "user",
        "neuser_id": "ne1",
    }
    return TestClient(app)


@pytest.fixture
def isolated_env(monkeypatch):
    def _install(entries):
        monkeypatch.setattr(
            "neurova.shared_config.get_shared_config_manager",
            lambda: FakeManager(entries),
        )

    return _install


def _fake_token_endpoint(monkeypatch, token="ep-token"):
    """令 token 换取走假 httpx：返回固定 access_token，并记录请求"""

    class FakeResp:
        status_code = 200
        text = json.dumps({"access_token": token, "expires_in": 3600})

        def json(self):
            return {"access_token": token, "expires_in": 3600}

    calls = []

    async def fake_post(self, url, data=None, headers=None):
        calls.append({"url": url, "data": data})
        return FakeResp()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return calls


def _idp_opener(code="code-1"):
    """模拟 IdP 回跳：从 auth_url 提取 state，打回环回调"""

    def opener(url: str) -> bool:
        qs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        redirect = qs["redirect_uri"]
        urllib.request.urlopen(
            f"{redirect}?code={code}&state={qs['state']}", timeout=5
        ).read()
        return True

    return opener


class TestOAuthAuthorizeEndpoint:
    def test_unauthenticated_401(self, app, isolated_env):
        with TestClient(app) as client:  # 不覆盖鉴权依赖
            isolated_env([_oauth_server_entry()])
            resp = client.post(f"{BASE}/mcp-servers/remote-ac/oauth/authorize")
            assert resp.status_code == 401

    def test_unknown_server_404(self, app, isolated_env):
        client = _authed_client(app)
        isolated_env([])
        resp = client.post(f"{BASE}/mcp-servers/nope/oauth/authorize")
        assert resp.status_code == 404

    def test_missing_oauth_config_400(self, app, isolated_env):
        client = _authed_client(app)
        isolated_env([_oauth_server_entry(oauth=None)])
        resp = client.post(f"{BASE}/mcp-servers/remote-ac/oauth/authorize")
        assert resp.status_code == 400
        assert "authorization_code" in resp.json()["detail"]

    def test_client_credentials_grant_rejected_400(self, app, isolated_env):
        client = _authed_client(app)
        isolated_env([_oauth_server_entry(oauth={"token_url": "u", "client_id": "a"})])
        resp = client.post(f"{BASE}/mcp-servers/remote-ac/oauth/authorize")
        assert resp.status_code == 400

    def test_full_flow_authorized_and_cached(self, app, isolated_env, monkeypatch):
        client = _authed_client(app)
        isolated_env([_oauth_server_entry()])
        monkeypatch.setattr("webbrowser.open", _idp_opener(code="code-1"))
        token_calls = _fake_token_endpoint(monkeypatch, token="ep-token")

        resp = client.post(f"{BASE}/mcp-servers/remote-ac/oauth/authorize")

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "authorized"
        # 换 token 走授权码 grant
        assert token_calls[0]["data"]["grant_type"] == "authorization_code"
        assert token_calls[0]["data"]["code"] == "code-1"
        # token 已入 per-call 解析缓存
        import asyncio

        from neurova.tool_layers.mcp_oauth import resolve_mcp_token

        token = asyncio.run(resolve_mcp_token("remote-ac", OAUTH_CFG))
        assert token == "ep-token"

    def test_timeout_returns_400_with_detail(self, app, isolated_env, monkeypatch):
        client = _authed_client(app)
        isolated_env([_oauth_server_entry()])
        monkeypatch.setattr("webbrowser.open", lambda url: True)  # 打开但从不回跳

        resp = client.post(
            f"{BASE}/mcp-servers/remote-ac/oauth/authorize", json={"timeout_s": 0.3}
        )
        assert resp.status_code == 400
        assert "超时" in resp.json()["detail"]

    def test_state_mismatch_rejected_no_token_call(self, app, isolated_env, monkeypatch):
        client = _authed_client(app)
        isolated_env([_oauth_server_entry()])

        def evil_opener(url: str) -> bool:
            qs = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            urllib.request.urlopen(
                f"{qs['redirect_uri']}?code=x&state=attacker", timeout=5
            ).read()
            return True

        monkeypatch.setattr("webbrowser.open", evil_opener)
        token_calls = _fake_token_endpoint(monkeypatch)

        resp = client.post(f"{BASE}/mcp-servers/remote-ac/oauth/authorize")
        assert resp.status_code == 400
        assert "state" in resp.json()["detail"]
        assert token_calls == []  # CSRF：不符绝不换 token


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
