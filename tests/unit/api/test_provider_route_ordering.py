"""
测试 Provider 端点路由顺序问题

问题：
1. GET /api/v1/providers/active-model 返回 404
   根因：/{provider_id} 路由在 /active-model 之前定义，FastAPI 将 "active-model" 当作 provider_id
2. POST /api/v1/providers 返回 500
   根因：add_provider() 参数名不匹配（provider_type vs provider）

使用 TDD 方法：先写失败测试，再修复
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

import os
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")


@pytest.fixture
def mock_provider_manager():
    """模拟 ProviderManager"""
    manager = MagicMock()

    # 模拟 ProviderConfig 对象
    provider_config = MagicMock()
    provider_config.id = "openai-1"
    provider_config.name = "OpenAI"
    provider_config.provider = "openai"
    provider_config.base_url = "https://api.openai.com/v1"
    provider_config.enabled = True
    provider_config.health_status = "healthy"
    provider_config.models = ["gpt-4", "gpt-3.5-turbo"]

    # 设置方法返回值
    manager.list_providers.return_value = [provider_config]
    manager.get_provider.return_value = provider_config
    manager.add_provider.return_value = provider_config
    manager.get_active_model.return_value = {"model": "gpt-4", "provider": "openai"}
    manager.activate_model.return_value = True

    return manager


def _mock_current_user():
    """模拟认证用户"""
    return {"user_id": "test_user", "username": "testuser", "role": "admin"}


@pytest.fixture
def app_client(mock_provider_manager):
    """创建测试客户端（带认证覆盖）"""
    from neurova.api.endpoints.provider import router
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/providers")
    # 覆盖认证依赖，避免每个测试都要传 auth header
    app.dependency_overrides[get_current_user] = _mock_current_user

    # 覆盖依赖注入
    with patch("neurova.api.endpoints.provider._get_provider_manager", return_value=mock_provider_manager):
        client = TestClient(app)
        yield client


class TestRouteOrdering:
    """路由顺序测试"""
    
    def test_active_model_get_returns_200(self, app_client):
        """测试 GET /providers/active-model 返回 200 而非 404"""
        response = app_client.get("/providers/active-model")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "data" in data
    
    def test_activate_model_post_returns_200(self, app_client):
        """测试 POST /providers/activate-model 返回 200"""
        response = app_client.post(
            "/providers/activate-model",
            json={"provider_id": "openai-1", "model_id": "gpt-4"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
    
    def test_provider_id_still_works(self, app_client):
        """测试 /providers/{provider_id} 仍然正常工作"""
        response = app_client.get("/providers/openai-1")
        assert response.status_code == 200
        data = response.json()
        assert data["provider_id"] == "openai-1"


class TestCreateProviderParams:
    """创建服务商参数测试"""
    
    def test_create_provider_calls_add_provider_with_correct_params(self, app_client, mock_provider_manager):
        """测试 POST /providers 调用 add_provider 时使用正确的参数名"""
        response = app_client.post(
            "/providers",
            json={
                "name": "Test Provider",
                "provider_type": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "test-key"
            }
        )
        
        # 验证调用参数
        mock_provider_manager.add_provider.assert_called_once()
        call_args = mock_provider_manager.add_provider.call_args
        
        # 检查关键字参数
        assert call_args.kwargs.get("name") == "Test Provider"
        assert call_args.kwargs.get("provider") == "openai"  # 不是 provider_type
        assert call_args.kwargs.get("base_url") == "https://api.openai.com/v1"
        assert call_args.kwargs.get("api_key") == "test-key"
        
        # 验证响应
        assert response.status_code == 200
        data = response.json()
        assert data["provider_id"] == "openai-1"


class TestEdgeCases:
    """边界情况测试"""
    
    def test_active_model_when_manager_unavailable(self):
        """测试 ProviderManager 不可用时的行为"""
        from neurova.api.endpoints.provider import router
        from neurova.api.auth import get_current_user

        app = FastAPI()
        app.include_router(router, prefix="/providers")
        app.dependency_overrides[get_current_user] = _mock_current_user

        with patch("neurova.api.endpoints.provider._get_provider_manager", return_value=None):
            client = TestClient(app)
            response = client.get("/providers/active-model")
            
            # 应该返回 200 并包含 null 数据
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 0
            assert data["data"]["model"] is None
    
    def test_list_providers_returns_empty_when_no_providers(self, app_client, mock_provider_manager):
        """测试没有服务商时返回空列表"""
        mock_provider_manager.list_providers.return_value = []
        
        response = app_client.get("/providers")
        assert response.status_code == 200
        assert response.json() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])