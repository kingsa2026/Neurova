"""
P0-1 MCP 管理 API 鉴权与输入校验红测

RCE 面证据（评测文档 M1，tool_layers.py:27）：
- router = APIRouter() 无鉴权依赖 → 未认证 POST /v1/tool-layers/mcp-servers
  可注册任意 command+args+env 并被 stdio spawn = 未认证 RCE
- http/sse url 无私网校验 = 已认证低权用户可借 MCP 探测内网（SSRF）

修复设计（对评测计划的白名单方案有一处修正，理由见实现 commit）：
- 路由级鉴权（get_current_user）
- stdio 传输 = 本机进程派生面，仅限 admin 角色（解释器类白名单
  如 npx/python 本身就能执行任意代码，属安全剧场；真正的边界是角色）
- 非 admin 的 http/sse 配置拒绝私网 URL（admin 豁免，保住自托管
  localhost MCP 场景）；shell 类 command 任何角色都拒绝
"""

import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_for_p0-1_tool_layers_auth")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_for_p0-1_tool_layers_auth")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import tool_layers

BASE = "/v1/tool-layers"


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(tool_layers.router, prefix=BASE)
    yield app


@pytest.fixture
def anon_client(app):
    """不覆盖鉴权依赖 → 走真实 get_current_user"""
    with TestClient(app) as c:
        yield c


def _authed_client(app, role):
    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": f"u_{role}",
        "username": f"user_{role}",
        "role": role,
        "neuser_id": f"ne_{role}",
    }
    return TestClient(app)


@pytest.fixture
def isolated_env(monkeypatch):
    """隔离持久化与真实连接：FakeManager/FakeClient 替身"""

    class FakeManager:
        def __init__(self):
            self.items = {}

        def add_mcp_server(self, cfg):
            self.items[cfg["id"]] = cfg
            return True

        def get_mcp_server(self, sid):
            return self.items.get(sid)

        def list_mcp_servers(self):
            return list(self.items.values())

        def remove_mcp_server(self, sid):
            return self.items.pop(sid, None) is not None

    class FakeClient:
        def __init__(self):
            self.connected = {}

        async def connect_server(self, sid, cfg):
            self.connected[sid] = cfg
            return True

        async def disconnect_server(self, sid):
            return self.connected.pop(sid, None) is not None

        def get_server_status(self, sid):
            cfg = self.connected.get(sid) or {}
            return {
                "server_id": sid,
                "connected": sid in self.connected,
                "last_error": None,
                "tool_count": 0,
                "transport": cfg.get("transport"),
            }

    manager, client = FakeManager(), FakeClient()
    monkeypatch.setattr(
        "neurova.shared_config.get_shared_config_manager", lambda: manager
    )
    monkeypatch.setattr(
        "neurova.tool_layers.mcp_client.get_mcp_client", lambda user_id=None: client
    )
    return manager, client


# ── 1. 未认证访问必须 401（RCE 主修复点） ─────────────────────────


class TestAuthRequired:
    def test_connect_mcp_server_without_token_401(self, anon_client, isolated_env):
        # isolated_env 随行：红态（无鉴权）下请求会穿透到真实 handler，
        # 持久化配置并 spawn 进程（本测试最初的实测事故）
        resp = anon_client.post(
            f"{BASE}/mcp-servers",
            json={"name": "evil", "command": "bash", "args": ["-c", "id"]},
        )
        assert resp.status_code == 401

    def test_disconnect_without_token_401(self, anon_client, isolated_env):
        assert anon_client.delete(f"{BASE}/mcp-servers/anything").status_code == 401

    def test_list_mcp_servers_without_token_401(self, anon_client, isolated_env):
        assert anon_client.get(f"{BASE}/mcp-servers").status_code == 401

    def test_execute_tool_without_token_401(self, anon_client, isolated_env):
        resp = anon_client.post(
            f"{BASE}/tools/execute",
            json={"tool_name": "calculator", "arguments": {"expr": "1+1"}},
        )
        assert resp.status_code == 401

    def test_list_tools_without_token_401(self, anon_client, isolated_env):
        assert anon_client.get(f"{BASE}/tools").status_code == 401


# ── 2. 角色边界：stdio（本机进程派生）仅限 admin ─────────────────


class TestStdioRoleGate:
    def test_stdio_rejected_for_user_role_403(self, isolated_env):
        # isolated_env 必须随行：红态（角色门未实现）下请求会打到真实
        # connect_server 并 spawn npx 进程 + 污染 shared_config.json
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        client = _authed_client(app, "user")
        with client:
            resp = client.post(
                f"{BASE}/mcp-servers",
                json={
                    "name": "fs",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                },
            )
        assert resp.status_code == 403

    def test_stdio_accepted_for_admin(self, isolated_env):
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        client = _authed_client(app, "admin")
        manager, _ = isolated_env
        with client:
            resp = client.post(
                f"{BASE}/mcp-servers",
                json={
                    "name": "fs",
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                },
            )
        assert resp.status_code == 200
        assert resp.json()["server_id"] == "fs"
        assert "fs" in manager.items


# ── 3. shell 类 command 任何角色都拒绝 ────────────────────────────


class TestShellCommandDenylist:
    @pytest.mark.parametrize("command", ["bash", "sh", "cmd", "powershell"])
    def test_shell_command_rejected_400(self, command, isolated_env):
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        client = _authed_client(app, "admin")
        with client:
            resp = client.post(
                f"{BASE}/mcp-servers",
                json={"name": "shell", "command": command, "args": ["-c", "id"]},
            )
        assert resp.status_code == 400
        assert "shell" in resp.json()["detail"]


# ── 4. 非 admin 的 http/sse 拒绝私网 URL（admin 豁免） ────────────


class TestPrivateUrlGate:
    def test_private_url_rejected_for_user_400(self, isolated_env):
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        client = _authed_client(app, "user")
        with client:
            resp = client.post(
                f"{BASE}/mcp-servers",
                json={"name": "local", "transport": "http", "url": "http://127.0.0.1:9000/mcp"},
            )
        assert resp.status_code == 400

    def test_private_url_allowed_for_admin(self, isolated_env):
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        client = _authed_client(app, "admin")
        with client:
            resp = client.post(
                f"{BASE}/mcp-servers",
                json={"name": "local", "transport": "http", "url": "http://127.0.0.1:9000/mcp"},
            )
        assert resp.status_code == 200

    def test_public_url_ok_for_user(self, isolated_env):
        app = FastAPI()
        app.include_router(tool_layers.router, prefix=BASE)
        client = _authed_client(app, "user")
        with client:
            resp = client.post(
                f"{BASE}/mcp-servers",
                json={"name": "remote", "transport": "http", "url": "http://8.8.8.8:9000/mcp"},
            )
        assert resp.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
