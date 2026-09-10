"""BUG AUDIT S-17 残余回归测试: console WS 连接生命周期收口。

已修复部分（本测试守护）: token 校验（无效 → 4401 拒绝）。
残余缺陷（本测试驱动修复）:
1. 仅 `except WebSocketDisconnect` 清理连接 —— 其他异常（如 receive_json
   解析失败）时条目永久滞留 _manager（泄漏 + 已断连接被 broadcast 重试）;
   修复: try/finally 收口。
2. client_id 由客户端任意指定 —— 可冒用他人条目（覆盖其 WebSocket,
   接收其推送/破坏其连接）；修复: 服务端按 f"{user}:{uuid4().hex[:8]}"
   派生连接键, 路径参数仅保留路由形状不作为身份。

前端核查结论: NeurUI 中 getConsoleWSUrl 为死代码（无调用方）,
无任何前端依赖特定 client_id 语义。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_s17_0123456789abc")

from neurova.api.auth import create_access_token
from neurova.api.endpoints import console as console_module


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(console_module.router, prefix="/api/v1/console")
    return TestClient(app)


@pytest.fixture()
def user_token():
    return create_access_token({"sub": "ws-user-1", "username": "wsu", "role": "user"})


class TestTokenGate:
    def test_invalid_token_rejected_4401(self, client):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/api/v1/console/ws/any-id?token=forged-token"):
                pass
        assert exc.value.code == 4401


class TestServerDerivedClientId:
    def test_connection_key_is_server_derived(self, client, user_token):
        """连接键必须是服务端派生的 f"{user}:...", 不采纳客户端路径参数"""
        with client.websocket_connect(f"/api/v1/console/ws/attacker-chosen-id?token={user_token}") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"
            keys = list(console_module._manager._connections.keys())
            assert len(keys) == 1
            assert keys[0] != "attacker-chosen-id", "客户端路径参数被用作连接键（可冒用他人条目）"
            assert keys[0].startswith("ws-user-1:"), f"连接键未按用户派生: {keys[0]!r}"

    def test_distinct_connections_get_distinct_keys(self, client, user_token):
        """同一用户两条连接 → 两个独立连接键, 不互相覆盖"""
        with client.websocket_connect(f"/api/v1/console/ws/x?token={user_token}") as ws1:
            with client.websocket_connect(f"/api/v1/console/ws/y?token={user_token}") as ws2:
                keys = set(console_module._manager._connections.keys())
                assert len(keys) == 2, f"两条连接被合并: {keys}"


class TestFinallyCleanup:
    def test_unexpected_exception_cleans_connection(self, client, user_token):
        """非 WebSocketDisconnect 异常（无效 JSON）也必须清理 _manager 条目"""
        with pytest.raises(Exception):
            with client.websocket_connect(f"/api/v1/console/ws/some-id?token={user_token}") as ws:
                ws.send_text("{not-valid-json")
                ws.receive_json()
        assert console_module._manager._connections == {}, (
            "异常退出后连接条目滞留 _manager（缺少 finally 收口）"
        )

    def test_normal_disconnect_cleans_connection(self, client, user_token):
        with client.websocket_connect(f"/api/v1/console/ws/some-id?token={user_token}") as ws:
            ws.send_json({"type": "ping"})
            ws.receive_json()
        assert console_module._manager._connections == {}
