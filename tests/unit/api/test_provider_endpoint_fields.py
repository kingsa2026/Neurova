"""
TDD 测试：Provider 端点字段映射正确性

验证 list_providers 和 get_provider 正确映射 ProviderConfig 属性到 ProviderInfo 响应。
"""
import os
import pytest
from unittest.mock import MagicMock, patch

# 设置测试环境变量（P0 安全修复后端点需要认证）
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")


def _mock_current_user():
    """模拟认证用户（覆盖 get_current_user 依赖）"""
    return {"user_id": "test_user", "username": "testuser", "role": "admin"}


@pytest.fixture
def mock_provider_config():
    """创建一个模拟的 ProviderConfig 对象，使用真实字段名"""
    provider = MagicMock()
    provider.id = "openai-1"
    provider.name = "OpenAI"
    provider.provider = "openai"
    provider.base_url = "https://api.openai.com/v1"
    provider.enabled = True
    provider.health_status = "healthy"
    provider.models = ["gpt-4o", "gpt-3.5-turbo"]
    provider.api_key = "sk-test-key"
    provider.priority = 10
    provider.is_builtin = True
    provider.description = "Test provider"
    provider.default_model = "gpt-4o"
    return provider


@pytest.fixture
def mock_provider_manager(mock_provider_config):
    """创建一个模拟的 ProviderManager，使用正确的 API 方法名"""
    manager = MagicMock()
    # 正确方法名是 list_providers()，不是 get_all_providers()
    manager.list_providers.return_value = [mock_provider_config]
    manager.get_provider.return_value = mock_provider_config
    return manager


@pytest.fixture
def app_client(mock_provider_manager):
    """创建 FastAPI 测试客户端（带认证覆盖）"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    # Mock get_provider_manager
    with patch("neurova.api.endpoints.provider._get_provider_manager", return_value=mock_provider_manager):
        from neurova.api.endpoints.provider import router
        from neurova.api.auth import get_current_user
        app.include_router(router, prefix="/providers")
        # 覆盖认证依赖，避免每个测试都要传 auth header
        app.dependency_overrides[get_current_user] = _mock_current_user
        client = TestClient(app)
        yield client


class TestListProvidersFieldMapping:
    """测试 list_providers 端点的字段映射"""

    def test_list_providers_uses_list_providers_method(self, app_client, mock_provider_manager):
        """list_providers 应该调用 list_providers()，不是 get_all_providers()"""
        response = app_client.get("/providers")
        assert response.status_code == 200
        # 验证调用的是 list_providers 而非 get_all_providers
        mock_provider_manager.list_providers.assert_called_once()
        assert not hasattr(mock_provider_manager, 'get_all_providers') or \
               not mock_provider_manager.get_all_providers.called

    def test_list_providers_maps_id_field(self, app_client):
        """provider_id 应该从 ProviderConfig.id 映射"""
        response = app_client.get("/providers")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert data[0]["provider_id"] == "openai-1"  # 来自 provider.id

    def test_list_providers_maps_provider_type_field(self, app_client):
        """provider_type 应该从 ProviderConfig.provider 映射"""
        response = app_client.get("/providers")
        data = response.json()
        assert data[0]["provider_type"] == "openai"  # 来自 provider.provider

    def test_list_providers_maps_is_active_field(self, app_client):
        """is_active 应该从 ProviderConfig.enabled 映射"""
        response = app_client.get("/providers")
        data = response.json()
        assert data[0]["is_active"] is True  # 来自 provider.enabled

    def test_list_providers_maps_status_field(self, app_client):
        """status 应该从 ProviderConfig.health_status 映射"""
        response = app_client.get("/providers")
        data = response.json()
        assert data[0]["status"] == "healthy"  # 来自 provider.health_status

    def test_list_providers_maps_models_count(self, app_client):
        """models_count 应该从 len(ProviderConfig.models) 计算"""
        response = app_client.get("/providers")
        data = response.json()
        assert data[0]["models_count"] == 2  # len(["gpt-4o", "gpt-3.5-turbo"])

    def test_list_providers_maps_api_key_configured(self, app_client):
        """api_key_configured 反映 ProviderConfig.api_key 是否已配置（聊天模型切换器过滤未配置种子商用）"""
        response = app_client.get("/providers")
        data = response.json()
        assert data[0]["api_key_configured"] is True  # provider.api_key = "sk-test-key"


class TestGetProviderFieldMapping:
    """测试 get_provider 端点的字段映射"""

    def test_get_provider_maps_id_field(self, app_client):
        """provider_id 应该从 ProviderConfig.id 映射"""
        response = app_client.get("/providers/openai-1")
        assert response.status_code == 200
        data = response.json()
        assert data["provider_id"] == "openai-1"

    def test_get_provider_maps_provider_type_field(self, app_client):
        """provider_type 应该从 ProviderConfig.provider 映射"""
        response = app_client.get("/providers/openai-1")
        data = response.json()
        assert data["provider_type"] == "openai"

    def test_get_provider_maps_is_active_field(self, app_client):
        """is_active 应该从 ProviderConfig.enabled 映射"""
        response = app_client.get("/providers/openai-1")
        data = response.json()
        assert data["is_active"] is True

    def test_get_provider_maps_status_field(self, app_client):
        """status 应该从 ProviderConfig.health_status 映射"""
        response = app_client.get("/providers/openai-1")
        data = response.json()
        assert data["status"] == "healthy"

    def test_get_provider_maps_models_count(self, app_client):
        """models_count 应该从 len(ProviderConfig.models) 计算"""
        response = app_client.get("/providers/openai-1")
        data = response.json()
        assert data["models_count"] == 2


class TestDisabledProvider:
    """测试禁用服务商的字段映射"""

    @pytest.fixture
    def disabled_provider(self):
        provider = MagicMock()
        provider.id = "disabled-1"
        provider.name = "Disabled Provider"
        provider.provider = "custom"
        provider.base_url = "http://localhost:9999"
        provider.enabled = False
        provider.health_status = "unknown"
        provider.models = []
        return provider

    @pytest.fixture
    def manager_with_disabled(self, disabled_provider):
        manager = MagicMock()
        manager.list_providers.return_value = [disabled_provider]
        manager.get_provider.return_value = disabled_provider
        return manager

    @pytest.fixture
    def disabled_client(self, manager_with_disabled):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        with patch("neurova.api.endpoints.provider._get_provider_manager", return_value=manager_with_disabled):
            from neurova.api.endpoints.provider import router
            from neurova.api.auth import get_current_user
            app.include_router(router, prefix="/providers")
            # 覆盖认证依赖
            app.dependency_overrides[get_current_user] = _mock_current_user
            client = TestClient(app)
            yield client

    def test_disabled_provider_is_active_false(self, disabled_client):
        response = disabled_client.get("/providers")
        data = response.json()
        assert data[0]["is_active"] is False

    def test_disabled_provider_models_count_zero(self, disabled_client):
        response = disabled_client.get("/providers")
        data = response.json()
        assert data[0]["models_count"] == 0
