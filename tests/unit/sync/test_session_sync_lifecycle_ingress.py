"""P2-18：Session Sync 入站、生命周期与 Agent 回路的真实装配回归。

这些用例不用 MagicMock 冒充 Agent/ChannelManager：
- 真 FastAPI router + 真 SessionSyncManager + 真 ChannelManager；
- Agent 是可记录调用的事实替身，只替换 lookup 边界；
- REST 无 WebSocket 时，Agent 回复仍必须落进同一会话历史。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import deps
from neurova.api.auth import create_access_token
from neurova.api.endpoints import session_sync
from neurova.channels.manager import ChannelManager
from neurova.sync.session_sync_manager import EventType, reset_session_sync_manager
from tests.auth_headers import pinJwtSecret


class _Agent:
    """真实调用面的事实替身：记录 session/metadata，并返回可回放的回复。"""

    def __init__(self, owner_user_id: str = "agent-owner"):
        self.config = SimpleNamespace(owner_user_id=owner_user_id)
        self.calls: list[dict] = []
        self.current_reasoning = ""

    async def chat(self, user_input: str, session_id: str, metadata: dict) -> dict:
        self.calls.append(
            {"user_input": user_input, "session_id": session_id, "metadata": dict(metadata)}
        )
        return {"text": f"reply:{user_input}"}


@pytest.fixture()
def assembled(monkeypatch):
    reset_session_sync_manager()
    ChannelManager._instance = None
    manager = ChannelManager.get_instance()
    sync_manager = session_sync.get_session_sync_manager()
    agent = _Agent()
    monkeypatch.setattr("neurova.api.endpoints.get_agent_instance", lambda _aid: agent)

    app = FastAPI()
    app.include_router(session_sync.router, prefix="/api/v1/sync")
    app.dependency_overrides[deps.get_current_user] = lambda: {
        "user_id": "alice",
        "neuser_id": "alice",
        "username": "alice",
        "role": "user",
    }
    pinJwtSecret()
    token = create_access_token(
        {"sub": "alice", "username": "alice", "role": "user", "neuser_id": "alice", "user_id": "alice"}
    )
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            manager=manager,
            sync=sync_manager,
            agent=agent,
            token=token,
        )
    reset_session_sync_manager()
    ChannelManager._instance = None


def _create_session(ctx, agent_id: str = "default") -> str:
    response = ctx.client.post(
        "/api/v1/sync/sessions",
        json={"user_id": "alice", "agent_id": agent_id},
    )
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


def test_restWithoutWsRunsAgentAndPersistsReply(assembled):
    ctx = assembled
    sid = _create_session(ctx, agent_id="default")

    response = ctx.client.post(
        f"/api/v1/sync/sessions/{sid}/messages",
        json={"content": "hello", "channel_type": "api"},
    )

    assert response.status_code == 200, response.text
    assert len(ctx.agent.calls) == 1, "REST 消息只写历史，未触发 Agent"
    call = ctx.agent.calls[0]
    assert call["session_id"] == sid
    assert call["metadata"]["user_id"] == "alice", "发送者 token 身份被渠道身份解析覆盖"
    assert call["metadata"]["session_owner_id"] == "agent-owner", "Agent 属主身份丢失"
    messages = ctx.sync.get_messages(sid, limit=10)
    assert [m["role"] for m in messages] == ["user", "assistant"], messages
    assert messages[-1]["content"] == "reply:hello"


def test_wsMessageUsesSameIngressAndReceivesAgentReply(assembled):
    ctx = assembled
    sid = _create_session(ctx, agent_id="default")
    url = f"/api/v1/sync/ws/{sid}?channel_type=web&token={ctx.token}"

    with ctx.client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "sync_hello"
        ws.receive_json()  # session_created
        ws.receive_json()  # channel_connected

        ws.send_json({"type": "user_message", "content": "from-ws"})
        assert ws.receive_json()["type"] == "message_sent"
        reply = ws.receive_json()
        assert reply["event_type"] == EventType.AGENT_REPLY.value, reply
        assert reply["payload"]["content"] == "reply:from-ws"

    assert len(ctx.agent.calls) == 1
    assert ctx.agent.calls[0]["metadata"]["user_id"] == "alice"
    assert ctx.agent.calls[0]["metadata"]["session_owner_id"] == "agent-owner"


def test_wsIdentityUsesTokenSubjectRatherThanNeuserId(assembled):
    ctx = assembled
    sid = _create_session(ctx)
    token = create_access_token({
        "sub": "alice", "user_id": "alice", "neuser_id": "alice-ne",
        "username": "alice", "role": "user",
    })
    url = f"/api/v1/sync/ws/{sid}?channel_type=web&token={token}"

    with ctx.client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "sync_hello"
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "user_message", "content": "identity"})
        assert ws.receive_json()["type"] == "message_sent"
        assert ws.receive_json()["event_type"] == EventType.AGENT_REPLY.value

    assert ctx.agent.calls[0]["metadata"]["user_id"] == "alice"
    assert ctx.agent.calls[0]["metadata"]["memory_scope"] == {
        "neuser_id": "alice-ne", "user_id": "alice"}


def test_terminalSessionDoesNotAcceptFallbackReply(assembled, monkeypatch):
    ctx = assembled
    sid = _create_session(ctx)

    async def pause_during_chat(user_input, session_id, metadata):
        ctx.sync.pause_session(session_id)
        return {"text": "late-reply"}

    monkeypatch.setattr(ctx.agent, "chat", pause_during_chat)
    response = ctx.client.post(
        f"/api/v1/sync/sessions/{sid}/messages",
        json={"content": "hello", "channel_type": "api"},
    )

    assert response.status_code == 200, response.text
    events = ctx.sync.get_session(sid).history
    assert events[-1].event_type == EventType.SESSION_PAUSED
    assert not any(event.event_type == EventType.AGENT_REPLY for event in events)


def test_wsEndDisconnectsAndClearsRegisteredChannels(assembled):
    ctx = assembled
    sid = _create_session(ctx)
    url = f"/api/v1/sync/ws/{sid}?channel_type=web&token={ctx.token}"

    with ctx.client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "sync_hello"
        ws.receive_json()
        ws.receive_json()
        ws.send_json({"type": "end_session"})
        assert ws.receive_json()["event_type"] == EventType.SESSION_ENDED.value
        with pytest.raises(Exception):
            ws.receive_json()

    assert ctx.sync.get_session(sid).active_channels == {}


def test_pauseResumeEndShareStateGateBroadcastAndDisconnect(assembled):
    ctx = assembled
    sid = _create_session(ctx, agent_id="default")
    url = f"/api/v1/sync/ws/{sid}?channel_type=web&token={ctx.token}"

    with ctx.client.websocket_connect(url) as ws:
        assert ws.receive_json()["type"] == "sync_hello"
        ws.receive_json()
        ws.receive_json()

        paused = ctx.client.post(f"/api/v1/sync/sessions/{sid}/pause")
        assert paused.status_code == 200, paused.text
        assert ws.receive_json()["event_type"] == EventType.SESSION_PAUSED.value
        assert ctx.sync.get_session(sid).status == "paused"

        blocked = ctx.client.post(
            f"/api/v1/sync/sessions/{sid}/messages", json={"content": "blocked"}
        )
        assert blocked.status_code == 409, blocked.text
        assert ctx.agent.calls == []

        resumed = ctx.client.post(f"/api/v1/sync/sessions/{sid}/resume")
        assert resumed.status_code == 200, resumed.text
        assert ws.receive_json()["event_type"] == EventType.SESSION_RESUMED.value

        ended = ctx.client.delete(f"/api/v1/sync/sessions/{sid}")
        assert ended.status_code == 200, ended.text
        assert ws.receive_json()["event_type"] == EventType.SESSION_ENDED.value
        with pytest.raises(Exception):
            ws.receive_json()  # 结束后服务端必须断连

    assert ctx.sync.get_session(sid).status == "ended"
    with pytest.raises(ValueError, match="ended"):
        ctx.sync.register_or_create_session(sid, user_id="alice", agent_id="default")
