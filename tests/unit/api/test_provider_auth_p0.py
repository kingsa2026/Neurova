"""
BE-API-010 (P0) 安全修复测试: provider 端点无认证

验证所有 /api/v1/providers 端点都需要认证，匿名访问返回 401。
provider 配置是敏感操作，不能匿名访问。
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api import auth
from neurova.api.endpoints import provider as provider_endpoint


@pytest.fixture
def mock_provider_manager():
    """模拟 ProviderManager"""
    manager = MagicMock()
    provider_config = MagicMock()
    provider_config.id = "openai-1"
    provider_config.name = "OpenAI"
    provider_config.provider = "openai"
    provider_config.base_url = "https://api.openai.com/v1"
    provider_config.enabled = True
    provider_config.health_status = "healthy"
    provider_config.models = ["gpt-4", "gpt-3.5-turbo"]

    manager.list_providers.return_value = [provider_config]
    manager.get_provider.return_value = provider_config
    manager.add_provider.return_value = provider_config
    manager.update_provider.return_value = True
    manager.remove_provider.return_value = True
    manager.get_active_model.return_value = {"model": "gpt-4", "provider": "openai"}
    manager.activate_model.return_value = True
    manager.fetch_provider_models.return_value = ["gpt-4", "gpt-3.5-turbo"]
    manager.check_provider_connection.return_value = {"connected": True}
    return manager


@pytest.fixture
def app_client(mock_provider_manager):
    """创建带 provider 路由的测试客户端"""
    app = FastAPI()
    app.include_router(provider_endpoint.router, prefix="/api/v1/providers")

    with patch(
        "neurova.api.endpoints.provider._get_provider_manager",
        return_value=mock_provider_manager,
    ):
        client = TestClient(app, raise_server_exceptions=False)
        yield client


@pytest.fixture
def auth_token():
    """生成有效的认证 token"""
    return auth.create_access_token({
        "sub": "admin123",
        "username": "admin",
        "role": "admin",
    })


@pytest.fixture
def auth_headers(auth_token):
    """认证请求头"""
    return {"Authorization": f"Bearer {auth_token}"}


class TestProviderEndpointAuth:
    """所有 provider 端点必须要求认证"""

    def test_list_providers_without_auth_returns_401(self, app_client):
        """列出服务商无认证返回 401"""
        response = app_client.get("/api/v1/providers")
        assert response.status_code == 401

    def test_get_provider_without_auth_returns_401(self, app_client):
        """获取服务商详情无认证返回 401"""
        response = app_client.get("/api/v1/providers/openai-1")
        assert response.status_code == 401

    def test_create_provider_without_auth_returns_401(self, app_client):
        """创建服务商无认证返回 401"""
        response = app_client.post(
            "/api/v1/providers",
            json={"name": "Test", "provider_type": "openai"},
        )
        assert response.status_code == 401

    def test_update_provider_without_auth_returns_401(self, app_client):
        """更新服务商无认证返回 401"""
        response = app_client.put(
            "/api/v1/providers/openai-1",
            json={"name": "Updated"},
        )
        assert response.status_code == 401

    def test_delete_provider_without_auth_returns_401(self, app_client):
        """删除服务商无认证返回 401"""
        response = app_client.delete("/api/v1/providers/openai-1")
        assert response.status_code == 401

    def test_activate_model_without_auth_returns_401(self, app_client):
        """激活模型无认证返回 401"""
        response = app_client.post(
            "/api/v1/providers/activate-model",
            json={"provider_id": "openai-1", "model_id": "gpt-4"},
        )
        assert response.status_code == 401

    def test_get_active_model_without_auth_returns_401(self, app_client):
        """获取活跃模型无认证返回 401"""
        response = app_client.get("/api/v1/providers/active-model")
        assert response.status_code == 401

    def test_discover_models_without_auth_returns_401(self, app_client):
        """发现模型无认证返回 401"""
        response = app_client.get("/api/v1/providers/openai-1/models/discover")
        assert response.status_code == 401

    def test_check_connection_without_auth_returns_401(self, app_client):
        """检查连接无认证返回 401"""
        response = app_client.post("/api/v1/providers/openai-1/check-connection")
        assert response.status_code == 401

    def test_list_providers_with_auth_not_401(self, app_client, auth_headers):
        """带认证列出服务商不应返回 401"""
        response = app_client.get("/api/v1/providers", headers=auth_headers)
        assert response.status_code != 401, "带认证不应返回 401"

    def test_get_active_model_with_auth_not_401(self, app_client, auth_headers):
        """带认证获取活跃模型不应返回 401"""
        response = app_client.get("/api/v1/providers/active-model", headers=auth_headers)
        assert response.status_code != 401, "带认证不应返回 401"
