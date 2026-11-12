"""P2-6 /tools/execute 属主门红测（全库断点审计 2026-11-12）

证据（审计 P2-6）：tool_layers.py execute_tool 无 current_user——router 级
get_current_user 只挡匿名，任何登录用户可点名执行 admin 注册的 stdio MCP
工具（本机进程派生面），横向越权。

修复口径（审计开方"取 current_user 对动态/MCP 工具按注册属主校验"）：
- stdio MCP 工具 → 仅 admin（注册门已保证 stdio 只可能出自 admin，执行面同口径）；
- MCP server 配置缺失 → 非 admin fail-closed 403；
- 带 owner 的动态工具 → 属主本人或 admin；
- public / 无属主动态 / http(sse) MCP → 登录即可（与聊天链可见性一致）。

基建：引擎/共享配置/agent/治理全替身，只测属主门本身。
"""

import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_p2-6_execute_ownership")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_p2-6_execute_ownership")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints import tool_layers

BASE = "/v1/tool-layers"


class FakeToolDef:
    def __init__(self, tags=None, owner="", is_public=False):
        self.tags = tags or []
        self.owner = owner
        self.is_public = is_public
        self.name = "t"
        self.description = ""
        self.parameters = []


class FakeEngine:
    def __init__(self, tool_def=None):
        self._tool_def = tool_def

    def get_tool(self, name):
        return self._tool_def

    async def execute_with_safeguards(self, tool_name, parameters, timeout):
        return {"ok": True}


class FakeConfigManager:
    def __init__(self, servers=None):
        self._servers = servers or {}

    def get_mcp_server(self, sid):
        return self._servers.get(sid)


@pytest.fixture
def wired(monkeypatch):
    """默认装配：无 agent（走引擎直调支）＋治理放行＋空 server 表"""

    def _install(engine=None, servers=None):
        fake_engine = engine or FakeEngine()
        monkeypatch.setattr(tool_layers, "get_tool_engine", lambda: fake_engine)
        monkeypatch.setattr(
            "neurova.api.endpoints.get_agent_instance", lambda: None
        )
        import neurova.security.governance as governance_mod

        monkeypatch.setattr(
            governance_mod, "get_governance", lambda: type(
                "G", (), {"evaluate_tool_call": staticmethod(lambda *a, **k: None)}
            )()
        )
        import neurova.shared_config as shared_config_mod

        manager = FakeConfigManager(servers)
        monkeypatch.setattr(
            shared_config_mod, "get_shared_config_manager", lambda: manager
        )
        return fake_engine

    return _install


def _client(app, role):
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u_user" if role == "user" else f"u_{role}",
        "username": f"user_{role}",
        "role": role,
        "neuser_id": f"ne_{role}",
    }
    return TestClient(app)


def _execute(client, tool_name):
    return client.post(
        f"{BASE}/tools/execute",
        json={"tool_name": tool_name, "arguments": {}},
    )


# ── 1. stdio MCP 工具：普通用户必须 403（红态：200 放行） ──────────


class TestStdioMcpAdminOnly:
    def test_user_cannot_execute_stdio_mcp_tool(self, wired):
        wired(
            engine=FakeEngine(FakeToolDef(tags=["mcp", "srv_local"])),
            servers={"srv_local": {"id": "srv_local", "transport": "stdio"}},
        )
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        assert _execute(_client(app, "user"), "mcp.srv_local.run").status_code == 403

    def test_user_fail_closed_when_server_config_missing(self, wired):
        wired(engine=FakeEngine(FakeToolDef(tags=["mcp", "gone"])), servers={})
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        assert _execute(_client(app, "user"), "mcp.gone.run").status_code == 403

    def test_admin_can_execute_stdio_mcp_tool(self, wired):
        wired(
            engine=FakeEngine(FakeToolDef(tags=["mcp", "srv_local"])),
            servers={"srv_local": {"id": "srv_local", "transport": "stdio"}},
        )
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        resp = _execute(_client(app, "admin"), "mcp.srv_local.run")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0


# ── 2. 带 owner 的动态工具：属主本人或 admin ───────────────────────


class TestOwnedDynamicTool:
    def test_user_cannot_execute_others_tool(self, wired):
        wired(engine=FakeEngine(FakeToolDef(owner="someone_else")))
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        assert _execute(_client(app, "user"), "custom_tool").status_code == 403

    def test_owner_can_execute_own_tool(self, wired):
        wired(engine=FakeEngine(FakeToolDef(owner="u_user")))
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        resp = _execute(_client(app, "user"), "custom_tool")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0

    def test_admin_can_execute_any_owned_tool(self, wired):
        wired(engine=FakeEngine(FakeToolDef(owner="someone_else")))
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        assert _execute(_client(app, "admin"), "custom_tool").status_code == 200


# ── 3. 不过度收权：public / 无属主动态 / http MCP 登录即可 ─────────


class TestUnrestrictedSourcesStayOpen:
    def test_public_tool_ok_for_user(self, wired):
        wired(engine=FakeEngine(FakeToolDef(is_public=True)))
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        assert _execute(_client(app, "user"), "pub_tool").status_code == 200

    def test_ownerless_dynamic_tool_ok_for_user(self, wired):
        wired(engine=FakeEngine(FakeToolDef()))
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        assert _execute(_client(app, "user"), "dyn_tool").status_code == 200

    def test_http_mcp_tool_ok_for_user(self, wired):
        wired(
            engine=FakeEngine(FakeToolDef(tags=["mcp", "srv_http"])),
            servers={"srv_http": {"id": "srv_http", "transport": "http"}},
        )
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        assert _execute(_client(app, "user"), "mcp.srv_http.call").status_code == 200

    def test_tool_not_in_engine_unchanged(self, wired):
        """引擎查无此工具（builtin 等真内置来源）不在此判，走原执行路径"""
        wired(engine=FakeEngine(None))
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        resp = _execute(_client(app, "user"), "builtin_calc")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
