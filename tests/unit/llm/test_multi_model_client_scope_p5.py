"""
P5 升级:运行时 LLM 客户端按用户 scope 隔离 + Agent 按 owner 注入。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。

需求:普通用户的 Agent 运行时使用 owner 自己的 LLM 配置(不可见/不可用他人配置);
admin 与无 owner 的 Agent 保持全局(admin scope)。
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from neurova.llm import multi_model_client as mmc
from neurova.llm.multi_model_client import (
    MultiModelLLMClient,
    get_multi_model_client,
    reset_multi_model_client,
    scope_for_owner,
)


@pytest.fixture(autouse=True)
def clean_state():
    reset_multi_model_client()
    yield
    reset_multi_model_client()


class TestScopedClients:
    def test_get_client_uses_owner_scope_provider_manager(self):
        fake_pm = MagicMock()
        with patch.object(mmc, "get_provider_manager", return_value=fake_pm) as mock_pm:
            client = get_multi_model_client(scope="user:alice")
        assert client._provider_manager is fake_pm
        mock_pm.assert_called_once_with(scope="user:alice")

    def test_same_scope_returns_same_instance(self):
        with patch.object(mmc, "get_provider_manager", return_value=MagicMock()):
            a = get_multi_model_client(scope="user:alice")
            b = get_multi_model_client(scope="user:alice")
        assert a is b

    def test_different_scopes_are_isolated(self):
        with patch.object(
            mmc, "get_provider_manager", side_effect=[MagicMock(), MagicMock()],
        ):
            alice = get_multi_model_client(scope="user:alice")
            bob = get_multi_model_client(scope="user:bob")
        assert alice is not bob
        assert alice._provider_manager is not bob._provider_manager

    def test_default_still_uses_global(self):
        fake_pm = MagicMock()
        with patch.object(mmc, "get_provider_manager", return_value=fake_pm) as mock_pm:
            client = get_multi_model_client()
        assert client._provider_manager is fake_pm
        # 无参调用仍走默认(admin)scope
        mock_pm.assert_called_once_with(scope="admin")

    def test_reset_clears_scoped_clients(self):
        with patch.object(mmc, "get_provider_manager", return_value=MagicMock()):
            alice = get_multi_model_client(scope="user:alice")
            reset_multi_model_client()
            alice2 = get_multi_model_client(scope="user:alice")
        assert alice2 is not alice


class TestScopeForOwner:
    def test_owner_maps_to_user_scope(self):
        assert scope_for_owner("alice") == "user:alice"

    def test_missing_owner_returns_none(self):
        assert scope_for_owner(None) is None
        assert scope_for_owner("") is None


class TestAgentLLMClientScope:
    def test_agent_client_uses_owner_scope(self):
        from neurova.agent_core import AgentLLMClient

        with patch.object(mmc, "get_multi_model_client") as mock_getter:
            client = AgentLLMClient(model="auto", scope="user:alice")
            client._get_client()
        mock_getter.assert_called_once_with("user:alice")

    def test_agent_client_without_owner_uses_default(self):
        from neurova.agent_core import AgentLLMClient

        with patch.object(mmc, "get_multi_model_client") as mock_getter:
            client = AgentLLMClient(model="auto", scope=None)
            client._get_client()
        mock_getter.assert_called_once_with(None)
