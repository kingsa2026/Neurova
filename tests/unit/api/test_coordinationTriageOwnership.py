# -*- coding: utf-8 -*-
"""API-09 红灯：/coordination/triage/check 缺会话属主校验。

审计（2026-11-25 全仓审计 · API-09）：router 有登录门但只收 conversation_id，
历史读取无 owner 过滤，空 key 静默回落全局 provider——任何登录用户可对任意
已知会话触发分诊，把他人会话历史发往默认 provider 并产生账单。

判据（P0-08 单源口径）：非属主一律 403；会话不存在 404；属主本人照常可达；
空属主会话仅主管理员可触发。判据复用全仓唯一归属比较式
（console._check_session_ownership，经 session_sync._requireSessionOwnership）。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints import coordination_api as coord_mod
from neurova.sync.session_sync_manager import (
    EventType,
    SessionEvent,
    get_session_sync_manager,
    reset_session_sync_manager,
)

ALICE = {"user_id": "alice", "username": "alice", "role": "user"}
BOB = {"user_id": "bob", "username": "bob", "role": "user"}
ADMIN = {"user_id": "9", "username": "root", "role": "admin"}


@pytest.fixture(autouse=True)
def _isolatedSync():
    reset_session_sync_manager()
    yield
    reset_session_sync_manager()


@pytest.fixture
def client():
    app = FastAPI()
    # 生产挂载：注册表前缀 /api/v1 + 模块自述 prefix /coordination
    app.include_router(coord_mod.router, prefix="/api/v1")
    tc = TestClient(app)

    def asUser(identity):
        # coordination router 的登录门与端点参数用的是同一函数对象
        # （neurova.api.auth.get_current_user），override 打在它上面对两端同时生效。
        tc.app.dependency_overrides[auth_mod.get_current_user] = lambda: identity

    tc.as_user = asUser
    return tc


@pytest.fixture
def aliceSessionId():
    manager = get_session_sync_manager()
    session = manager.create_session(user_id="alice", agent_id="agent_x", external_id="conv-alice-1")
    session.add_event(SessionEvent(
        event_type=EventType.USER_MESSAGE,
        session_id=session.session_id,
        payload={"content": "alice 的私密问题"},
    ))
    session.add_event(SessionEvent(
        event_type=EventType.AGENT_REPLY,
        session_id=session.session_id,
        payload={"content": "alice 的私密回复"},
    ))
    return session.session_id


@pytest.fixture
def fakeTriageModel(monkeypatch):
    """把分诊模型调用替换成真解析形状的假实现（不碰外网、不碰凭据）。"""

    class _FakeResult:
        content = '{"actionable": false, "reason": "agent loop"}'

    async def _fakeCall(self, messages):
        return _FakeResult()

    from neurova.llm.triage import SmallBrainTriageGate

    monkeypatch.setattr(SmallBrainTriageGate, "_call_triage_model", _fakeCall)


class TestTriageOwnershipGate:
    def test_nonOwnerTriagingForeignSessionIs403(self, client, aliceSessionId):
        """bob 对 alice 的会话触发分诊必须 403（修前：历史被发往默认 provider）。"""
        client.as_user(BOB)
        resp = client.post(f"/api/v1/coordination/triage/check?conversation_id={aliceSessionId}")
        assert resp.status_code == 403, (
            f"非属主触发他人会话分诊未被拒：{resp.status_code} {resp.text[:160]}"
        )

    def test_missingSessionIs404(self, client):
        """不存在的会话 404，不进分诊链。"""
        client.as_user(BOB)
        resp = client.post("/api/v1/coordination/triage/check?conversation_id=conv-not-exists")
        assert resp.status_code == 404, (
            f"不存在的会话未按 404 拒绝：{resp.status_code} {resp.text[:160]}"
        )

    def test_ownerCanStillTriageOwnSession(self, client, aliceSessionId, fakeTriageModel):
        """收紧不得把属主自己挡在门外：alice 对自己的会话分诊照常出结论。"""
        client.as_user(ALICE)
        resp = client.post(f"/api/v1/coordination/triage/check?conversation_id={aliceSessionId}")
        assert resp.status_code == 200, (
            f"属主本人分诊被误拒：{resp.status_code} {resp.text[:160]}"
        )
        body = resp.json()
        assert body["actionable"] is False
        assert body["reason"] == "agent loop"

    def test_emptyOwnerSessionAdminOnly(self, client, fakeTriageModel, monkeypatch):
        """空属主会话按 P0-08 归主管理员：普通用户 403，管理员可达。"""
        # 测试环境无真实管理员库：把主管理员解析钉到 ADMIN 的 user_id，
        # 只验"空属主 → 管理员"这条归属语义，不验管理员查库本身。
        import neurova.post_chat_pipeline as pcp

        monkeypatch.setattr(pcp, "_adminOwnerId", lambda: "9")

        manager = get_session_sync_manager()
        session = manager.create_session(user_id="", agent_id="agent_x", external_id="conv-legacy")
        session.add_event(SessionEvent(
            event_type=EventType.USER_MESSAGE,
            session_id=session.session_id,
            payload={"content": "历史无主会话消息"},
        ))

        client.as_user(BOB)
        resp = client.post(f"/api/v1/coordination/triage/check?conversation_id={session.session_id}")
        assert resp.status_code == 403, (
            f"普通用户读取空属主会话分诊未被拒：{resp.status_code} {resp.text[:160]}"
        )

        client.as_user(ADMIN)
        resp = client.post(f"/api/v1/coordination/triage/check?conversation_id={session.session_id}")
        assert resp.status_code == 200, (
            f"管理员分诊空属主会话被误拒：{resp.status_code} {resp.text[:160]}"
        )
