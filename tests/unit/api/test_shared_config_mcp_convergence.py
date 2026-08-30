"""
P0-4 配置收敛 + 掩码红测（评测 M7/M10/M12）

原缺陷：
- M7: /shared-config/mcp-servers CRUD 用纯内存 dict（永不持久化，通过该
  界面加的 server 对 bootstrap 完全不可见），与 tool-layers 的
  SharedConfigManager(data/shared_config.json) 分叉
- M10: 掩码只盖 env，headers（Authorization 等）明文返回
- M12: 前端文档写 streamable_http，mcp_config 只认 stdio/http/sse

修复语义：
- /shared-config MCP CRUD 收敛为 SharedConfigManager 薄壳（同一持久化存储）
- 掩码覆盖 env（全掩，既有语义）+ headers（敏感键名：authorization/
  token/secret/key/password/cookie）
- transport 别名 streamable_http → http 归一化
- 角色门与 tool-layers 对齐：stdio 仅限 admin（收敛后此端点也持久化
  stdio 配置，不能成为新的最弱环节）
"""

import os

os.environ.setdefault("NEUROVA_JWT_SECRET", "test_secret_p0_4_convergence")
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_p0_4_convergence")

import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import shared_config as sc_module
from neurova.tool_layers.mcp_config import validate_mcp_server_config

MASKED = "***REDACTED***"
BASE = "/v1/shared-config"


@pytest.fixture
def iso_manager(monkeypatch, tmp_path):
    """Manager 指向 tmp_path，隔离真实 data/shared_config.json"""
    import neurova.shared_config as sc

    manager = sc.SharedConfigManager(tmp_path / "cfg.json")
    monkeypatch.setattr(sc, "get_shared_config_manager", lambda: manager)
    yield manager
    sc.reset_shared_config_manager()


def _authed_client(role="admin"):
    app = FastAPI()
    app.include_router(sc_module.router, prefix=BASE)
    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": f"u_{role}",
        "username": f"user_{role}",
        "role": role,
        "neuser_id": f"ne_{role}",
    }
    return TestClient(app)


# ── 1. schema 校验前置（400 带指名原因） ─────────────────────────


class TestSchemaValidation:
    def test_add_http_without_url_rejected_400(self, iso_manager):
        resp = _authed_client().post(
            f"{BASE}/mcp-servers",
            json={"name": "bad", "transport": "http", "url": ""},
        )
        assert resp.status_code == 400
        assert "url" in resp.json()["detail"]

    def test_add_invalid_transport_rejected_400(self, iso_manager):
        resp = _authed_client().post(
            f"{BASE}/mcp-servers",
            json={"name": "bad", "transport": "carrier-pigeon", "command": "npx"},
        )
        assert resp.status_code == 400
        assert "transport" in resp.json()["detail"]

    def test_add_shell_command_rejected_400(self, iso_manager):
        resp = _authed_client().post(
            f"{BASE}/mcp-servers",
            json={"name": "sh", "command": "bash", "args": ["-c", "id"]},
        )
        assert resp.status_code == 400
        assert "shell" in resp.json()["detail"]


# ── 2. 收敛：读写都走 SharedConfigManager（M7 核心） ─────────────


class TestManagerConvergence:
    def test_add_persists_to_manager(self, iso_manager):
        resp = _authed_client().post(
            f"{BASE}/mcp-servers",
            json={"name": "fs", "command": "npx", "args": ["-y", "srv"]},
        )
        assert resp.status_code == 200
        sid = resp.json()["data"]["id"]
        assert iso_manager.get_mcp_server(sid) is not None

    def test_get_lists_from_manager(self, iso_manager):
        client = _authed_client()
        client.post(f"{BASE}/mcp-servers", json={"name": "fs", "command": "npx"})
        resp = client.get(f"{BASE}/mcp-servers")
        data = resp.json()["data"]
        # Manager 默认模板自带 filesystem 条目，断言包含而非总数
        ids = [s["id"] for s in data["servers"]]
        assert "fs" in ids

    def test_export_includes_manager_servers(self, iso_manager):
        client = _authed_client()
        client.post(f"{BASE}/mcp-servers", json={"name": "fs", "command": "npx"})
        exported = client.get(f"{BASE}/export").json()["data"]
        # GET / 与 /export 保持 dict 键形（前端兼容）
        assert "fs" in exported.get("mcp_servers", {})

    def test_delete_goes_through_manager(self, iso_manager):
        client = _authed_client()
        client.post(f"{BASE}/mcp-servers", json={"name": "fs", "command": "npx"})
        assert client.delete(f"{BASE}/mcp-servers/fs").status_code == 200
        assert iso_manager.get_mcp_server("fs") is None
        assert client.delete(f"{BASE}/mcp-servers/fs").status_code == 404

    def test_add_duplicate_409(self, iso_manager):
        client = _authed_client()
        body = {"name": "fs", "command": "npx"}
        assert client.post(f"{BASE}/mcp-servers", json=body).status_code == 200
        assert client.post(f"{BASE}/mcp-servers", json=body).status_code == 409


# ── 3. 掩码：env 全掩（既有）+ headers 敏感键（M10） ─────────────


class TestMasking:
    def _add_server_with_secrets(self):
        client = _authed_client()
        resp = client.post(
            f"{BASE}/mcp-servers",
            json={
                "name": "web",
                "transport": "http",
                "url": "http://8.8.8.8:9000/mcp",
                "env": {"API_TOKEN": "env-secret"},
                "headers": {
                    "Authorization": "Bearer real-token",
                    "Content-Type": "application/json",
                },
            },
        )
        assert resp.status_code == 200
        return client, resp.json()["data"]

    def test_response_masks_env_and_sensitive_headers(self, iso_manager):
        _, data = self._add_server_with_secrets()
        assert data["env"]["API_TOKEN"] == MASKED
        assert data["headers"]["Authorization"] == MASKED
        # 非敏感头不掩（掩了前端没法回显 Content-Type）
        assert data["headers"]["Content-Type"] == "application/json"

    def test_get_masks_sensitive_headers(self, iso_manager):
        client, _ = self._add_server_with_secrets()
        data = client.get(f"{BASE}/mcp-servers/web").json()["data"]
        assert data["headers"]["Authorization"] == MASKED
        assert data["env"]["API_TOKEN"] == MASKED

    def test_update_masked_writeback_preserves_secrets(self, iso_manager):
        """前端回传掩码值时保留原值（env 既有语义扩展到 headers）"""
        client, _ = self._add_server_with_secrets()
        resp = client.put(
            f"{BASE}/mcp-servers/web",
            json={
                "name": "web",
                "transport": "http",
                "url": "http://8.8.8.8:9000/mcp",
                "env": {"API_TOKEN": MASKED},
                "headers": {"Authorization": MASKED},
            },
        )
        assert resp.status_code == 200
        stored = iso_manager.get_mcp_server("web")
        assert stored["env"]["API_TOKEN"] == "env-secret"
        assert stored["headers"]["Authorization"] == "Bearer real-token"


# ── 4. transport 别名归一化（M12） ───────────────────────────────


class TestTransportAlias:
    def test_unit_level_alias_normalized(self):
        cfg = validate_mcp_server_config(
            {"id": "s", "url": "http://8.8.8.8/mcp", "transport": "streamable_http"}
        )
        assert cfg["transport"] == "http"

    def test_endpoint_accepts_alias(self, iso_manager):
        client = _authed_client()
        resp = client.post(
            f"{BASE}/mcp-servers",
            json={"name": "remote", "transport": "streamable_http", "url": "http://8.8.8.8:9/mcp"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["transport"] == "http"

    def test_tool_layers_endpoint_accepts_alias(self, iso_manager, monkeypatch):
        """tool-layers 同一校验入口，别名行为一致（fake client 隔离真实连接）"""
        from neurova.api.endpoints import tool_layers as tl_module

        class _FakeClient:
            async def connect_server(self, sid, cfg):
                return True

            def get_server_status(self, sid):
                return {"server_id": sid, "connected": True, "last_error": None,
                        "tool_count": 0, "transport": (cfg_t.get("transport"))}

        cfg_t = {}
        monkeypatch.setattr(
            "neurova.tool_layers.mcp_client.get_mcp_client", lambda user_id=None: _FakeClient()
        )
        app = FastAPI()
        app.include_router(tl_module.router, prefix="/v1/tool-layers")
        from neurova.api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "admin", "username": "admin", "role": "admin", "neuser_id": "admin",
        }
        client = TestClient(app)
        resp = client.post(
            "/v1/tool-layers/mcp-servers",
            json={"name": "remote", "transport": "streamable_http", "url": "http://8.8.8.8:9/mcp"},
        )
        assert resp.status_code == 200
        assert resp.json()["transport"] == "http"


# ── 5. 角色门与 tool-layers 对齐（stdio 仅限 admin） ─────────────


class TestStdioRoleGate:
    def test_stdio_rejected_for_user_role_403(self, iso_manager):
        resp = _authed_client("user").post(
            f"{BASE}/mcp-servers",
            json={"name": "fs", "command": "npx"},
        )
        assert resp.status_code == 403

    def test_private_url_rejected_for_user_400(self, iso_manager):
        resp = _authed_client("user").post(
            f"{BASE}/mcp-servers",
            json={"name": "local", "transport": "http", "url": "http://127.0.0.1:9/mcp"},
        )
        assert resp.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
