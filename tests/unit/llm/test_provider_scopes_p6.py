"""
P6 升级:model.py 端点 scope 化 + admin 查看用户 LLM 配置入口。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from neurova.llm.provider_manager import get_provider_manager_for_user, list_available_scopes


class TestProviderManagerForUser:
    def test_user_maps_to_own_scope(self):
        with patch(
            "neurova.llm.provider_manager.get_provider_manager",
            return_value="alice-pm",
        ) as mock_pm:
            result = get_provider_manager_for_user(
                {"role": "user", "user_id": "alice"},
            )
        assert result == "alice-pm"
        mock_pm.assert_called_once_with(scope="user:alice")

    def test_admin_maps_to_global(self):
        with patch(
            "neurova.llm.provider_manager.get_provider_manager",
            return_value="admin-pm",
        ) as mock_pm:
            result = get_provider_manager_for_user(
                {"role": "admin", "user_id": "alice"},
            )
        assert result == "admin-pm"
        mock_pm.assert_called_once_with(scope="admin")

    def test_missing_user_id_falls_back_to_admin(self):
        with patch(
            "neurova.llm.provider_manager.get_provider_manager",
            return_value="admin-pm",
        ) as mock_pm:
            result = get_provider_manager_for_user({"role": "user", "user_id": ""})
        assert result == "admin-pm"
        mock_pm.assert_called_once_with(scope="admin")


class TestListAvailableScopes:
    def test_scans_user_config_files(self, tmp_path):
        (tmp_path / "providers.json").write_text("{}", encoding="utf-8")
        (tmp_path / "providers.user-alice.json").write_text("{}", encoding="utf-8")
        (tmp_path / "providers.user-bob.json").write_text("{}", encoding="utf-8")
        scopes = list_available_scopes(tmp_path)
        assert scopes == ["user:alice", "user:bob"]

    def test_ignores_global_and_temp_files(self, tmp_path):
        (tmp_path / "providers.json").write_text("{}", encoding="utf-8")
        (tmp_path / "providers.user-alice.json.bak").write_text("{}", encoding="utf-8")
        scopes = list_available_scopes(tmp_path)
        assert scopes == []


class TestScopesEndpoint:
    def _run(self, current_user):
        from neurova.api.endpoints import provider as provider_module

        with patch.object(
            provider_module,
            "_get_provider_manager",
            return_value=MagicMock(),
        ):
            request = MagicMock()
            request.state.request_id = "scopes-1"
            # 直接函数调用:current_user 由测试注入(绕开 Depends)
            return asyncio.run(
                provider_module.list_provider_scopes(request, current_user),
            )

    def test_admin_gets_scopes_including_user_views(self):
        result = self._run({"role": "admin", "user_id": "root"})
        assert result["code"] == 0
        assert "scopes" in result["data"]

    def test_regular_user_is_forbidden(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as excinfo:
            self._run({"role": "user", "user_id": "alice"})
        assert excinfo.value.status_code == 403


class TestModelEndpointsScope:
    def test_list_models_passes_current_user_to_scoped_helper(self):
        from neurova.api.endpoints import model as model_module
        import asyncio

        fake_manager = MagicMock()
        fake_manager.get_all_models.return_value = []
        with patch.object(
            model_module, "_get_provider_manager", return_value=fake_manager,
        ) as mock_helper:
            request = MagicMock()
            request.state.request_id = "scope-list"
            result = asyncio.run(
                model_module.list_models(request, {"role": "user", "user_id": "alice"}),
            )
        assert result
        mock_helper.assert_called_once_with({"role": "user", "user_id": "alice"})
