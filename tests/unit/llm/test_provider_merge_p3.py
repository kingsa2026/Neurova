"""
P3 升级:发现候选(discovered_models)与配置列表(models)分离 + 显式合并且。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。

对齐 QwenPaw:发现的模型是"候选"而非"已配置";候选持久化,
用户可经 merge 端点显式并入配置(避免 OpenRouter 全量发现 200+ 模型
一次性冲进配置列表的失焦体验)。
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


def _provider(pid: str, models, discovered=None) -> ProviderConfig:
    return ProviderConfig(
        id=pid,
        name=pid,
        provider="openai",
        base_url="https://api.openai.com/v1",
        models=list(models),
        discovered_models=[*discovered] if discovered is not None else [],
    )


class TestFetchKeepsCandidatesSeparate:
    def test_fetch_with_merge_false_keeps_models_untouched(self, manager):
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        fetched = [
            ModelInfo(id="gpt-4o", name="GPT-4o"),
            ModelInfo(id="gpt-5", name="GPT-5", context_window=272000),
        ]
        instance = MagicMock()
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            models = asyncio.run(
                manager.fetch_provider_models("openai", merge=False),
            )

        provider = manager.get_provider("openai")
        # 候选不自动并入配置,但已持久化(刷新不丢失)
        assert provider.models == ["gpt-4o"]
        assert provider.discovered_models == ["gpt-5"]
        assert provider.model_metadata["gpt-5"]["context_window"] == 272000
        manager._save_config.assert_called()

    def test_fetch_merge_true_still_appends(self, manager):
        # P2 行为保留:默认 merge=True 时兼容现有前端"发现即全部加入"
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        fetched = [ModelInfo(id="gpt-4o"), ModelInfo(id="gpt-5")]
        instance = MagicMock()
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            asyncio.run(manager.fetch_provider_models("openai"))

        provider = manager.get_provider("openai")
        assert provider.models == ["gpt-4o", "gpt-5"]
        assert provider.discovered_models == []

    def test_fetch_failure_preserves_prior_candidates(self, manager):
        manager._providers["openai"] = _provider(
            "openai", ["gpt-4o"], discovered=["gpt-5"],
        )
        instance = MagicMock()
        instance.fetch_models = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            asyncio.run(manager.fetch_provider_models("openai", merge=False))

        provider = manager.get_provider("openai")
        assert provider.discovered_models == ["gpt-5"]


class TestMergeDiscoveredModels:
    def test_merge_all_candidates(self, manager):
        manager._providers["openai"] = _provider(
            "openai", ["gpt-4o"], discovered=["gpt-5", "gpt-4o"],
        )
        count = manager.merge_discovered_models("openai")
        provider = manager.get_provider("openai")
        assert count == 1  # gpt-4o 已在配置中,仅并入 gpt-5
        assert provider.models == ["gpt-4o", "gpt-5"]
        assert provider.discovered_models == []
        manager._save_config.assert_called()

    def test_merge_selected_ids_only(self, manager):
        manager._providers["openai"] = _provider(
            "openai", ["gpt-4o"], discovered=["gpt-5", "gpt-6"],
        )
        count = manager.merge_discovered_models("openai", model_ids=["gpt-6"])
        provider = manager.get_provider("openai")
        assert count == 1
        assert provider.models == ["gpt-4o", "gpt-6"]
        assert provider.discovered_models == ["gpt-5"]  # 未选择保留候选

    def test_merge_ignores_unknown_and_configured_ids(self, manager):
        manager._providers["openai"] = _provider(
            "openai", ["gpt-4o"], discovered=["gpt-5"],
        )
        count = manager.merge_discovered_models(
            "openai", model_ids=["gpt-5", "gpt-4o", "not-a-candidate"],
        )
        assert count == 1
        assert manager.get_provider("openai").models == ["gpt-4o", "gpt-5"]

    def test_merge_is_idempotent(self, manager):
        manager._providers["openai"] = _provider(
            "openai", [], discovered=["gpt-5"],
        )
        manager.merge_discovered_models("openai")
        second = manager.merge_discovered_models("openai")
        assert second == 0
        assert manager.get_provider("openai").models == ["gpt-5"]


class TestMergeEndpoint:
    def test_merge_endpoint_returns_merged_count(self):
        from neurova.api.endpoints import provider as provider_module

        mock_mgr = MagicMock()
        mock_mgr.merge_discovered_models = MagicMock(return_value=2)
        with patch.object(
            provider_module, "_get_provider_manager", return_value=mock_mgr
        ):
            request = MagicMock()
            request.state.request_id = "merge-1"
            result = asyncio.run(
                provider_module.merge_discovered_models_endpoint(
                    request, "openai", MagicMock(model_ids=["a", "b"]),
                ),
            )

        assert result["code"] == 0
        assert result["data"]["merged_count"] == 2
