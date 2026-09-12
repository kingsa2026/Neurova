# -*- coding: utf-8 -*-
"""通用渠道二维码 REST 端点契约（对齐 QwenPaw GET /config/channels/{ch}/qrcode 两段式）。

端点（channel_config router, prefix=/channel-configs）：
- GET /{channel}/qrcode           → {qrcode_img(base64 PNG), poll_token}
- GET /{channel}/qrcode/status?token= → {status, credentials}
未注册 handler 的渠道 → 404（诚实，不假二维码）。
"""

from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user  # 路由依赖的是 auth 版（非 deps 版）
from neurova.api.endpoints import channel_config as CC
from neurova.channels import qrcode_auth


class _FakeHandler:
    async def fetch_qrcode(self, request):
        return qrcode_auth.QRCodeResult(
            scan_url="https://example.com/scan?a=1", poll_token="tok-1"
        )

    async def poll_status(self, token, request):
        return qrcode_auth.PollResult(
            status="success", credentials={"app_id": "cli_a", "app_secret": "sec_b"}
        )


@pytest.fixture()
def client(monkeypatch):
    app = FastAPI()
    app.include_router(CC.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {"sub": "u", "username": "u"}
    monkeypatch.setitem(qrcode_auth.QRCODE_AUTH_HANDLERS, "feishu", _FakeHandler())
    return TestClient(app)


def test_generic_qrcode_endpoint(client):
    r = client.get("/api/v1/channel-configs/feishu/qrcode")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["poll_token"] == "tok-1"
    raw = base64.b64decode(data["qrcode_img"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


def test_generic_qrcode_status_endpoint(client):
    r = client.get("/api/v1/channel-configs/feishu/qrcode/status", params={"token": "tok-1"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "success"
    assert data["credentials"]["app_id"] == "cli_a"


def test_qrcode_status_requires_token(client):
    r = client.get("/api/v1/channel-configs/feishu/qrcode/status")
    assert r.status_code == 400


def test_unknown_channel_404(client):
    r = client.get("/api/v1/channel-configs/nonexistent/qrcode")
    assert r.status_code == 404


def test_legacy_single_segment_routes_not_shadowed(client, monkeypatch):
    """新增两段式路由不得劫持 /schemas 与 /{channel_type} 一段路由。"""
    r = client.get("/api/v1/channel-configs/schemas")
    assert r.status_code == 200
    r = client.get("/api/v1/channel-configs/no-such-channel")
    assert r.status_code == 404


def test_legacy_wechat_ilink_routes_still_present(client):
    """并行会话的 F-3 旧端点保留兼容（POST 生成 + GET 轮询）。"""
    paths = [getattr(r, "path", "") for r in client.app.routes]
    assert any(p.endswith("/channel-configs/wechat/ilink/qrcode") for p in paths)
    assert any(p.endswith("/channel-configs/wechat/ilink/qrcode/status") for p in paths)
