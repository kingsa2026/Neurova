"""
P6b 修复:_get_provider_instance 实例构造的 provider_type 参数按签名分发。

TDD Red Phase:OpenAI 兼容类(无 provider_type 参数)实例化不抛
TypeError(当前实现必炸);需要该参数的类(OpenRouter 等)仍正确传入。
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig
from neurova.llm.providers.openai_provider import OpenAIProvider
from neurova.llm.providers.openrouter_provider import OpenRouterProvider
from neurova.llm.providers.types import ModelInfo, ProviderType


def _make_mgr():
    mgr = LLMProviderManager.__new__(LLMProviderManager)
    mgr._providers = {}
    mgr._default_provider_id = None
    mgr._config_lock = threading.RLock()
    mgr._save_config = MagicMock()
    mgr._config_path = MagicMock()
    mgr._provider_instances = {}
    return mgr


def _put_provider(mgr, pid, ptype, **kw):
    mgr._providers[pid] = ProviderConfig(
        id=pid,
        name=pid,
        provider=ptype,
        base_url=kw.get("base_url", "https://api.example.com/v1"),
        api_key=kw.get("api_key", "not-a-real-credential"),
        models=[],
    )


class TestBuildInstance:
    def test_openai_compatible_constructs_without_provider_type(self):
        """回归根因:OpenAIProvider 无 provider_type 参数,构造不得抛 TypeError。"""
        mgr = _make_mgr()
        _put_provider(mgr, "modelscope", "modelscope")
        instance = mgr._get_provider_instance("modelscope")
        assert isinstance(instance, OpenAIProvider)
        assert instance.base_url == "https://api.example.com/v1"

    def test_provider_type_param_classes_still_work(self):
        """支持 provider_type 参数的类(如 OpenRouter)应能正确构造。"""
        mgr = _make_mgr()
        _put_provider(mgr, "openrouter", "openrouter")
        instance = mgr._get_provider_instance("openrouter")
        assert isinstance(instance, OpenRouterProvider)
        assert instance.provider_type == ProviderType.OPENROUTER
        assert instance.provider_id == "openrouter"

    def test_fetch_provider_models_returns_real_models(self):
        """fetch_provider_models 经真实实例构造后正常返回发现结果。"""
        mgr = _make_mgr()
        _put_provider(mgr, "modelscope", "modelscope")
        instance = MagicMock()
        fetched = [
            ModelInfo(id="Qwen/Qwen3-235B-A22B-Thinking-2507", name="Qwen3-235B"),
            ModelInfo(id="ZhipuAI/GLM-5.2", name="GLM-5.2"),
        ]
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(mgr, "_get_provider_instance", return_value=instance):
            models = asyncio.run(mgr.fetch_provider_models("modelscope"))
        assert [m.id for m in models] == [
            "Qwen/Qwen3-235B-A22B-Thinking-2507",
            "ZhipuAI/GLM-5.2",
        ]
