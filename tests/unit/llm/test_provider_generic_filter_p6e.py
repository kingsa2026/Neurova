"""
P6e 修复:filter_provider_models 对无 filter_models 方法的实例做通用过滤。

TDD Red Phase:当前实现(实例无 filter_models → 直接返回 [])下全部失败。
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig
from neurova.llm.providers.types import ModelInfo, ProviderCapability, ProviderType


@pytest.fixture
def manager():
    mgr = LLMProviderManager.__new__(LLMProviderManager)
    mgr._providers = {}
    mgr._default_provider_id = None
    mgr._config_lock = threading.RLock()
    mgr._save_config = MagicMock()
    mgr._config_path = MagicMock()
    mgr._provider_instances = {}
    return mgr


def _put_open_code(mgr):
    mgr._providers["opencode"] = ProviderConfig(
        id="opencode",
        name="OpenCode",
        provider="opencode",
        base_url="https://opencode.ai/zen/v1",
        models=[],
    )


class TestGenericFilter:
    def test_free_only_works_without_instance_filter_method(self, manager):
        """OpenCode 等无 filter_models 的实例:按通用语义过滤。"""
        _put_open_code(manager)
        # spec 限制属性:确保 filter_models 不存在(无特化实现,走通用过滤)
        instance = MagicMock(spec=["fetch_models"])
        fetched = [
            ModelInfo(
                id="mimo-v2.5-free", is_free=True,
                capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            ),
            ModelInfo(
                id="claude-opus-5", is_free=False,
                capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            ),
        ]
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            models = asyncio.run(
                manager.filter_provider_models("opencode", is_free=True),
            )
        assert [m.id for m in models] == ["mimo-v2.5-free"]

    def test_series_filter_matches_id_prefix(self, manager):
        _put_open_code(manager)
        instance = MagicMock(spec=["fetch_models"])
        fetched = [
            ModelInfo(id="openai/gpt-4o"),
            ModelInfo(id="anthropic/claude-5"),
        ]
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            models = asyncio.run(
                manager.filter_provider_models("opencode", providers=["openai"]),
            )
        assert [m.id for m in models] == ["openai/gpt-4o"]

    def test_modality_filter_matches_capabilities(self, manager):
        _put_open_code(manager)
        instance = MagicMock(spec=["fetch_models"])
        fetched = [
            ModelInfo(id="vision-model", capabilities=[ProviderCapability.VISION]),
            ModelInfo(id="text-model", capabilities=[ProviderCapability.TEXT]),
        ]
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            models = asyncio.run(
                manager.filter_provider_models("opencode", input_modalities=["image"]),
            )
        assert [m.id for m in models] == ["vision-model"]
