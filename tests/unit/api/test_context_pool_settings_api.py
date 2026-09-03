"""
上下文池设置API测试 - TDD实现

测试目标：
1. 获取上下文池设置
2. 更新上下文池设置
3. 获取特定模型的Token预算
4. 测试Token预算计算

修复记录（2026-08 审计）:
- 原实现用 create_app() + `with TestClient` 触发完整 lifespan，
  Agent 初始化会同步加载持久化记忆库（>100万条），导致测试挂起数分钟。
- 端点本身自包含（模块级 _default_pool_settings），改用最小 FastAPI 应用
  只挂载 context_pool_settings 路由（与 test_files_api_auth_p0.py 同一约定）。
- 原测试路径 /v1/context/pool-settings 与真实挂载路径 /v1/context-pool/pool-settings
  不符（endpoints/__init__.py 注册为 /v1/context-pool），一并修正。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import context_pool_settings
from neurova.api.endpoints.context_pool_settings import _default_pool_settings

MOCK_USER = {
    "user_id": "test_user",
    "username": "testuser",
    "role": "user",
}

BASE = "/v1/context-pool/pool-settings"


@pytest.fixture
def client():
    """创建最小测试客户端（不触发 create_app lifespan），mock 认证并隔离全局设置"""
    original = dict(_default_pool_settings)
    original_budgets = dict(_default_pool_settings.get("model_budgets", {}))

    app = FastAPI()
    app.include_router(context_pool_settings.router, prefix="/v1/context-pool")

    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER

    with TestClient(app) as c:
        yield c

    _default_pool_settings.clear()
    _default_pool_settings.update(original)
    _default_pool_settings["model_budgets"] = original_budgets
    app.dependency_overrides.clear()


class TestContextPoolSettingsAPI:
    """上下文池设置API"""

    def test_get_pool_settings(self, client):
        """测试获取上下文池设置"""
        response = client.get(BASE)

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "data" in data

        settings = data["data"]
        assert "max_size" in settings
        assert "ttl_seconds" in settings
        assert "default_token_budget" in settings
        assert "model_budgets" in settings

        assert settings["max_size"] == 100
        assert settings["ttl_seconds"] == 3600
        assert settings["default_token_budget"] == 16000

    def test_update_pool_settings(self, client):
        """测试更新上下文池设置"""
        update_data = {
            "max_size": 150,
            "ttl_seconds": 7200,
            "default_token_budget": 32000,
        }

        response = client.put(BASE, json=update_data)

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "message" in data
        assert "data" in data

        updated_settings = data["data"]
        assert updated_settings["max_size"] == 150
        assert updated_settings["ttl_seconds"] == 7200
        assert updated_settings["default_token_budget"] == 32000

    def test_get_token_budget_for_model(self, client):
        """测试获取特定模型的Token预算"""
        response = client.get(f"{BASE}/token-budget/gpt-4")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "data" in data

        budget_info = data["data"]
        assert "model_name" in budget_info
        assert "token_budget" in budget_info

        assert budget_info["model_name"] == "gpt-4"
        assert budget_info["token_budget"] == 32000

    def test_test_budget_calculation(self, client):
        """测试Token预算计算测试端点"""
        test_data = {
            "model_name": "gpt-4",
            "capabilities": ["TEXT", "VISION"],
        }

        response = client.post(f"{BASE}/test-budget", json=test_data)

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "data" in data

        budget_result = data["data"]
        assert "model_name" in budget_result
        assert "capabilities" in budget_result
        assert "calculated_budget" in budget_result
        assert "explanation" in budget_result

        assert budget_result["model_name"] == "gpt-4"
        assert budget_result["calculated_budget"] == 32000

    def test_get_pool_settings_unauthorized(self):
        """测试未认证访问返回 401（端点自带 Depends(get_current_user)）"""
        app = FastAPI()
        app.include_router(context_pool_settings.router, prefix="/v1/context-pool")
        with TestClient(app) as no_auth_client:
            response = no_auth_client.get(BASE)
            assert response.status_code in [401, 403]

    def test_update_pool_settings_validation(self, client):
        """测试更新设置时的数据验证"""
        invalid_data = {
            "max_size": -1,
            "ttl_seconds": 0,
            "default_token_budget": 500,
        }

        response = client.put(BASE, json=invalid_data)

        assert response.status_code == 422

    def test_get_token_budget_unknown_model(self, client):
        """测试获取未知模型的Token预算"""
        response = client.get(f"{BASE}/token-budget/unknown-model")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

        budget_info = data["data"]
        assert budget_info["model_name"] == "unknown-model"
        assert budget_info["token_budget"] == 16000


class TestContextPoolSettingsIntegration:
    """上下文池设置集成测试"""

    def test_pool_settings_affect_context_building(self):
        """测试池设置影响上下文构建"""
        # 这个测试验证修改设置后，上下文构建行为是否改变
        # 需要模拟上下文池和设置服务
        pass

    def test_dynamic_budget_integration(self):
        """测试动态预算计算是否正确集成"""
        # 验证动态预算计算是否正确
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
