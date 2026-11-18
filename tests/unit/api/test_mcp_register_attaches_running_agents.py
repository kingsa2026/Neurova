"""
红灯 2（外部手机网关接入批）：运行期经 API 注册的 MCP server 必须即时进入
agent 工具面，无需重启。

现状断点：`_register_mcp_server` 只把连接建在进程单例里；agent ToolRouter
的挂载来源只有 bootstrap 注册表（attach_bootstrapped_clients），运行期注册
的 server 不在其中 → 已在运行的 agent 看不到新 server 的工具，必须重启。
本测试同时钉住删除侧：DELETE 后必须从运行中 agent 摘除并清出注册表，
否则留下 zombie 供后续 attach 误挂。
"""
import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_mcp_attach_running_agents")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_mcp_attach_running_agents")

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.app import AppState
from neurova.api.auth import get_current_user
from neurova.api.endpoints import tool_layers
from neurova.tool_layers.mcp_bootstrap import get_bootstrapped_clients

BASE = "/v1/tool-layers"
REGISTER_BODY = {
    "name": "phonegw",
    "transport": "http",
    "url": "http://127.0.0.1:7465/mcp",
}


class FakeRouter:
    def __init__(self):
        self.registered = []
        self.detached = []

    def register_mcp_client(self, server_id, client):
        self.registered.append((server_id, client))

    def detach_mcp_client(self, server_id):
        self.detached.append(server_id)


class FakeManager:
    def __init__(self):
        self.items = {}

    def add_mcp_server(self, cfg):
        self.items[cfg["id"]] = cfg
        return True

    def get_mcp_server(self, sid):
        return self.items.get(sid)

    def remove_mcp_server(self, sid):
        return self.items.pop(sid, None) is not None

    def list_mcp_servers(self):
        return list(self.items.values())


class FakeClient:
    def __init__(self):
        self.connected = {}

    async def connect_server(self, sid, cfg):
        self.connected[sid] = cfg
        return True

    async def disconnect_server(self, sid):
        return self.connected.pop(sid, None) is not None

    def get_server_status(self, sid):
        return {
            "server_id": sid,
            "connected": sid in self.connected,
            "tool_count": 1 if sid in self.connected else 0,
            "last_error": None,
            "transport": "http",
        }


@pytest.fixture
def env(monkeypatch):
    manager, client = FakeManager(), FakeClient()
    monkeypatch.setattr("neurova.shared_config.get_shared_config_manager", lambda: manager)
    monkeypatch.setattr("neurova.tool_layers.mcp_client.get_mcp_client", lambda user_id=None: client)

    state = AppState()
    router = FakeRouter()
    state.agents["default"] = types.SimpleNamespace(tool_router=router)
    monkeypatch.setattr(
        "neurova.api.endpoints.tool_layers._running_app_state", lambda: state, raising=False
    )

    app = FastAPI()
    app.include_router(tool_layers.router, prefix=BASE)
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u_admin",
        "username": "admin",
        "role": "admin",
        "neuser_id": "ne_admin",
    }
    yield TestClient(app), router, client, manager
    app.dependency_overrides.clear()


def test_register_attaches_server_to_running_agents(env):
    client, router, _, _ = env
    resp = client.post(f"{BASE}/mcp-servers", json=REGISTER_BODY)
    assert resp.status_code == 200, resp.text
    assert any(sid == "phonegw" for sid, _ in router.registered), (
        "运行期注册的 MCP server 必须即时挂到运行中 agent 的 ToolRouter"
    )
    assert "phonegw" in get_bootstrapped_clients(), (
        "运行期注册的客户端必须登记进 bootstrap 注册表（attach 的唯一发现口）"
    )


def test_register_failure_does_not_attach(env):
    client, router, fake, _ = env

    async def fail_connect(sid, cfg):
        return False

    fake.connect_server = fail_connect
    resp = client.post(f"{BASE}/mcp-servers", json=REGISTER_BODY)
    assert resp.status_code == 200  # 注册面返回 error 态而非 5xx
    assert not router.registered, "连接失败的 server 不得挂进 agent 工具面"


def test_delete_detaches_server_from_running_agents(env):
    client, router, _, _ = env
    assert client.post(f"{BASE}/mcp-servers", json=REGISTER_BODY).status_code == 200
    resp = client.delete(f"{BASE}/mcp-servers/phonegw")
    assert resp.status_code == 200, resp.text
    assert "phonegw" in router.detached, "删除后必须从运行中 agent 的 ToolRouter 摘除"
    assert "phonegw" not in get_bootstrapped_clients(), "删除后注册表不得残留 zombie 条目"
