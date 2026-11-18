# -*- coding: utf-8 -*-
"""Webhook 管理面属主门（fullrepo 审计 2026-11-18 高项）。

红灯依据：router 级仅 `get_current_user`（认证非鉴权），创建硬编码
`user_id="default"`，list/get/update/delete/test/deliveries 六端点均无
属主过滤——任意登录用户可读/改/删/触发**他人**的 webhook 与投递记录；
`/test` 还能把他人 webhook 的 url 改掉后借服务端 POST 外送任意 payload。

裁定与先例：属主判据取请求身份字典的 `user_id`（webhook 是配置面 REST，
§3 身份通道 ContextVar 在这些路由无写点）；空属主（存量 `"default"` 行）
按 2026-11-18「空属主判给管理员」裁定归 admin；非属主一律 404（不泄露
存在性，与 artifacts 属主门同口径）；admin 全量。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import webhooks


def _identity(user_id: str, role: str = "user") -> dict:
    return {"user_id": user_id, "username": user_id, "role": role,
            "neuser_id": user_id, "tenant_id": "default"}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """隔离 webhook 存储：dict 清空重种、落盘文件指到 tmp，绝不碰真实 data/。"""
    monkeypatch.setattr(webhooks, "_STORE_FILE", tmp_path / "webhooks.json")
    webhooks._webhooks.clear()
    webhooks._deliveries.clear()
    yield webhooks._webhooks
    webhooks._webhooks.clear()
    webhooks._deliveries.clear()


def _client(user_id: str, role: str = "user") -> TestClient:
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(webhooks.router, prefix="/v1/webhooks")
    app.dependency_overrides[get_current_user] = lambda: _identity(user_id, role)
    return TestClient(app)


def _seed(wh_id: str, user_id: str, url: str = "https://example.com/hook") -> None:
    webhooks._webhooks[wh_id] = {
        "webhook_id": wh_id, "name": f"wh-{wh_id}", "url": url,
        "events": [], "enabled": True, "user_id": user_id,
        "created_at": 1.0, "updated_at": 1.0,
    }


class TestCreateStampsRequesterAsOwner:
    def test_create_lands_requester_user_id(self, store):
        resp = _client("alice").post("/v1/webhooks", json={
            "name": "n", "url": "https://example.com/hook", "events": []})
        assert resp.status_code == 200, resp.text
        assert resp.json()["user_id"] == "alice", (
            "创建行属主必须是发起者本人，而不是硬编码 default"
        )


class TestListIsOwnerScoped:
    def test_list_hides_other_users_webhooks(self, store):
        _seed("a1", "alice")
        _seed("b1", "bob")
        got = {w["webhook_id"] for w in _client("alice").get("/v1/webhooks").json()}
        assert got == {"a1"}, f"alice 只能看见自己的 webhook，实际 {got}"

    def test_admin_sees_all_including_legacy_default_rows(self, store):
        _seed("a1", "alice")
        _seed("legacy", "default")
        got = {w["webhook_id"] for w in _client("root", role="admin").get("/v1/webhooks").json()}
        assert got == {"a1", "legacy"}, "admin 全量可见（含存量 default 行）"

    def test_legacy_default_row_hidden_from_normal_users(self, store):
        _seed("legacy", "default")
        resp = _client("alice").get("/v1/webhooks/legacy")
        assert resp.status_code == 404, "存量无主行按裁定归 admin，普通用户不可见"


class TestSingleItemIsOwnerGated:
    def test_get_other_users_webhook_is_404(self, store):
        _seed("a1", "alice")
        assert _client("bob").get("/v1/webhooks/a1").status_code == 404
        assert _client("alice").get("/v1/webhooks/a1").status_code == 200

    def test_update_other_users_webhook_is_404(self, store):
        _seed("a1", "alice")
        resp = _client("bob").put("/v1/webhooks/a1", json={"name": "hijacked"})
        assert resp.status_code == 404
        assert store["a1"]["name"] == "wh-a1", "他人 webhook 不许被改"

    def test_delete_other_users_webhook_is_404(self, store):
        _seed("a1", "alice")
        assert _client("bob").delete("/v1/webhooks/a1").status_code == 404
        assert "a1" in store, "他人 webhook 不许被删"

    def test_owner_full_lifecycle_still_works(self, store):
        """正向对照：属主本人创建/读/改/删全链不受影响（防门修成全员不可用）。"""
        c = _client("alice")
        made = c.post("/v1/webhooks", json={
            "name": "n", "url": "https://example.com/hook", "events": []}).json()
        wid = made["webhook_id"]
        assert c.get(f"/v1/webhooks/{wid}").status_code == 200
        assert c.put(f"/v1/webhooks/{wid}", json={"name": "renamed"}).json()["name"] == "renamed"
        assert c.delete(f"/v1/webhooks/{wid}").status_code == 200
        assert wid not in store

    def test_admin_can_manage_others_webhook(self, store):
        _seed("a1", "alice")
        assert _client("root", role="admin").delete("/v1/webhooks/a1").status_code == 200
        assert "a1" not in store


class TestTestEndpointIsOwnerGated:
    def test_test_other_users_webhook_is_404_and_sends_nothing(self, store, monkeypatch):
        _seed("a1", "alice")
        sent: list = []

        class _FakeClient:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, **kwargs):
                sent.append(url)

                class _R:
                    status_code = 200
                return _R()

        monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
        resp = _client("bob").post("/v1/webhooks/a1/test", json={"event_type": "test"})
        assert resp.status_code == 404, "非属主不得借服务端外送"
        assert sent == [], "未过属主门就不得发起服务端 POST"
        assert webhooks._deliveries == {}, "未过属主门就不得落投递记录"

    def test_deliveries_of_other_users_webhook_are_404(self, store):
        _seed("a1", "alice")
        webhooks._deliveries["d1"] = {"delivery_id": "d1", "webhook_id": "a1",
                                      "event_type": "test", "status": "failed",
                                      "response_code": None, "attempts": 1,
                                      "created_at": 1.0}
        assert _client("bob").get("/v1/webhooks/a1/deliveries").status_code == 404
        assert _client("alice").get("/v1/webhooks/a1/deliveries").status_code == 200


class TestUrlGateUnchanged:
    def test_internal_url_still_rejected_on_create(self, store):
        resp = _client("alice").post("/v1/webhooks", json={
            "name": "n", "url": "http://169.254.169.254/latest", "events": []})
        assert resp.status_code == 400, "属主门不得放松 SSRF 闸"
