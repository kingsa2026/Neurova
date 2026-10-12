"""
技能市场 提交/审批 通知闭环 测试（2026-09-01 TDD）

背景：市场端上架/更新/下架均仅管理员直发，普通用户没有"提交技能
上架"的入口；版本更新通知已有（_notify_market_update）但走契约断裂
的旧通知端点。

契约：
1. POST /skills/submit（登录用户）→ 提交进入 pending，
   所有管理员收到 skill_review 通知
2. GET /skill-submissions（仅 admin）→ 待审列表
3. POST /skill-submissions/{id}/review（仅 admin）
   approve → 写入市场目录（真正上架）+ 提交者收到 skill_review_result
   reject  → 不上架 + 提交者收到拒绝回执
4. skill_id 与市场已有技能冲突 → 409
5. 版本更新通知沿用 market_update（走统一通知端点可见）
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import marketplace, notifications as notif_module
from neurova.api.deps import get_current_user
from neurova.skills.market_store import reset_market_store
from tests.auth_headers import overrideIdentity

USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
ADMIN = {"user_id": "a9", "username": "admin", "role": "admin", "neuser_id": "a9"}

BASE = "/api/v1/marketplace"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    monkeypatch.setenv("NEUROVA_MARKET_SUBMISSIONS", str(tmp_path / "submissions.json"))
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    reset_market_store()
    notif_module.reset_notification_manager()
    from neurova.skills.market_submissions import reset_market_submission_store

    reset_market_submission_store()
    # 管理员必须是真账号：通知枚举只走 UserModel/users.db（与身份链同一事实源），
    # 过去注入 enhanced_users_api._users_store 是在假契约上自证通过。
    from tests.unit.api._realAccountFixture import seedAccounts

    seeded = seedAccounts(
        monkeypatch, tmp_path, accounts=(("admin", "admin"), ("alice", "user"))
    )
    a = FastAPI()
    a.include_router(marketplace.router, prefix=BASE)
    with TestClient(a, raise_server_exceptions=False) as c:
        yield a, c, seeded
    reset_market_store()
    reset_market_submission_store()
    notif_module.reset_notification_manager()


def _auth(c, role):
    user = ADMIN if role == "admin" else USER
    overrideIdentity(c.app, user)
    return c


def _notifications_for(user_id: str):
    mgr = notif_module.get_notification_manager()
    return mgr.get_user_notifications(user_id, limit=50)


def _submit(c, **overrides):
    payload = {
        "skill_id": "my-tool",
        "name": "My Tool",
        "version": "1.0.0",
        "description": "A community skill",
        "download_url": "https://example.com/my-tool.zip",
    }
    payload.update(overrides)
    return c.post(f"{BASE}/skills/submit", json=payload)


class TestSkillSubmission:
    def test_submit_creates_pending_and_notifies_admin(self, app):
        _a, c, seeded = app
        _auth(c, "user")
        resp = _submit(c)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["status"] == "pending"
        assert body["data"]["submitted_by"] == "u1"
        assert body["data"]["submitted_by_name"] == "alice"

        admin_notes = _notifications_for(seeded["admin"])
        assert any(
            n.notification_type == "skill_review" and n.data.get("skill_id") == "my-tool"
            for n in admin_notes
        ), "用户提交技能后管理员必须收到 skill_review 通知"

    def test_submissions_list_admin_only(self, app):
        _a, c, seeded = app
        _auth(c, "user")
        _submit(c)
        _auth(c, "admin")
        resp = c.get(f"{BASE}/skill-submissions")
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert len(items) == 1 and items[0]["status"] == "pending"

        # 普通用户不可见
        _auth(c, "user")
        assert c.get(f"{BASE}/skill-submissions").status_code == 403

    def test_review_approve_publishes_and_notifies(self, app):
        _a, c, seeded = app
        _auth(c, "user")
        sub_id = _submit(c).json()["data"]["id"]

        _auth(c, "admin")
        resp = c.post(
            f"{BASE}/skill-submissions/{sub_id}/review", json={"approve": True, "note": "lgm"}
        )
        assert resp.status_code == 200, resp.text

        # 真正上架：市场目录可见
        r = c.get(f"{BASE}/skills/my-tool")
        assert r.status_code == 200, "approve 后技能必须出现在市场目录"

        notes = [n for n in _notifications_for("u1") if n.notification_type == "skill_review_result"]
        assert notes and notes[0].data.get("approve") is True, "通过后提交者必须收到回执"

    def test_review_reject_does_not_publish(self, app):
        _a, c, seeded = app
        _auth(c, "user")
        sub_id = _submit(c).json()["data"]["id"]

        _auth(c, "admin")
        resp = c.post(
            f"{BASE}/skill-submissions/{sub_id}/review", json={"approve": False, "note": "缺 README"}
        )
        assert resp.status_code == 200, resp.text
        assert c.get(f"{BASE}/skills/my-tool").status_code == 404, "拒绝后不得上架"

        notes = [n for n in _notifications_for("u1") if n.notification_type == "skill_review_result"]
        assert notes and notes[0].data.get("approve") is False
        assert any("README" in (n.message or "") for n in notes)

    def test_duplicate_skill_id_conflict(self, app):
        _a, c, seeded = app
        _auth(c, "user")
        assert _submit(c).status_code == 200
        assert _submit(c).status_code == 409, "重复 skill_id 提交须 409"

        # 与市场上架技能冲突
        _auth(c, "admin")
        c.post(f"{BASE}/skills", json={"skill_id": "taken", "name": "Taken", "version": "1.0.0"})
        _auth(c, "user")
        assert _submit(c, skill_id="taken").status_code == 409

    def test_unauthenticated_submit_401(self, app):
        _a, c, seeded = app
        c.app.dependency_overrides.pop(get_current_user, None)
        assert _submit(c).status_code == 401


class TestMarketUpdateNotify:
    def test_version_update_notification_reaches_unified_endpoint(self, app):
        _a, c, seeded = app
        _auth(c, "admin")
        r = c.put(
            f"{BASE}/skills/web-search", json={"version": "9.9.9"}
        )
        assert r.status_code == 200, r.text

        _auth(c, "user")
        # 走统一通知管理器断言（端点契约由 test_notifications_service 覆盖）。
        # 收件人必须是**真账号 id**——notify_all_users 现在枚举 users.db，
        # 拿旧注入字典里的 "u1" 去查，查到的是不存在的人。
        notes = _notifications_for(seeded["alice"])
        assert any(
            n.notification_type == "market_update" and n.data.get("skill_id") == "web-search"
            for n in notes
        ), "版本更新通知必须经统一通知服务到达用户"
