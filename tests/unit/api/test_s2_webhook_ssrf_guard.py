"""S2 安全批：webhook 三入口 SSRF 闸（审计 2026-11-16 P1-5）。

webhook.url 由 create/update 任意指定，test 端点会向它发起服务端 POST——
不过 url_guard（`neurova/security/url_guard.py` 单源）即构成内网探测预言机。
三处入口（create / update / test）必须统一过同一份校验。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_webhook_0123456789")

from neurova.api.auth import get_current_user  # noqa: E402
from neurova.api.endpoints import webhooks as WH  # noqa: E402

USER = {"user_id": "whUser", "username": "whUser", "role": "user"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(WH, "_STORE_FILE", tmp_path / "webhooks.json")
    WH._webhooks.clear()
    WH._deliveries.clear()
    app = FastAPI()
    app.include_router(WH.router, prefix="/api/v1/webhooks")
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    WH._webhooks.clear()
    WH._deliveries.clear()


def _create(c, url):
    return c.post(
        "/api/v1/webhooks",
        json={"name": "w", "url": url, "events": ["test"]},
    )


class TestWebhookSsrfGuard:
    def test_create_rejects_link_local_metadata_ip(self, client):
        r = _create(client, "http://169.254.169.254/latest/meta-data")
        assert r.status_code == 400, f"链路本地元数据地址应 400，实得 {r.status_code}: {r.text}"

    def test_create_rejects_localhost(self, client):
        for url in ("http://localhost/hook", "http://127.0.0.1/hook"):
            r = _create(client, url)
            assert r.status_code == 400, f"{url} 应 400，实得 {r.status_code}"

    def test_create_rejects_private_net(self, client):
        r = _create(client, "http://192.168.1.10/hook")
        assert r.status_code == 400, f"私网地址应 400，实得 {r.status_code}"

    def test_create_accepts_public_ip_literal(self, client):
        # 公网 IP 字面量不触发 DNS 解析，测试不依赖外网
        r = _create(client, "http://1.2.3.4/hook")
        assert r.status_code == 200, f"公网地址应放行，实得 {r.status_code}: {r.text}"

    def test_update_rejects_private_url(self, client):
        r = _create(client, "http://1.2.3.4/hook")
        assert r.status_code == 200, r.text
        wh_id = r.json()["webhook_id"]
        r2 = client.put(
            f"/api/v1/webhooks/{wh_id}", json={"url": "http://10.0.0.5/hook"}
        )
        assert r2.status_code == 400, f"update 改成私网应 400，实得 {r2.status_code}: {r2.text}"

    def test_test_endpoint_revalidates_stored_url(self, client):
        """历史存量脏数据（入库早于闸）在 test 时也要被拦：不向内网发服务端 POST。"""
        r = _create(client, "http://1.2.3.4/hook")
        wh_id = r.json()["webhook_id"]
        # 模拟闸上线前的存量行
        WH._webhooks[wh_id]["url"] = "http://169.254.169.254/latest/meta-data"
        r2 = client.post(f"/api/v1/webhooks/{wh_id}/test", json={"event_type": "test"})
        assert r2.status_code == 400, (
            f"test 端点对内网 url 应 400 拒发，实得 {r2.status_code}: {r2.text}"
        )
