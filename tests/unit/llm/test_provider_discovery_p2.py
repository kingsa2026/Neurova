"""
P2 升级:发现结果持久化 — fetch_provider_models 成功时把新模型并入配置列表。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。

根因:前端"发现模型"按钮把返回结果 push 进内存 models(刷新即丢),
后端从未把发现的模型持久化进 provider.models —— 发现语义前后端不一致。
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig
from neurova.llm.providers.types import ModelInfo


@pytest.fixture
def manager():
    with patch.object(LLMProviderManager, "__init__", lambda self, **kw: None):
        mgr = LLMProviderManager.__new__(LLMProviderManager)
        mgr._providers = {}
        mgr._default_provider_id = None
        mgr._config_lock = threading.RLock()
        mgr._save_config = MagicMock()
        mgr._config_path = MagicMock()
        mgr._provider_instances = {}
        return mgr


def _provider(pid: str, models) -> ProviderConfig:
    return ProviderConfig(
        id=pid,
        name=pid,
        provider="openai",
        base_url="https://api.openai.com/v1",
        models=list(models),
    )


class TestDiscoveryPersistsModels:
    def test_success_appends_new_discovered_models(self, manager):
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        fetched = [
            ModelInfo(id="gpt-4o", name="GPT-4o"),
            ModelInfo(
                id="gpt-5",
                name="GPT-5",
                capabilities=["text", "tool_use"],
                context_window=272000,
            ),
        ]
        instance = MagicMock()
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            models = asyncio.run(manager.fetch_provider_models("openai"))

        provider = manager.get_provider("openai")
        # 新增模型持久化进配置列表(前端点击"发现模型"后的刷新不丢失)
        assert provider.models == ["gpt-4o", "gpt-5"]
        assert provider.model_metadata["gpt-5"]["context_window"] == 272000
        manager._save_config.assert_called()

    def test_existing_ids_not_duplicated(self, manager):
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        fetched = [ModelInfo(id="gpt-4o", name="GPT-4o")]
        instance = MagicMock()
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            asyncio.run(manager.fetch_provider_models("openai"))

        assert manager.get_provider("openai").models == ["gpt-4o"]

    def test_failure_does_not_touch_models(self, manager):
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        instance = MagicMock()
        instance.fetch_models = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            models = asyncio.run(manager.fetch_provider_models("openai"))

        assert models == []
        assert manager.get_provider("openai").models == ["gpt-4o"]
        manager._save_config.assert_not_called()

    def test_discovery_keeps_user_order_and_removed_models_out(self, manager):
        manager._providers["openai"] = _provider("openai", ["z-model", "a-model"])
        fetched = [
            ModelInfo(id="a-model"),
            ModelInfo(id="new-model"),
        ]
        instance = MagicMock()
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            asyncio.run(manager.fetch_provider_models("openai"))

        provider = manager.get_provider("openai")
        # 已配置模型保持原有顺序;新模型按发现顺序追加在尾部
        assert provider.models == ["z-model", "a-model", "new-model"]
