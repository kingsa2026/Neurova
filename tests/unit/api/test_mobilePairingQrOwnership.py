# -*- coding: utf-8 -*-
"""配对二维码读取验属主（API-08，2026-11-25 全仓审计·批次 C）。

`GET /mobile/pairing/qrcode/{code}` 此前只挂 `Depends(_get_current_user_id)`
（仅验登录、不取属主）：6 位配对码是本仓自陈的**唯一认证凭据**，任何登录用户
拿到（枚举/泄露）他人的 code 就能读出那张二维码——图里是 `neurova://pair?ref=…`
的一次性配对引用，等于替他人把配对材料取走。

判据与同文件既有属主口径同源（`cancel_pairing` / `get_pairing_status` 的
"非属主与码不存在同形 404"——不向非属主确认存在性）：
- 属主本人：200 + PNG（反向控制，门不得误伤自己人）；
- 他人登录：404（与码不存在同形）；
- 码不存在：404（同形，不给枚举者区分线索）。
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_qr_owner_0123456789")

from neurova.api.endpoints import mobile_pairing as MP

OWNER = "kai"
STRANGER = "mallory"
PREFIX = "/api/v1/mobile"


@pytest.fixture()
def app_client():
    """真挂载生产路由（与前缀注册表同形），身份用 dependency_overrides 换人。"""
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()
    app = FastAPI()
    app.include_router(MP.router, prefix=PREFIX)
    app.dependency_overrides[MP._get_current_user_id] = lambda: OWNER
    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as c:
        yield c, app
    app.dependency_overrides.clear()
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()


def _as(app: FastAPI, user_id: str) -> None:
    app.dependency_overrides[MP._get_current_user_id] = lambda: user_id


def _generate(c: TestClient) -> dict:
    r = c.post(f"{PREFIX}/pairing/generate",
               json={"device_name": "probe", "device_type": "mobile"})
    assert r.status_code == 200, r.text
    return r.json()


class TestQrReadIsOwnerOnly:
    def test_strangerCannotReadOthersQrcode(self, app_client):
        """非属主读他人配对二维码必须被拒（API-08 主判据）。"""
        c, app = app_client
        body = _generate(c)
        _as(app, STRANGER)

        r = c.get(f"{PREFIX}/pairing/qrcode/{body['code']}")

        assert r.status_code == 404, (
            f"非属主 {STRANGER} 读到了 {OWNER} 的配对二维码：{r.status_code} {r.text[:120]}")
        assert not r.content.startswith(b"\x89PNG"), "非属主竟拿到了二维码图片本体"

    def test_unknownCodeStays404SameShape(self, app_client):
        """码不存在仍是 404——非属主与不存在同形，枚举者分不出真假。"""
        c, app = app_client
        _as(app, STRANGER)

        r = c.get(f"{PREFIX}/pairing/qrcode/000000")

        assert r.status_code == 404
        assert "not found" in r.text.lower()

    def test_ownerStillReadsOwnQrcode(self, app_client):
        """反向控制：属主本人照常拿到真 PNG（门不得一刀切）。"""
        c, app = app_client
        body = _generate(c)

        r = c.get(f"{PREFIX}/pairing/qrcode/{body['code']}")

        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("image/png")
        assert r.content[:4] == b"\x89PNG", "属主拿到的应是真二维码图"

    def test_unauthenticatedIsStill401(self, app_client):
        """未登录照旧 401：属主门加在登录之后，不放宽原有认证面。"""
        c, app = app_client
        body = _generate(c)
        app.dependency_overrides.pop(MP._get_current_user_id, None)
        # 依赖被移除后恢复真实依赖：给一个不含凭据的客户端直接打
        from fastapi import HTTPException

        async def _realDependency():
            raise HTTPException(status_code=401, detail="Missing authorization")

        app.dependency_overrides[MP._get_current_user_id] = _realDependency

        r = c.get(f"{PREFIX}/pairing/qrcode/{body['code']}")

        assert r.status_code == 401, f"未登录却没被 401 拦下：{r.status_code} {r.text[:120]}"
