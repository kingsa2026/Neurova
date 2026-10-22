# -*- coding: utf-8 -*-
"""通用渠道二维码 REST 端点契约。

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
    # 归属门（Issue #290 追问②）先于路由内的一切判定：本文件测的是路由解析与
    # 扫码契约，故用已授权身份；越权形态（403 先于存在性）由
    # tests/unit/api/test_channel_agent_access_290.py 咬合。
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u", "username": "u", "role": "admin"}
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


def test_legacy_wechat_ilink_routes_removed(client):
    """旧 /wechat/ilink/qrcode* 端点已随两套扫码合并而删除（防复活钉）。

    取数换口径单源 `tests/route_table.registeredPaths`。此前这格写
    `[getattr(r, "path", "") for r in client.app.routes]`：现行 FastAPI 把 include 落成
    惰性包装 `_IncludedRouter`，那一形在装配后的 app 上取不到叶子路径（主装配 app 实测
    只吐 7 条挂载点、单源同口径 877 条叶子路径）。于是这枚"防复活钉"**从来没咬过任何东西**——
    把那两个端点加回来它也绿。缺席型断言在空集上恒真，是比假红更坏的一种失明（§6-401）。
    """
    from tests.route_table import registeredPaths

    paths = registeredPaths(client.app)
    # 分母自检用**正控**而不是拍一个数量级：本档的 app 只挂 `channel_config` 一个 router，
    # 真在表上的是那条通用两段式路由——它在，就说明取数看得到叶子路径，
    # 下面两条「不存在」断言才有意义（不在这里写 `> 100` 那种凭空的数，
    # 本档第一版就因为它只取到 20 条而把守卫自己弄红了）。
    assert "/api/v1/channel-configs/{channel_type}/qrcode" in paths, (
        f"口径没读到叶子路径（现取 {len(paths)} 条）——空集上「不存在」恒真，本格失去意义"
    )
    assert not any(p.endswith("/channel-configs/wechat/ilink/qrcode") for p in paths)
    assert not any(p.endswith("/channel-configs/wechat/ilink/qrcode/status") for p in paths)
