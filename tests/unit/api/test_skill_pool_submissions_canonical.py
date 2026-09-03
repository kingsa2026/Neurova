"""
TDD Red:canonical 域名下的技能提交/审核三连 (/v1/skill-pool/*)

背景（2026-09-03 线上 404）:SkillMarketPage 调 GET /skill-pool/skill-submissions
404 —— ADR 0013 已把技能市场域 canonical 收敛到 /v1/skill-pool,前端与前端
契约测试均按 /skill-pool/* 接线,但提交-审核三连的后端实现仍寄生在
/v1/marketplace,属迁移漏项。本测试锁定 canonical 前缀下的
submit / list / review 契约 —— 当前实现(skill_pool_api.py 无此三连)全部失败。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import skill_pool_api
from neurova.api.deps import get_current_user
from neurova.skills.market_store import get_market_store, reset_market_store

USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}
ADMIN = {"user_id": "a9", "username": "admin", "role": "admin", "neuser_id": "a9"}
BASE = "/api/v1/skill-pool"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    monkeypatch.setenv("NEUROVA_MARKET_SUBMISSIONS", str(tmp_path / "submissions.json"))
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    reset_market_store()

    from neurova.skills.market_submissions import reset_market_submission_store

    reset_market_submission_store()
    import neurova.api.endpoints.notifications as notif_module

    notif_module.reset_notification_manager()

    import neurova.api.endpoints.enhanced_users_api as users_api

    monkeypatch.setattr(
        users_api,
        "_users_store",
        {"a9": {"role": "admin", "username": "admin"}, "u1": {"role": "user", "username": "alice"}},
        raising=False,
    )

    a = FastAPI()
    a.include_router(skill_pool_api.router, prefix=BASE)
    with TestClient(a, raise_server_exceptions=False) as c:
        yield a, c

    reset_market_store()
    reset_market_submission_store()
    notif_module.reset_notification_manager()


def _auth(c, role):
    user = ADMIN if role == "admin" else USER
    c.app.dependency_overrides[get_current_user] = lambda: user
    return c


class TestCanonicalSkillSubmissions:
    def test_submit_skill_under_canonical_prefix(self, app):
        _, c = app
        _auth(c, "user")
        resp = c.post(
            f"{BASE}/skills/submit",
            json={
                "skill_id": "my-tool",
                "name": "My Tool",
                "version": "1.0.0",
                "description": "A community skill",
                "download_url": "https://example.com/my-tool.zip",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["code"] == 0

    def test_list_submissions_under_canonical_prefix(self, app):
        _, c = app
        _auth(c, "user")
        c.post(f"{BASE}/skills/submit", json={"skill_id": "my-tool", "name": "My Tool"})
        _auth(c, "admin")
        resp = c.get(f"{BASE}/skill-submissions", params={"review_status": "pending"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["skill_id"] == "my-tool"

    def test_review_approve_under_canonical_prefix_writes_market(self, app):
        _, c = app
        _auth(c, "user")
        c.post(f"{BASE}/skills/submit", json={"skill_id": "my-tool", "name": "My Tool"})
        _auth(c, "admin")
        sub_id = c.get(f"{BASE}/skill-submissions").json()["data"]["items"][0]["id"]
        resp = c.post(f"{BASE}/skill-submissions/{sub_id}/review", json={"approve": True})
        assert resp.status_code == 200, resp.text
        assert get_market_store().get("my-tool") is not None

    def test_submit_conflict_409_under_canonical_prefix(self, app):
        _, c = app
        _auth(c, "user")
        c.post(f"{BASE}/skills/submit", json={"skill_id": "my-tool", "name": "My Tool"})
        resp = c.post(
            f"{BASE}/skills/submit", json={"skill_id": "my-tool", "name": "My Tool 2"}
        )
        assert resp.status_code == 409, resp.text


class TestCanonicalPermissionGate:
    """可见性契约:提交面板=登录用户入口;审核列表/审批=仅管理员(前端 gate 之外
    后端必须强制,防止绕过前端直接调接口)。"""

    def _no_auth(self):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Not authenticated")

    def test_list_403_for_regular_user(self, app):
        _, c = app
        _auth(c, "user")
        resp = c.get(f"{BASE}/skill-submissions")
        assert resp.status_code == 403, resp.text

    def test_review_403_for_regular_user(self, app):
        _, c = app
        _auth(c, "user")
        resp = c.post(f"{BASE}/skill-submissions/whatever/review", json={"approve": True})
        assert resp.status_code == 403, resp.text

    def test_submit_401_for_anonymous(self, app):
        _, c = app
        c.app.dependency_overrides[get_current_user] = self._no_auth
        resp = c.post(f"{BASE}/skills/submit", json={"skill_id": "my-tool", "name": "My Tool"})
        assert resp.status_code == 401, resp.text
