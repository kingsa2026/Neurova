"""
TDD Red:模型条目编辑/删除 API 契约

需求:内置/发现的模型条目(PUT /models/{model_id})可编辑模型 ID 与显示名称;
DELETE /models/{model_id} 对内置发现条目同样生效(不受 user-added 限制)。
当前 model.py 无 PUT 端点、rename_model_entry 不存在 → 全红。
"""

import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")


def _mock_current_user():
    """模拟认证用户（覆盖 get_current_user 依赖）"""
    return {"user_id": "test_user", "username": "testuser", "role": "admin"}


@pytest.fixture
def mock_manager():
    manager = MagicMock()
    manager.rename_model_entry.return_value = True
    manager.update_provider.return_value = True
    provider = MagicMock()
    provider.id = "sensetime"
    provider.name = "商汤科技"
    provider.models = ["sensechat-5", "sensenova-6.7-flash-lite"]
    provider.model_metadata = {
        "sensechat-5": {"id": "sensechat-5", "name": "SenseChat 5"},
        "sensenova-6.7-flash-lite": {"id": "sensenova-6.7-flash-lite", "name": "Sensenova 6.7 Flash Lite"},
    }
    provider.is_builtin = True
    manager.list_providers.return_value = [provider]
    manager.get_provider.return_value = provider
    return manager


@pytest.fixture
def app_client(mock_manager):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    from neurova.api.endpoints import model as model_mod
    from neurova.api.auth import get_optional_user

    app = FastAPI()
    with patch.object(model_mod, "_get_provider_manager", return_value=mock_manager):
        app.include_router(model_mod.router, prefix="/models")
        app.dependency_overrides[get_optional_user] = _mock_current_user
        client = TestClient(app)
        yield client


class TestUpdateModelEndpoint:
    def test_put_updates_id_and_name(self, app_client, mock_manager):
        resp = app_client.put(
            "/models/sensechat-5",
            json={"id": "sensechat-5-pro", "name": "商量 5 Pro", "provider_id": "sensetime"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        mock_manager.rename_model_entry.assert_called_once()

    def test_put_404_when_model_not_found(self, app_client, mock_manager):
        mock_manager.rename_model_entry.return_value = False
        resp = app_client.put("/models/no-such", json={"name": "X"})
        assert resp.status_code == 404

    def test_put_400_when_nothing_to_update(self, app_client):
        resp = app_client.put("/models/sensechat-5", json={})
        assert resp.status_code == 400

    def test_delete_builtin_entry_not_restricted_to_user_added(self, app_client, mock_manager):
        # 内置发现条目同样允许删除:DELETE 不应依赖 user-added 标记
        resp = app_client.delete("/models/sensechat-5")
        assert resp.status_code == 200
        mock_manager.update_provider.assert_called_once()
