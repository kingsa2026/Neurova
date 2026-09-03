"""
P5 升级:端点按 current_user 隔离 — provider 配置管理端点 scope 化。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from neurova.api.endpoints import provider as provider_module


class TestEndpointScopeHelper:
    def test_users_use_own_scope(self):
        with patch(
            "neurova.llm.provider_manager.get_provider_manager",
        ) as mock_pm:
            mock_pm.return_value = "alice-instance"
            result = provider_module._get_provider_manager(
                {"role": "user", "user_id": "alice"},
            )
        assert result == "alice-instance"
        mock_pm.assert_called_once_with(scope="user:alice")

    def test_admin_uses_global_scope(self):
        with patch(
            "neurova.llm.provider_manager.get_provider_manager",
        ) as mock_pm:
            mock_pm.return_value = "admin-instance"
            result = provider_module._get_provider_manager(
                {"role": "admin", "user_id": "alice"},
            )
        assert result == "admin-instance"
        mock_pm.assert_called_once_with(scope="admin")

    def test_missing_role_defaults_to_user_scope(self):
        with patch("neurova.llm.provider_manager.get_provider_manager") as mock_pm:
            provider_module._get_provider_manager({"user_id": "bob"})
        mock_pm.assert_called_once_with(scope="user:bob")

    def test_anonymous_falls_back_to_injected_global(self):
        # 无 current_user(如直接函数调用/测试环境)不隔离,保持存量行为
        with patch.object(
            provider_module, "_get_app_state_manager", return_value="global-instance",
        ):
            assert provider_module._get_provider_manager(None) == "global-instance"

    def test_endpoint_respects_user_scope(self):
        """集成:list_providers 端点把 current_user 传入 scoped helper。"""
        from unittest.mock import MagicMock
        import asyncio

        fake_manager = MagicMock()
        fake_manager.list_providers.return_value = []
        with patch.object(
            provider_module, "_get_provider_manager", return_value=fake_manager,
        ) as mock_helper:
            request = MagicMock()
            request.state.request_id = "scope-1"
            current_user = {"role": "user", "user_id": "alice"}
            result = asyncio.run(
                provider_module.list_providers(request, current_user),
            )
            # 端点必须把 current_user 传给隔离 helper(否则隔离失效)
            mock_helper.assert_called_once_with(current_user)

        assert result == []
