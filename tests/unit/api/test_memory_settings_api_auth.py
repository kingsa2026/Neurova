"""
记忆设置 API 鉴权测试 — 全局配置仅管理员可写（2026-08-31）

背景：
- /v1/memory-settings 是进程级全局配置（settings_config 单例），此前所有端点
  （GET/PUT/import/reset）完全无鉴权，任何登录或匿名请求都能读写全系统记忆参数。
- 用户契约：此页面仅管理员可操作，普通用户不可操作。

契约：
1. 读端点（GET /settings、/settings/schema、/settings/{section}、/settings/export）
   要求登录（401 未认证）；
2. 写端点（PUT /settings、/settings/reset、/settings/import）要求 admin 角色：
   普通登录用户 403，admin 200；
3. 测试不触发完整 lifespan（最小 FastAPI 只挂 router，与 test_context_pool_settings_api 同约定）。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import memory_settings_api
from neurova.api.deps import get_current_user
from neurova.cognitive_layers.memory_layer.settings_config import (
    get_memory_settings,
    MemorySettingsConfig,
)

# 真实挂载: /api/v1/memory-settings + router 内路径 /settings[/...]
BASE = "/api/v1/memory-settings/settings"

MOCK_USER = {
    "user_id": "test_user",
    "username": "testuser",
    "role": "user",
}

MOCK_ADMIN = {
    "user_id": "admin_user",
    "username": "adminuser",
    "role": "admin",
}


@pytest.fixture
def client(tmp_path):
    """最小测试客户端：只挂 memory_settings router，隔离 settings 单例到 tmp 目录"""
    MemorySettingsConfig.reset_instance()
    get_memory_settings(str(tmp_path))

    app = FastAPI()
    app.include_router(memory_settings_api.router, prefix="/api/v1/memory-settings")
    with TestClient(app) as c:
        yield c

    MemorySettingsConfig.reset_instance()


@pytest.fixture
def user_client(client):
    def _override():
        return MOCK_USER

    client.app.dependency_overrides[get_current_user] = _override
    yield client
    client.app.dependency_overrides.clear()


@pytest.fixture
def admin_client(client):
    def _override():
        return MOCK_ADMIN

    client.app.dependency_overrides[get_current_user] = _override
    yield client
    client.app.dependency_overrides.clear()


class TestReadEndpointsRequireAuth:
    def test_get_schema_unauthorized(self, client):
        r = client.get(f"{BASE}/schema")
        assert r.status_code == 401

    def test_get_settings_as_user_ok(self, user_client):
        r = user_client.get(BASE)
        assert r.status_code == 200
        assert r.json()["code"] == 0

    def test_get_schema_as_user_ok(self, user_client):
        r = user_client.get(f"{BASE}/schema")
        assert r.status_code == 200
        assert "data" in r.json()

    def test_get_export_requires_auth(self, client):
        r = client.get(f"{BASE}/export")
        assert r.status_code == 401


class TestWriteEndpointsRequireAdmin:
    def test_update_as_user_forbidden(self, user_client):
        r = user_client.put(BASE, json={"settings": {"temperature.decay_rate": 0.2}})
        assert r.status_code == 403

    def test_update_as_admin_ok(self, admin_client):
        r = admin_client.put(BASE, json={"settings": {"temperature.decay_rate": 0.2}})
        assert r.status_code == 200
        assert r.json()["code"] == 0

    def test_reset_as_user_forbidden(self, user_client):
        r = user_client.put(f"{BASE}/reset", json={"keys": None})
        assert r.status_code == 403

    def test_reset_as_admin_ok(self, admin_client):
        r = admin_client.put(f"{BASE}/reset", json={"keys": None})
        assert r.status_code == 200
        assert r.json()["code"] == 0

    def test_import_as_user_forbidden(self, user_client):
        r = user_client.put(f"{BASE}/import", json={"settings": {"temperature.decay_rate": 0.1}})
        assert r.status_code == 403

    def test_import_as_admin_ok(self, admin_client):
        r = admin_client.put(f"{BASE}/import", json={"settings": {"temperature.decay_rate": 0.1}})
        assert r.status_code == 200
        assert r.json()["code"] == 0

    def test_update_unauthorized(self, client):
        r = client.put(BASE, json={"settings": {"temperature.decay_rate": 0.2}})
        assert r.status_code == 401
