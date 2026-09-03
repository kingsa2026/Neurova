"""
系统设置 API 单元测试 (FastAPI版本)

测试 neurova/api/endpoints/settings 模块提供的真实端点：
- GET  /v1/settings            获取所有设置
- PUT  /v1/settings            更新设置（整体）
- GET  /v1/settings/{key}      获取单个设置
- PUT  /v1/settings/{key}      更新单个设置
- GET  /v1/settings/cors       获取 CORS 配置

说明：原测试针对的是更丰富的设置 API（语言/时区/用户工作空间/
系统信息/用户管理等端点），但这些端点并不在 settings.py 中实现，
属于"测试针对不存在的 API"的陈旧用例。此处对齐到 settings.py
实际提供的端点（与 router / api_router / mem_core 的修复原则一致）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.api.endpoints.settings import router as settings_router


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def app() -> FastAPI:
    """创建测试用 FastAPI 应用（仅挂载 settings_router）"""
    application = FastAPI()
    application.include_router(settings_router)

    # PUT 端点依赖 get_current_user，override 为测试用户
    from neurova.api.auth import get_current_user

    async def _fake_current_user() -> dict:
        return {"user_id": "test_user", "username": "tester"}

    application.dependency_overrides[get_current_user] = _fake_current_user
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """创建测试客户端"""
    return TestClient(app)


# ============================================================
# 设置 API 测试
# ============================================================

class TestSettingsAPI:
    """系统设置 API 测试"""

    def test_get_all_settings(self, client: TestClient):
        """获取所有设置"""
        response = client.get("/v1/settings")
        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        assert isinstance(data["settings"], dict)

    def test_update_all_settings(self, client: TestClient):
        """整体更新设置（请求体需为 {"settings": {...}}）"""
        payload = {"settings": {"theme": "dark", "language": "zh_CN"}}
        response = client.put("/v1/settings", json=payload)
        assert response.status_code == 200
        result = response.json()
        assert "settings" in result

    def test_get_single_setting(self, client: TestClient):
        """获取单个设置"""
        response = client.get("/v1/settings/theme")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert data["data"]["key"] == "theme"

    def test_update_single_setting(self, client: TestClient):
        """更新单个设置"""
        response = client.put("/v1/settings/theme", json="light")
        assert response.status_code == 200
        result = response.json()
        assert result["data"]["key"] == "theme"
        assert result["data"]["value"] == "light"

    def test_get_cors_config(self, client: TestClient):
        """获取 CORS 配置"""
        response = client.get("/v1/settings/cors")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["origins"], list)
        assert data["allow_credentials"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
