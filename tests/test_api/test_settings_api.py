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

@pytest.fixture(autouse=True)
def _isolate_app_settings(tmp_path, monkeypatch):
    """app_settings 持久化重定向到 tmp——PUT /settings 用例（section + P7 flat）
    不得污染真实 data/app_settings.json（EKB-3920 同模式：测试打真库）。"""
    from neurova.core import app_settings as asm

    monkeypatch.setattr(
        asm, "_settings_path", lambda path=None: path or (tmp_path / "app_settings.json")
    )


@pytest.fixture
def app() -> FastAPI:
    """创建测试用 FastAPI 应用（仅挂载 settings_router）"""
    application = FastAPI()
    application.include_router(settings_router)

    # 端点与角色门都经 `api/deps` 那条再导出取身份（b1dfb744 起从 auth 迁入，
    # 并加 require_admin 写锁）。2026-10-08 §6-54 把**角色门**的取源改成严格门本体
    # （`require_role` 不再吃 `?access_token=`），原来"覆盖 deps 那一份就同时放行
    # GET 与 PUT"的前提因此不再成立——PUT 会 401。改用 helper，按 app 路由图上
    # **真正出现的那几条身份入口**一起替，既不漏也不把残留铺到没用的门上。
    from tests.auth_headers import overrideIdentity

    async def _fake_current_user() -> dict:
        return {"user_id": "test_user", "username": "tester", "role": "admin"}

    overrideIdentity(application, _fake_current_user)
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
        """整体更新设置（请求体需为 {"settings": {...}}）

        原先这一格顺手用 `language: "zh_CN"` 当第二个键——那是四份「默认语言」定义里的
        一个写口（§6-167 已退役，现在写它会得 400，判据在
        `tests/unit/api/test_RetiredGlobalLanguageDefault.py`）。这里改用一个仍然活着的
        平铺键，测的仍是"整表更新回 200 且带 settings"这一件事。
        """
        payload = {"settings": {"theme": "dark", "auto_save": False}}
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
        """更新单个设置（P7 后 update_setting 用 Body(embed=True)，body 需 {"value": ...}）"""
        response = client.put("/v1/settings/theme", json={"value": "light"})
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
