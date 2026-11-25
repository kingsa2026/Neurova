# -*- coding: utf-8 -*-
"""P0-09：MCP 全局注册表的管理员门、ID 唯一性与 Agent 属主隔离。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import tool_layers
from neurova.tool_layers import mcp_bootstrap

BASE = "/v1/tool-layers"


class FakeManager:
    def __init__(self):
        self.items = {}

    def add_mcp_server(self, config):
        serverId = config["id"]
        if serverId in self.items:
            return False
        self.items[serverId] = dict(config)
        return True

    def get_mcp_server(self, serverId):
        return self.items.get(serverId)

    def list_mcp_servers(self):
        return list(self.items.values())

    def remove_mcp_server(self, serverId):
        return self.items.pop(serverId, None) is not None


class FakeClient:
    def __init__(self):
        self.connectCalls = []
        self.connected = {}

    async def connect_server(self, serverId, config):
        self.connectCalls.append((serverId, dict(config)))
        self.connected[serverId] = dict(config)
        return True

    async def disconnect_server(self, serverId):
        return self.connected.pop(serverId, None) is not None

    async def disconnect_all(self):
        self.connected.clear()

    def get_server_status(self, serverId):
        return {
            "server_id": serverId,
            "connected": serverId in self.connected,
            "last_error": None,
            "tool_count": 0,
            "transport": (self.connected.get(serverId) or {}).get("transport"),
        }


class FakeRouter:
    def __init__(self):
        self.registered = {}

    def register_mcp_client(self, serverId, client):
        self.registered[serverId] = client


@pytest.fixture()
def registryEnv(monkeypatch):
    manager = FakeManager()
    client = FakeClient()
    state = SimpleNamespace(
        agents={
            "agent_admin": SimpleNamespace(
                config=SimpleNamespace(owner_user_id="u_admin"),
                tool_router=FakeRouter(),
            ),
            "agent_bob": SimpleNamespace(
                config=SimpleNamespace(owner_user_id="u_bob"),
                tool_router=FakeRouter(),
            ),
        }
    )
    monkeypatch.setattr(
        "neurova.shared_config.get_shared_config_manager", lambda: manager
    )
    monkeypatch.setattr(
        "neurova.tool_layers.mcp_client.get_mcp_client", lambda user_id=None: client
    )
    monkeypatch.setattr(tool_layers, "_running_app_state", lambda: state)
    mcp_bootstrap.reset_bootstrap()
    yield manager, client, state
    mcp_bootstrap.reset_bootstrap()


def _client(role="admin"):
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(tool_layers.router, prefix=BASE)
    userId = "u_admin" if role == "admin" else "u_bob"
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": userId,
        "username": role,
        "role": role,
        "neuser_id": userId,
    }
    return TestClient(app)


def _httpConfig(name="runtime", url="https://example.com/mcp"):
    return {"name": name, "transport": "http", "url": url}


@pytest.mark.parametrize("transport", ["http", "sse"])
def test_nonAdminCannotRegisterRemoteMcp(registryEnv, transport):
    manager, client, _ = registryEnv
    body = _httpConfig()
    body["transport"] = transport
    with _client("user") as http:
        response = http.post(f"{BASE}/mcp-servers", json=body)
    assert response.status_code == 403
    assert manager.items == {}
    assert client.connectCalls == []


@pytest.mark.parametrize("entryId", ["context7", "github"])
def test_nonAdminCannotInstallCatalog(registryEnv, entryId):
    manager, client, _ = registryEnv
    with _client("user") as http:
        response = http.post(
            f"{BASE}/mcp-catalog/{entryId}/install", json={"secrets": {}}
        )
    assert response.status_code == 403
    assert manager.items == {}
    assert client.connectCalls == []


def test_duplicateIdCannotReplaceClientOrAttach(registryEnv):
    manager, client, state = registryEnv
    with _client() as http:
        first = http.post(f"{BASE}/mcp-servers", json=_httpConfig())
        assert first.status_code == 200, first.text
        firstClient = mcp_bootstrap.get_bootstrapped_clients()["runtime"]
        second = http.post(
            f"{BASE}/mcp-servers",
            json=_httpConfig(url="https://attacker.example/mcp"),
        )
    assert second.status_code == 409, second.text
    assert len(client.connectCalls) == 1
    assert manager.items["runtime"]["url"] == "https://example.com/mcp"
    assert mcp_bootstrap.get_bootstrapped_clients()["runtime"] is firstClient
    assert set(state.agents["agent_admin"].tool_router.registered) == {"runtime"}
    assert state.agents["agent_bob"].tool_router.registered == {}


def test_registerClientDuplicateFailsWithoutOverwrite(registryEnv):
    first = object()
    mcp_bootstrap.register_client("duplicate", first, owner_id="u_admin")
    with pytest.raises(ValueError, match="已注册"):
        mcp_bootstrap.register_client("duplicate", object(), owner_id="u_bob")
    assert mcp_bootstrap.get_bootstrapped_clients()["duplicate"] is first
    assert mcp_bootstrap.get_server_owner("duplicate") == "u_admin"


def test_runtimeAttachRequiresOwnerAndFiltersFutureAgents(registryEnv):
    client = object()
    with pytest.raises(ValueError, match="owner_id"):
        mcp_bootstrap.attach_server_to_running_agents(
            "missing_owner", client, registryEnv[2]
        )

    mcp_bootstrap.register_client("owned", client, owner_id="u_admin")
    bobRouter = FakeRouter()
    bobAgent = SimpleNamespace(config=SimpleNamespace(owner_user_id="u_bob"))
    bobRouter._tool_executor = SimpleNamespace(_agent=bobAgent)
    assert mcp_bootstrap.attach_bootstrapped_clients(bobRouter) == 0
    assert bobRouter.registered == {}

    adminRouter = FakeRouter()
    adminAgent = SimpleNamespace(config=SimpleNamespace(owner_user_id="u_admin"))
    adminRouter._tool_executor = SimpleNamespace(_agent=adminAgent)
    assert mcp_bootstrap.attach_bootstrapped_clients(adminRouter, agent=adminAgent) == 1
    assert adminRouter.registered == {"owned": client}


def test_bootstrapDuplicateServerIdConnectsOnlyFirst(monkeypatch):
    class ConfigManager:
        def list_mcp_servers(self):
            return [
                {
                    "id": "duplicate",
                    "name": "first",
                    "transport": "http",
                    "url": "https://first.example/mcp",
                    "enabled": True,
                },
                {
                    "id": "duplicate",
                    "name": "second",
                    "transport": "http",
                    "url": "https://second.example/mcp",
                    "enabled": True,
                },
            ]

    created = []

    class RecordingClient(FakeClient):
        def __init__(self):
            super().__init__()
            created.append(self)

    mcp_bootstrap.reset_bootstrap()
    monkeypatch.setattr(mcp_bootstrap, "MCPToolClient", RecordingClient)
    results = asyncio.run(mcp_bootstrap.bootstrap_mcp(ConfigManager()))
    mcp_bootstrap.reset_bootstrap()
    assert results == {"duplicate": True}
    assert len(created) == 1, "重复全局 ID 不得建立第二条会话"
    assert created[0].connectCalls[0][1]["url"] == "https://first.example/mcp"


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", f"{BASE}/mcp-servers/runtime/test"),
        ("delete", f"{BASE}/mcp-servers/runtime"),
        ("post", f"{BASE}/mcp-servers/runtime/oauth/authorize"),
    ],
)
def test_nonAdminCannotReconnectAuthorizeOrDelete(registryEnv, method, path):
    manager, client, _ = registryEnv
    manager.items["runtime"] = {
        "id": "runtime",
        "name": "runtime",
        "transport": "http",
        "url": "https://example.com/mcp",
        "oauth": {"grant_type": "authorization_code"},
    }
    with _client("user") as http:
        response = getattr(http, method)(path)
    assert response.status_code == 403
    assert client.connectCalls == []
    assert "runtime" in manager.items


def test_runtimeMcpExecutionUsesRegisteredOwner(registryEnv, monkeypatch):
    manager, _, _ = registryEnv
    manager.items["runtime"] = _httpConfig()
    mcp_bootstrap.register_client("runtime", object(), owner_id="u_admin")
    toolDef = SimpleNamespace(
        name="mcp.runtime.lookup",
        tags=["mcp", "runtime"],
        is_public=False,
        owner=None,
    )
    monkeypatch.setattr(
        tool_layers,
        "get_tool_engine",
        lambda: SimpleNamespace(get_tool=lambda name: toolDef),
    )
    bob = {"user_id": "u_bob", "role": "user"}
    assert tool_layers._executeOwnershipGate(toolDef.name, bob) is not None
    assert tool_layers._executeOwnershipGate(
        toolDef.name, {"user_id": "u_admin", "role": "admin"}
    ) is None


def test_appMountRetainsOntologyAsgiForLifespan():
    import neurova.api.app as appMod
    import neurova.api.endpoints as endpointsMod

    savedInstance = appMod._app_instance
    savedState = appMod._app_state
    savedEndpoints = endpointsMod.get_app_state()
    try:
        appMod.create_app()
        assert appMod._app_state.ontology_mcp_asgi is not None, (
            "挂载后的 ASGI 必须留给 startup lifespan，否则真实 MCP 链路无法启动"
        )
    finally:
        appMod._app_instance = savedInstance
        appMod._app_state = savedState
        endpointsMod.set_app_state(savedEndpoints)


def test_backgroundBootstrapPassesConcreteAgentOwner(monkeypatch):
    from neurova.api.app import AppState, _schedule_mcp_bootstrap

    attached = []

    async def bootstrap():
        return {}

    def attach(router, **kwargs):
        attached.append(kwargs)
        return 0

    monkeypatch.setattr(mcp_bootstrap, "bootstrap_mcp", bootstrap)
    monkeypatch.setattr(mcp_bootstrap, "attach_bootstrapped_clients", attach)
    agent = SimpleNamespace(
        config=SimpleNamespace(owner_user_id="u_admin"),
        tool_router=FakeRouter(),
    )
    state = AppState()
    state.agents["agent_admin"] = agent

    async def scenario():
        task = _schedule_mcp_bootstrap(state)
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())
    assert attached == [{"agent": agent}]
