"""sync WS 端点鉴权契约测试（S-03 契约 + 握手 403 根修 2026-09-12）

- 未带 token / 无效 token：必须先 accept 完成 WebSocket 握手、再以
  close(4401) 关闭。此前实现在 accept 之前 close，uvicorn 对"未 accept
  即 close"一律回 HTTP 403 握手拒绝——4401 语义到不了客户端，浏览器报
  "WebSocket handshake: Unexpected response code: 403"，前端无法区分
  鉴权失败（不该重连）与网络故障（该重连）
- 合法 token：正常进入事件流（sync_hello 纪元探测帧）
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from neurova.api.auth import create_access_token
from neurova.api.endpoints import session_sync


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(session_sync.router, prefix="/api/v1/sync")
    return TestClient(app)


def _valid_token(user_id: str = "42") -> str:
    return create_access_token(
        {"sub": user_id, "username": "alice", "role": "user", "neuser_id": user_id, "user_id": user_id}
    )


class TestSyncWsAuthContract:
    def test_missing_token_accepted_then_closed_4401(self, client):
        """无 token：握手必须完成（accept），随后 4401 关闭——不能 403 拒绝握手"""
        with client.websocket_connect("/api/v1/sync/ws/ws-auth-none?channel_type=web") as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
        assert exc_info.value.code == 4401

    def test_invalid_token_accepted_then_closed_4401(self, client):
        """无效 token：同样 accept 后 4401，而非握手 403"""
        with client.websocket_connect(
            "/api/v1/sync/ws/ws-auth-bad?channel_type=web&token=garbage.jwt.value"
        ) as ws:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
        assert exc_info.value.code == 4401

    def test_valid_token_enters_event_stream(self, client):
        """合法 token：握手 + 4401 分支不触发，正常收到 sync_hello"""
        token = _valid_token("42")
        with client.websocket_connect(
            f"/api/v1/sync/ws/ws-auth-ok?channel_type=web&token={token}"
        ) as ws:
            hello = ws.receive_json()
            assert hello["type"] == "sync_hello"

    def test_user_id_derived_from_token_not_client_param(self, client):
        """user_id 必须从 token 主体派生（IDOR 防护）：注册会话归属 neuser_id"""
        token = _valid_token("424242")
        with client.websocket_connect(
            f"/api/v1/sync/ws/ws-auth-owner?channel_type=web&token={token}"
        ) as ws:
            ws.receive_json()  # sync_hello
        manager = session_sync.get_session_sync_manager()
        session = manager._sessions.get("ws-auth-owner")
        assert session is not None
        assert session.user_id == "424242"
