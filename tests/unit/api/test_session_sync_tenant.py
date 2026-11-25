# -*- coding: utf-8 -*-
"""A9c 红灯：WS 订阅腿归属校验前置（§6.4）。

存量会话不得因「已在册」放行任意认证用户——外部编码代理的流式内容
（含代码片段）只归会话属主可见；历史空属主统一归主管理员（复用 console 的
_check_session_ownership 单源判据，不再按共享放行）。
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from neurova.api.auth import create_access_token
from neurova.api.endpoints.session_sync import router as session_sync_router
from neurova.sync.session_sync_manager import get_session_sync_manager


def tokenFor(uid, role="user"):
    return create_access_token({
        "sub": uid, "username": uid, "role": role, "neuser_id": uid,
        "tenant_id": "default",
    })


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(session_sync_router)
    manager = get_session_sync_manager()
    manager._sessions.clear()
    manager.register_or_create_session("sess-u1", user_id="u1", agent_id="default")
    return TestClient(app)


def test_crossUserSubscribeRejected(client):
    with pytest.raises(Exception) as exc:
        with client.websocket_connect(f"/ws/sess-u1?token={tokenFor('u2')}") as ws:
            ws.receive_json()
    code = getattr(exc.value, "code", None)
    assert code == 4403 or "4403" in str(exc.value) or "403" in str(exc.value)


def test_ownerSubscribeAllowed(client):
    with client.websocket_connect(f"/ws/sess-u1?token={tokenFor('u1')}") as ws:
        hello = ws.receive_json()
        assert hello.get("type") == "sync_hello"


def test_ownerlessSessionRequiresPrimaryAdmin(client, monkeypatch):
    from neurova import post_chat_pipeline

    manager = get_session_sync_manager()
    manager.register_or_create_session("sess-ownerless", user_id="", agent_id="default")
    monkeypatch.setattr(post_chat_pipeline, "_adminOwnerId", lambda: "u2")

    with pytest.raises(Exception) as exc:
        with client.websocket_connect(f"/ws/sess-ownerless?token={tokenFor('u3')}") as ws:
            ws.receive_json()
    code = getattr(exc.value, "code", None)
    assert code == 4403 or "4403" in str(exc.value) or "403" in str(exc.value)

    with client.websocket_connect(f"/ws/sess-ownerless?token={tokenFor('u2')}") as ws:
        hello = ws.receive_json()
        assert hello.get("type") == "sync_hello"
