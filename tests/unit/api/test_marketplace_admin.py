"""
市场管理端点鉴权+CRUD+通知 测试（2026-08-31）

契约:
1. 读端点(GET /skills、/installed、/skills/{id}) 未认证 401;
2. 用户安装/卸载端点 登录可操作、未认证 401;
3. 管理端点(POST/PUT/DELETE /skills、/skills/{id}) 未认证 401、普通用户 403、admin 200;
4. PUT 版本变更 -> 站内通知(market_update)产生; 同版本更新不通知;
5. CRUD 落盘持久化(隔离 catalog 目录)。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import marketplace, notifications
from neurova.api.deps import get_current_user
from neurova.skills.market_store import reset_market_store

MOCK_USER = {"user_id": "u1", "username": "user1", "role": "user"}
MOCK_ADMIN = {"user_id": "admin1", "username": "adminuser", "role": "admin"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    """隔离 catalog + 通知管理器, 只挂 marketplace 路由"""
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    reset_market_store()
    from neurova.api.endpoints.notifications import reset_notification_manager

    reset_notification_manager()
    a = FastAPI()
    a.include_router(marketplace.router, prefix="/api/v1/marketplace")
    with TestClient(a, raise_server_exceptions=False) as c:
        yield a, c
    reset_market_store()
    reset_notification_manager()


def _auth(c, role):
    user = MOCK_ADMIN if role == "admin" else MOCK_USER
    c.app.dependency_overrides[get_current_user] = lambda: user
    return c


class TestMarketplaceAdminCrud:
    def test_create_update_delete_roundtrip(self, app):
        a, c = app
        _auth(c, "admin")
        # 上架
        r = c.post("/api/v1/marketplace/skills", json={
            "skill_id": "translate-plus", "name": "Translate Plus",
            "description": "多语言翻译", "version": "1.0.0", "category": "utility",
        })
        assert r.status_code == 200, r.text[:160]
        # 重复上架 409
        r = c.post("/api/v1/marketplace/skills", json={
            "skill_id": "translate-plus", "name": "Translate Plus",
        })
        assert r.status_code == 409
        # 更新版本 -> 200 + version_changed
        r = c.put("/api/v1/marketplace/skills/translate-plus", json={"version": "1.1.0"})
        assert r.status_code == 200, r.text[:160]
        assert r.json()["data"]["version_changed"] is True
        # 下架
        r = c.delete("/api/v1/marketplace/skills/translate-plus")
        assert r.status_code == 200
        r = c.delete("/api/v1/marketplace/skills/translate-plus")
        assert r.status_code == 404

    def test_persist_after_restart(self, app, tmp_path):
        a, c = app
        _auth(c, "admin")
        c.post("/api/v1/marketplace/skills", json={
            "skill_id": "persist-me", "name": "Persist Me", "version": "1.0.0",
        })
        reset_market_store()
        from neurova.skills.market_store import get_market_store

        assert get_market_store().get("persist-me") is not None

    def test_update_version_notifies(self, app):
        a, c = app
        _auth(c, "admin")
        r = c.put("/api/v1/marketplace/skills/web-search", json={"version": "1.5.0"})
        assert r.status_code == 200
        mgr = notifications.get_notification_manager()
        target_ids = ["u1"] if (notifications.get_notification_manager()._user_notifications) else ["default"]
        # 通知应以 market_update 类型存在
        found = False
        all_notifications = list(mgr._notifications.values())
        for n in all_notifications:
            if n.notification_type == "market_update" and n.data.get("skill_id") == "web-search":
                found = True
                assert n.data.get("latest_version") == "1.5.0"
        assert found, "版本变更未产生 market_update 通知"

    def test_update_same_version_no_notify(self, app):
        a, c = app
        _auth(c, "admin")
        before_count = len(notifications.get_notification_manager()._notifications)
        c.put("/api/v1/marketplace/skills/web-search", json={"version": "1.2.0"})
        after_count = len(notifications.get_notification_manager()._notifications)
        assert after_count == before_count


class TestMarketplaceAuth:
    @pytest.mark.parametrize(
        "method,path,json",
        [
            ("get", "/api/v1/marketplace/skills", None),
            ("get", "/api/v1/marketplace/installed", None),
            ("get", "/api/v1/marketplace/skills/web-search", None),
            ("post", "/api/v1/marketplace/skills", {"skill_id": "x", "name": "x"}),
            ("put", "/api/v1/marketplace/skills/web-search", {"version": "9.9.9"}),
            ("delete", "/api/v1/marketplace/skills/web-search", None),
        ],
    )
    def test_unauthorized_401(self, app, method, path, json):
        a, c = app
        r = getattr(c, method)(path, json=json) if json is not None else getattr(c, method)(path)
        assert r.status_code == 401, (method, path, r.text[:120])

    def test_user_forbidden_on_admin_endpoints(self, app):
        a, c = app
        _auth(c, "user")
        assert c.post("/api/v1/marketplace/skills", json={"skill_id": "x", "name": "x"}).status_code == 403
        assert c.put("/api/v1/marketplace/skills/web-search", json={"version": "9.9.9"}).status_code == 403
        assert c.delete("/api/v1/marketplace/skills/web-search").status_code == 403

    def test_user_can_read_and_install(self, app):
        a, c = app
        _auth(c, "user")
        assert c.get("/api/v1/marketplace/skills").status_code == 200
        assert c.get("/api/v1/marketplace/installed").status_code == 200
        # 安装走真实 importer(单例 data/skills) — 使用不存在的技能预期 404, 证明路由+鉴权通过
        assert c.post("/api/v1/marketplace/skills/no-such-skill/install").status_code == 404
