"""
站内通知 API 契约统一 + JSON 持久化 + 通知门面 测试（2026-09-01 TDD）

背景：原实现前端拿不到数据（裸数组 vs 信封）、字段名错位
（notification_id/notification_type vs id/type）、方法错位
（前端 POST vs 后端 PUT），铃铛未读数硬编码 0。

契约（对齐前端 api/modules/notifications.ts）：
1. GET /notifications → {code:0, data:{items, total}}；
   item 字段 id/type/title/message/read/created_at(ISO)/data
2. GET /unread-count → data.total
3. POST /{id}/read、POST /mark-all-read 可用（PUT 保留兼容）
4. 通知 JSON 文件持久化（重启不丢，NEUROVA_NOTIFICATIONS_PATH 隔离）
5. 门面 notify_user / notify_admins / notify_all_users（admin 枚举自
   enhanced_users_api._users_store，无 admin 兜底 default）
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import notifications as notif_module

PREFIX = "/v1/notifications"

USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
ADMIN = {"user_id": "a9", "username": "admin", "role": "admin", "neuser_id": "a9"}


@pytest.fixture
def api(tmp_path, monkeypatch):
    """隔离通知存储路径 + 重置单例；override 当前用户为 u1。"""
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    notif_module.reset_notification_manager()
    app = FastAPI()
    app.include_router(notif_module.router, prefix=PREFIX)
    app.dependency_overrides[notif_module.get_current_user_or_default] = lambda: dict(USER)
    client = TestClient(app)
    return client, app, tmp_path


def _seed_notification(user_id="u1", title="t1", ntype="info"):
    return notif_module.get_notification_manager().add_notification(
        user_id=user_id, title=title, message="m", notification_type=ntype, data={"k": 1}
    )


class TestContract:
    def test_list_uses_envelope_and_frontend_field_names(self, api):
        client, _app, _tmp = api
        n = _seed_notification(ntype="kb_review")
        resp = client.get(PREFIX)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        items = body["data"]["items"]
        assert body["data"]["total"] == 1
        assert items[0]["id"] == n.notification_id, "前端类型是 id，不是 notification_id"
        assert items[0]["type"] == "kb_review", "前端类型是 type，不是 notification_type"
        assert isinstance(items[0]["created_at"], str), "created_at 须为 ISO 字符串"
        assert items[0]["read"] is False
        assert items[0]["data"] == {"k": 1}

    def test_unread_count_returns_total(self, api):
        client, _app, _tmp = api
        _seed_notification()
        _seed_notification(title="t2")
        body = client.get(PREFIX + "/unread-count").json()
        assert body["code"] == 0
        assert body["data"]["total"] == 2, "store 期望 data.total"

    def test_post_mark_read_and_mark_all(self, api):
        client, _app, _tmp = api
        n = _seed_notification()
        _seed_notification(title="t2")
        assert client.post(PREFIX + f"/{n.notification_id}/read").status_code == 200, (
            "前端用 POST 标记已读"
        )
        assert client.post(PREFIX + "/mark-all-read").status_code == 200
        assert client.get(PREFIX + "/unread-count").json()["data"]["total"] == 0

    def test_put_legacy_still_works(self, api):
        client, _app, _tmp = api
        n = _seed_notification()
        assert client.put(PREFIX + f"/{n.notification_id}/read").status_code == 200
        assert client.put(PREFIX + "/read-all").status_code == 200

    def test_delete_returns_envelope(self, api):
        client, _app, _tmp = api
        n = _seed_notification()
        resp = client.delete(PREFIX + f"/{n.notification_id}")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0


class TestPersistence:
    def test_notifications_survive_manager_restart(self, api, tmp_path, monkeypatch):
        client, _app, tmp = api
        path = tmp / "notifications.json"
        n = _seed_notification()
        # 模拟重启：单例重置后从同一文件加载
        notif_module.reset_notification_manager()
        fresh = notif_module.get_notification_manager()
        assert fresh.get_unread_count("u1") == 1
        assert fresh.get_notification(n.notification_id) is not None

    def test_singleton_uses_env_path(self, api, tmp_path):
        client, _app, tmp = api
        _seed_notification()
        assert (tmp / "notifications.json").exists(), "单例须落盘到 NEUROVA_NOTIFICATIONS_PATH"


class TestFacade:
    def test_notify_user_and_admins(self, api, monkeypatch):
        client, app, tmp = api
        # 枚举管理员来源：_users_store
        import neurova.api.endpoints.enhanced_users_api as users_api

        monkeypatch.setattr(
            users_api,
            "_users_store",
            {"a9": {"role": "admin", "username": "admin"}, "u1": {"role": "user", "username": "alice"}},
        )
        notif_module.notify_user("u1", "给用户", "hello", "info")
        notif_module.notify_admins("给管理员", "review please", "kb_review", data={"x": 1})

        items = client.get(PREFIX).json()["data"]["items"]
        titles = {i["title"] for i in items}
        assert "给用户" in titles
        mgr = notif_module.get_notification_manager()
        admin_titles = {n.title for n in mgr.get_user_notifications("a9", limit=50)}
        assert "给管理员" in admin_titles, "管理员应收到通知"

    def test_notify_admins_falls_back_to_default(self, api, monkeypatch):
        import neurova.api.endpoints.enhanced_users_api as users_api

        monkeypatch.setattr(users_api, "_users_store", {}, raising=False)
        notif_module.notify_admins("无admin兜底", "m", "info")
        mgr = notif_module.get_notification_manager()
        assert mgr.get_unread_count("default") == 1, "无注册管理员时兜底 default（单机模式）"
