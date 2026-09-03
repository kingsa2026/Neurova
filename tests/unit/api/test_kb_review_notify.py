"""
知识库公库提交/审批 通知闭环 测试（2026-09-01 TDD）

背景：submit-public 是纯存储操作，管理员收不到任何通知；
review 结果也不回执提交者——审批闭环靠管理员"恰好打开知识库页面"。

契约：
1. submit-public 成功 → 所有管理员收到 kb_review 通知
   （data 带 knowledge_id/title/submitter，供通知中心跳转）
2. review-public 成功 → 提交者收到 kb_review_result 通知
   （approve 与拒绝文案区分；data 带 knowledge_id/approve）

测试范式：裸 FastAPI + dependency_overrides（同 test_knowledge_isolation_api）。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.api.endpoints import notifications as notif_module
from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}

PREFIX = "/v1/knowledge"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))
    notif_module.reset_notification_manager()
    # 管理员枚举来源
    import neurova.api.endpoints.enhanced_users_api as users_api

    monkeypatch.setattr(
        users_api,
        "_users_store",
        {"9": {"role": "admin", "username": "admin"}, "1": {"role": "user", "username": "alice"}},
        raising=False,
    )

    r = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr("neurova.knowledge.repository.get_knowledge_repository", lambda: r)

    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": dict(ALICE)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    client = TestClient(app)
    return client, holder, r


def _notifications_for(user_id: str):
    mgr = notif_module.get_notification_manager()
    return [n for n in mgr.get_user_notifications(user_id, limit=50)]


def _create_pending_submission(client, holder):
    """alice 建条目并提交公库，返回 knowledge_id；随后切回 alice。"""
    holder["user"] = dict(ALICE)
    resp = client.post(PREFIX, json={"title": "私有知识", "content": "内容"})
    assert resp.status_code == 200, resp.text
    kid = resp.json()["knowledge_id"]
    resp = client.post(f"{PREFIX}/{kid}/submit-public")
    assert resp.status_code == 200, resp.text
    return kid


class TestSubmissionNotifiesAdmins:
    def test_submit_public_notifies_admin(self, api):
        client, holder, _r = api
        kid = _create_pending_submission(client, holder)

        admin_notes = _notifications_for("9")
        assert any(
            n.notification_type == "kb_review" and n.data.get("knowledge_id") == kid
            for n in admin_notes
        ), "提交公库后管理员必须收到 kb_review 通知（含 knowledge_id）"
        # 提交者本人不收自己的提交通知
        assert not any(n.notification_type == "kb_review" for n in _notifications_for("1"))

    def test_notification_carries_context(self, api):
        client, holder, _r = api
        _create_pending_submission(client, holder)
        n = _notifications_for("9")[0]
        assert n.data.get("submitter") == "1", "submitter 存 user_id（与 repo 契约一致）"
        assert n.data.get("submitter_name") == "alice"
        assert "私有知识" in (n.title + n.message)


class TestReviewNotifiesSubmitter:
    def test_approve_notifies_submitter(self, api):
        client, holder, _r = api
        kid = _create_pending_submission(client, holder)
        holder["user"] = dict(ADMIN)
        resp = client.post(f"{PREFIX}/{kid}/review-public", json={"approve": True, "note": "ok"})
        assert resp.status_code == 200, resp.text

        notes = _notifications_for("1")
        assert any(
            n.notification_type == "kb_review_result" and n.data.get("approve") is True
            for n in notes
        ), "审批通过后提交者必须收到回执"

    def test_reject_notifies_submitter(self, api):
        client, holder, _r = api
        kid = _create_pending_submission(client, holder)
        holder["user"] = dict(ADMIN)
        resp = client.post(f"{PREFIX}/{kid}/review-public", json={"approve": False, "note": "质量不足"})
        assert resp.status_code == 200, resp.text

        notes = [n for n in _notifications_for("1") if n.notification_type == "kb_review_result"]
        assert notes and any(n.data.get("approve") is False for n in notes), "拒绝也要回执提交者"
        assert any("质量不足" in (n.message or "") for n in notes)
