"""WebhookPage 保存不持久 + /test 假投递修复回归（2026-09-12 空数据页面排查）。

根因:
1. _webhooks/_deliveries 为进程内 dict——WebhookPage 新建的 webhook 重启即空
   （"保存项未真实落盘"）；
2. POST /{id}/test 不发送任何 HTTP 请求，直接写死 status=delivered/response_code=200
   （假成功，违反修复教义#1/#3）。

修复契约:
1. webhook 与投递记录落 data/webhooks.json，启动自动加载，重启可回读；
2. /test 真实 POST url（httpx，超时/拒连/非 2xx 均如实记 failed 与真实响应码）。
"""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_webhooks_0123456789")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import webhooks as WH

MOCK_USER = {"user_id": "u1", "username": "u1", "role": "admin"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(WH, "_STORE_FILE", str(tmp_path / "webhooks.json"))
    WH._webhooks.clear()
    WH._deliveries.clear()
    app = FastAPI()
    app.include_router(WH.router, prefix="/api/v1/webhooks")
    app.dependency_overrides[get_current_user] = lambda: MOCK_USER
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _restart(client, tmp_path):
    """模拟进程重启：清空内存，从 JSON 文件重载。"""
    WH._webhooks.clear()
    WH._deliveries.clear()
    WH._load_store()


class TestPersistence:
    def test_created_webhook_written_to_disk(self, client, tmp_path):
        r = client.post("/api/v1/webhooks", json={"name": "ops", "url": "http://127.0.0.1:9/hook", "events": ["chat"]})
        assert r.status_code == 200
        f = tmp_path / "webhooks.json"
        assert f.exists(), "webhook 未落盘"
        saved = json.loads(f.read_text(encoding="utf-8"))
        assert any(w["name"] == "ops" for w in saved["webhooks"].values())

    def test_survives_restart(self, client, tmp_path):
        r = client.post("/api/v1/webhooks", json={"name": "ops", "url": "http://x/y", "events": ["a"]})
        wh_id = r.json()["webhook_id"]
        _restart(client, tmp_path)
        items = client.get("/api/v1/webhooks").json()
        assert [w["webhook_id"] for w in items] == [wh_id]
        assert client.get(f"/api/v1/webhooks/{wh_id}").status_code == 200

    def test_update_and_delete_persist(self, client, tmp_path):
        wh_id = client.post("/api/v1/webhooks", json={"name": "n1", "url": "u"}).json()["webhook_id"]
        client.put(f"/api/v1/webhooks/{wh_id}", json={"name": "n2"})
        client.post("/api/v1/webhooks", json={"name": "drop", "url": "u2"}).json()
        _wh2 = client.get("/api/v1/webhooks").json()
        # 删除其一
        other = [w["webhook_id"] for w in _wh2 if w["webhook_id"] != wh_id][0]
        client.delete(f"/api/v1/webhooks/{other}")
        _restart(client, tmp_path)
        items = client.get("/api/v1/webhooks").json()
        names = {w["webhook_id"]: w["name"] for w in items}
        assert names.get(wh_id) == "n2"
        assert other not in names


class TestHonestDelivery:
    def test_test_endpoint_reports_real_failure(self, client):
        """不可达 URL（端口 9 拒连）必须记 failed，不得谎报 delivered/200。"""
        wh_id = client.post("/api/v1/webhooks", json={
            "name": "dead", "url": "http://127.0.0.1:9/hook",
        }).json()["webhook_id"]
        r = client.post(f"/api/v1/webhooks/{wh_id}/test", json={"event_type": "ping"})
        assert r.status_code == 200, r.text
        did = r.json()["data"]["delivery_id"]
        deliv = next(d for d in client.get(f"/api/v1/webhooks/{wh_id}/deliveries").json()
                     if d["delivery_id"] == did)
        assert deliv["status"] == "failed"
        # 真实响应（含环境代理回传的 5xx）必须原样记录，绝不谎报 2xx
        assert not (200 <= (deliv["response_code"] or 0) < 300)
