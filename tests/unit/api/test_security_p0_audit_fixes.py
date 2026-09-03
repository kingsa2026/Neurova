"""
P0 安全审计修复测试（代码审计 2026-08）

覆盖:
1. computer API 未认证 RCE/任意文件读写 → 全部端点要求认证
2. shared_config API 未认证配置接管 + API Key 明文泄露 → 要求认证 + 响应掩码
3. settings API 未认证 CORS/设置篡改 → 写操作要求认证（读保持公开）
4. sandbox API 未认证访问 → 要求认证
5. logs_api 未认证访问 → 要求认证
6. files_api 路径穿越（agent_id/session_id 未净化）→ 400
7. files_api IDOR（跨用户文件操作）→ 404
8. _on_shutdown 中 agent.shutdown() 挂起导致服务无法退出 → 超时保护
"""

import asyncio
import os
import time
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api import auth
from neurova.api.endpoints import computer, files_api, logs_api, sandbox, settings, shared_config


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def auth_headers():
    token = auth.create_access_token({"sub": "user123", "username": "testuser", "role": "user"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_user_headers():
    token = auth.create_access_token({"sub": "attacker456", "username": "attacker", "role": "user"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def computer_client():
    app = FastAPI()
    app.include_router(computer.router, prefix="/v1/computer")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def shared_config_client():
    saved = dict(shared_config._shared_config)
    app = FastAPI()
    app.include_router(shared_config.router, prefix="/v1/shared-config")
    yield TestClient(app, raise_server_exceptions=False)
    shared_config._shared_config.clear()
    shared_config._shared_config.update(saved)


@pytest.fixture
def settings_client():
    saved_settings = dict(settings._default_settings)
    app = FastAPI()
    app.include_router(settings.router)
    yield TestClient(app, raise_server_exceptions=False)
    settings._default_settings.clear()
    settings._default_settings.update(saved_settings)


@pytest.fixture
def settings_admin_client(settings_client):
    """带 admin 认证的 settings 客户端（2026-08-31 收紧：读=登录、写=admin）"""
    from neurova.api.deps import get_current_user

    settings_client.app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "admin_user", "username": "adminuser", "role": "admin",
    }
    yield settings_client
    settings_client.app.dependency_overrides.clear()


@pytest.fixture
def sandbox_client():
    saved = dict(sandbox._SANDBOXES)
    sandbox._SANDBOXES.clear()
    app = FastAPI()
    app.include_router(sandbox.router, prefix="/v1/sandbox")
    yield TestClient(app, raise_server_exceptions=False)
    sandbox._SANDBOXES.clear()
    sandbox._SANDBOXES.update(saved)


@pytest.fixture
def logs_client():
    app = FastAPI()
    app.include_router(logs_api.router, prefix="/v1/logs-api")
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def files_client(tmp_path, monkeypatch):
    monkeypatch.setattr(files_api, "STORAGE_ROOT", tmp_path / "storage" / "users")
    saved = files_api._files_store.copy()
    files_api._files_store.clear()
    app = FastAPI()
    app.include_router(files_api.router, prefix="/v1/files")
    yield TestClient(app, raise_server_exceptions=False)
    files_api._files_store.clear()
    files_api._files_store.update(saved)


# ── 1. computer API 认证 ────────────────────────────────


class TestComputerAuth:
    def test_shell_without_auth_returns_401(self, computer_client):
        r = computer_client.post("/v1/computer/shell", json={"command": "echo pwned"})
        assert r.status_code == 401

    def test_file_read_without_auth_returns_401(self, computer_client):
        r = computer_client.post("/v1/computer/file/read", json={"path": "secret.txt"})
        assert r.status_code == 401

    def test_file_write_without_auth_returns_401(self, computer_client):
        r = computer_client.post("/v1/computer/file/write", json={"path": "evil.py", "content": "x"})
        assert r.status_code == 401

    def test_screenshot_without_auth_returns_401(self, computer_client):
        r = computer_client.post("/v1/computer/screenshot", json={})
        assert r.status_code == 401

    def test_shell_with_auth_not_401(self, computer_client, auth_headers, tmp_path):
        r = computer_client.post(
            "/v1/computer/shell", json={"command": "echo ok"}, headers=auth_headers
        )
        assert r.status_code != 401

    def test_file_write_read_with_auth(self, computer_client, auth_headers, tmp_path):
        target = tmp_path / "rw_test.txt"
        w = computer_client.post(
            "/v1/computer/file/write",
            json={"path": str(target), "content": "hello"},
            headers=auth_headers,
        )
        assert w.status_code != 401
        r = computer_client.post(
            "/v1/computer/file/read", json={"path": str(target)}, headers=auth_headers
        )
        assert r.status_code != 401


# ── 2. shared_config 认证 + 密钥掩码 ────────────────────


class TestSharedConfigAuth:
    def test_get_config_without_auth_returns_401(self, shared_config_client):
        assert shared_config_client.get("/v1/shared-config/").status_code == 401

    def test_put_config_without_auth_returns_401(self, shared_config_client):
        r = shared_config_client.put("/v1/shared-config/", json={"llm_providers": {}})
        assert r.status_code == 401

    def test_list_providers_without_auth_returns_401(self, shared_config_client):
        assert shared_config_client.get("/v1/shared-config/llm-providers").status_code == 401

    def test_add_provider_without_auth_returns_401(self, shared_config_client):
        r = shared_config_client.post(
            "/v1/shared-config/llm-providers", json={"name": "evil", "api_key": "sk-x"}
        )
        assert r.status_code == 401

    def test_update_provider_without_auth_returns_401(self, shared_config_client):
        r = shared_config_client.put(
            "/v1/shared-config/llm-providers/openai", json={"name": "openai"}
        )
        assert r.status_code == 401

    def test_delete_provider_without_auth_returns_401(self, shared_config_client):
        assert shared_config_client.delete("/v1/shared-config/llm-providers/openai").status_code == 401

    def test_mcp_list_without_auth_returns_401(self, shared_config_client):
        assert shared_config_client.get("/v1/shared-config/mcp-servers").status_code == 401

    def test_mcp_add_without_auth_returns_401(self, shared_config_client):
        r = shared_config_client.post(
            "/v1/shared-config/mcp-servers", json={"name": "evil", "command": "rm -rf /"}
        )
        assert r.status_code == 401

    def test_export_without_auth_returns_401(self, shared_config_client):
        assert shared_config_client.get("/v1/shared-config/export").status_code == 401

    def test_import_without_auth_returns_401(self, shared_config_client):
        r = shared_config_client.post(
            "/v1/shared-config/import", json={"config": {"llm_providers": {}}, "overwrite": True}
        )
        assert r.status_code == 401

    def test_get_config_with_auth_not_401(self, shared_config_client, auth_headers):
        r = shared_config_client.get("/v1/shared-config/", headers=auth_headers)
        assert r.status_code != 401

    def test_get_config_masks_api_key(self, shared_config_client, auth_headers):
        shared_config._shared_config["llm_providers"]["prov"] = {
            "name": "prov",
            "api_key": "sk-supersecret123456",
            "base_url": "https://api.example.com",
        }
        r = shared_config_client.get("/v1/shared-config/", headers=auth_headers)
        assert r.status_code == 200
        assert "sk-supersecret123456" not in r.text

    def test_list_providers_masks_api_key(self, shared_config_client, auth_headers):
        shared_config._shared_config["llm_providers"]["prov"] = {
            "name": "prov",
            "api_key": "sk-supersecret123456",
        }
        r = shared_config_client.get("/v1/shared-config/llm-providers", headers=auth_headers)
        assert r.status_code == 200
        assert "sk-supersecret123456" not in r.text

    def test_get_provider_detail_masks_api_key(self, shared_config_client, auth_headers):
        shared_config._shared_config["llm_providers"]["prov"] = {
            "name": "prov",
            "api_key": "sk-supersecret123456",
        }
        r = shared_config_client.get("/v1/shared-config/llm-providers/prov", headers=auth_headers)
        assert r.status_code == 200
        assert "sk-supersecret123456" not in r.text

    def test_masking_does_not_mutate_store(self, shared_config_client, auth_headers):
        shared_config._shared_config["llm_providers"]["prov"] = {
            "name": "prov",
            "api_key": "sk-supersecret123456",
        }
        shared_config_client.get("/v1/shared-config/", headers=auth_headers)
        assert shared_config._shared_config["llm_providers"]["prov"]["api_key"] == "sk-supersecret123456"


# ── 3. settings 写操作认证 ──────────────────────────────


class TestSettingsAuth:
    def test_get_settings_without_auth_returns_401(self, settings_client):
        assert settings_client.get("/v1/settings").status_code == 401

    def test_get_settings_with_auth_ok(self, settings_admin_client):
        assert settings_admin_client.get("/v1/settings").status_code == 200

    def test_get_cors_without_auth_returns_401(self, settings_client):
        assert settings_client.get("/v1/settings/cors").status_code == 401

    def test_put_settings_without_auth_returns_401(self, settings_client):
        r = settings_client.put("/v1/settings", json={"settings": {"theme": "light"}})
        assert r.status_code == 401

    def test_put_cors_without_auth_returns_401(self, settings_client):
        r = settings_client.put(
            "/v1/settings/cors", json={"origins": ["https://evil.example.com"]}
        )
        assert r.status_code == 401

    def test_put_setting_key_without_auth_returns_401(self, settings_client):
        r = settings_client.put("/v1/settings/theme", json="light")
        assert r.status_code == 401

    def test_put_settings_as_admin_not_401(self, settings_admin_client):
        r = settings_admin_client.put(
            "/v1/settings", json={"settings": {"theme": "light"}}
        )
        assert r.status_code != 401


# ── 4. sandbox 认证 ─────────────────────────────────────


class TestSandboxAuth:
    def test_list_without_auth_returns_401(self, sandbox_client):
        assert sandbox_client.get("/v1/sandbox").status_code == 401

    def test_start_without_auth_returns_401(self, sandbox_client):
        r = sandbox_client.post(
            "/v1/sandbox/start", json={"agent_id": "default", "topic": "t"}
        )
        assert r.status_code == 401

    def test_status_without_auth_returns_401(self, sandbox_client):
        assert sandbox_client.get("/v1/sandbox/some-id").status_code == 401

    def test_commit_without_auth_returns_401(self, sandbox_client):
        r = sandbox_client.post(
            "/v1/sandbox/some-id/commit", json={"conclusion": "injected"}
        )
        assert r.status_code == 401

    def test_delete_without_auth_returns_401(self, sandbox_client):
        assert sandbox_client.delete("/v1/sandbox/some-id").status_code == 401

    def test_start_with_auth_not_401(self, sandbox_client, auth_headers):
        r = sandbox_client.post(
            "/v1/sandbox/start",
            json={"agent_id": "default", "topic": "t"},
            headers=auth_headers,
        )
        assert r.status_code != 401


# ── 5. logs_api 认证 ────────────────────────────────────


class TestLogsApiAuth:
    def test_create_without_auth_returns_401(self, logs_client):
        r = logs_client.post("/v1/logs-api", json={"title": "x"})
        assert r.status_code == 401

    def test_list_without_auth_returns_401(self, logs_client):
        assert logs_client.get("/v1/logs-api").status_code == 401

    def test_daily_summary_without_auth_returns_401(self, logs_client):
        assert logs_client.get("/v1/logs-api/daily-summary").status_code == 401

    def test_export_without_auth_returns_401(self, logs_client):
        assert logs_client.get("/v1/logs-api/export").status_code == 401

    def test_list_with_auth_not_401(self, logs_client, auth_headers):
        r = logs_client.get("/v1/logs-api", headers=auth_headers)
        assert r.status_code != 401


# ── 6. files_api 路径穿越 ───────────────────────────────


class TestFilesPathTraversal:
    def test_upload_with_traversal_agent_id_rejected(self, files_client, auth_headers, tmp_path):
        r = files_client.post(
            "/v1/files/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
            params={"agent_id": "../../escape", "session_id": "default"},
            headers=auth_headers,
        )
        assert r.status_code == 400
        escaped = tmp_path / "storage" / "escape"
        assert not escaped.exists()

    def test_upload_with_traversal_session_id_rejected(self, files_client, auth_headers, tmp_path):
        r = files_client.post(
            "/v1/files/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
            params={"agent_id": "default", "session_id": "..%2F..%2Fescape"},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_upload_with_normal_ids_still_works(self, files_client, auth_headers):
        r = files_client.post(
            "/v1/files/upload",
            files={"file": ("test.txt", b"hello", "text/plain")},
            params={"agent_id": "agent-1", "session_id": "sess_01"},
            headers=auth_headers,
        )
        assert r.status_code == 200


# ── 7. files_api IDOR ───────────────────────────────────


class TestFilesIDOR:
    @pytest.fixture
    def victim_file_id(self, files_client, auth_headers):
        r = files_client.post(
            "/v1/files/upload",
            files={"file": ("private.txt", b"secret data", "text/plain")},
            headers=auth_headers,
        )
        assert r.status_code == 200
        return r.json()["file_id"]

    def test_other_user_cannot_get_info(self, files_client, other_user_headers, victim_file_id):
        r = files_client.get(f"/v1/files/{victim_file_id}", headers=other_user_headers)
        assert r.status_code == 404

    def test_other_user_cannot_download(self, files_client, other_user_headers, victim_file_id):
        r = files_client.get(f"/v1/files/{victim_file_id}/download", headers=other_user_headers)
        assert r.status_code == 404

    def test_other_user_cannot_preview(self, files_client, other_user_headers, victim_file_id):
        r = files_client.get(f"/v1/files/{victim_file_id}/preview", headers=other_user_headers)
        assert r.status_code == 404

    def test_other_user_cannot_update(self, files_client, other_user_headers, victim_file_id):
        r = files_client.put(
            f"/v1/files/{victim_file_id}", json={"filename": "hacked.txt"}, headers=other_user_headers
        )
        assert r.status_code == 404

    def test_other_user_cannot_delete(self, files_client, other_user_headers, victim_file_id):
        r = files_client.delete(f"/v1/files/{victim_file_id}", headers=other_user_headers)
        assert r.status_code == 404
        assert victim_file_id in files_api._files_store

    def test_other_user_cannot_approve(self, files_client, other_user_headers, victim_file_id):
        r = files_client.post(f"/v1/files/{victim_file_id}/approve", headers=other_user_headers)
        assert r.status_code == 404

    def test_owner_can_still_access(self, files_client, auth_headers, victim_file_id):
        r = files_client.get(f"/v1/files/{victim_file_id}", headers=auth_headers)
        assert r.status_code == 200


# ── 8. shutdown 超时保护 ────────────────────────────────


class TestShutdownTimeout:
    @pytest.mark.asyncio
    async def test_on_shutdown_survives_hanging_agent(self, monkeypatch):
        from neurova.api import app as app_module

        monkeypatch.setattr(app_module, "AGENT_SHUTDOWN_TIMEOUT", 0.3)
        state = app_module.AppState()

        class HangingAgent:
            async def shutdown(self):
                await asyncio.sleep(3600)

        state.agents["hang"] = HangingAgent()

        start = time.monotonic()
        await asyncio.wait_for(app_module._on_shutdown(state), timeout=5)
        elapsed = time.monotonic() - start
        assert elapsed < 5, f"_on_shutdown 被挂起的 agent 阻塞了 {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_on_shutdown_still_calls_normal_agent_shutdown(self, monkeypatch):
        from neurova.api import app as app_module

        monkeypatch.setattr(app_module, "AGENT_SHUTDOWN_TIMEOUT", 5)
        state = app_module.AppState()
        called = []

        class GoodAgent:
            async def shutdown(self):
                called.append(True)

        state.agents["good"] = GoodAgent()
        await asyncio.wait_for(app_module._on_shutdown(state), timeout=10)
        assert called == [True]
