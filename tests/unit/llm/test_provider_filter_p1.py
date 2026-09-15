"""
P1 升级:OpenRouter 模型筛选(filter_models)+ is_free 判定 + 元数据残留清理。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。

"""

from __future__ import annotations

import asyncio
import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.llm.provider_manager import ProviderConfig
from neurova.llm.providers.openrouter_provider import OpenRouterProvider
from neurova.llm.providers.types import ModelInfo, ProviderType

# 测试用凭据:只读环境变量占位,不落源码;真实密钥只能来自配置/环境变量。
_CRED = os.environ.get("NEUROVA_TEST_CRED", "not-a-real-credential")


@pytest.fixture
def provider() -> OpenRouterProvider:
    return OpenRouterProvider(
        provider_id="openrouter",
        api_key=_CRED,
        base_url="https://openrouter.ai/api/v1",
    )


def _m(model_id: str, is_free: bool = False, pricing=None) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        name=model_id,
        provider="openrouter",
        provider_type=ProviderType.OPENROUTER,
        capabilities=["text", "tool_use"],
        is_free=is_free,
        pricing=pricing or {},
    )


class TestIsFreeDetection:
    def test_zero_pricing_is_free(self, provider: OpenRouterProvider):
        model = provider._parse_api_model(
            {
                "id": "meta-llama/llama-3.3-70b-instruct:free",
                "pricing": {"prompt": "0", "completion": "0"},
            },
        )
        assert model.is_free is True

    def test_free_suffix_id_with_missing_pricing_is_free(
        self, provider: OpenRouterProvider
    ):
        # 2026-09-14 修复：`:free` 后缀是 OpenRouter 官方免费变体标记，
        # pricing 缺失/异常时不得把免费模型误判为付费
        model = provider._parse_api_model(
            {"id": "meta-llama/llama-3.3-70b-instruct:free"},
        )
        assert model.is_free is True

    def test_free_suffix_id_overrides_paid_pricing(
        self, provider: OpenRouterProvider
    ):
        # ID 标记为权威：`:free` 变体即使定价数据异常（非零脏数据）也是免费
        model = provider._parse_api_model(
            {
                "id": "x/y:free",
                "pricing": {"prompt": "0.001", "completion": "0.002"},
            },
        )
        assert model.is_free is True

    def test_paid_suffix_id_with_all_zero_pricing_stays_free_fallback(
        self, provider: OpenRouterProvider
    ):
        # 无 :free 后缀时保留原"全零定价=免费"兜底契约
        model = provider._parse_api_model(
            {
                "id": "z/w",
                "pricing": {"prompt": "0", "completion": "0"},
            },
        )
        assert model.is_free is True

    def test_nonzero_pricing_is_paid(self, provider: OpenRouterProvider):
        model = provider._parse_api_model(
            {
                "id": "openai/gpt-4o",
                "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            },
        )
        assert model.is_free is False

    def test_free_with_zero_prompt_but_paid_completion(
        self, provider: OpenRouterProvider
    ):
        # 仅 prompt 为 0 不算免费
        model = provider._parse_api_model(
            {
                "id": "x/y",
                "pricing": {"prompt": "0", "completion": "0.001"},
            },
        )
        assert model.is_free is False


class TestFilterModels:
    def _models(self):
        return [
            _m("openai/gpt-4o", pricing={"input": 2.5, "output": 10.0}),
            _m("anthropic/claude-3.5-sonnet", pricing={"input": 3.0, "output": 15.0}),
            _m("meta-llama/llama-3.3-70b-instruct:free", is_free=True, pricing={"input": 0.0, "output": 0.0}),
        ]

    def test_filter_by_provider_prefix(self, provider: OpenRouterProvider):
        result = provider.filter_models(self._models(), providers=["openai"])
        assert [m.id for m in result] == ["openai/gpt-4o"]

    def test_filter_by_provider_prefix_case_insensitive(
        self, provider: OpenRouterProvider
    ):
        result = provider.filter_models(self._models(), providers=["OpenAI"])
        assert [m.id for m in result] == ["openai/gpt-4o"]

    def test_filter_by_free_only(self, provider: OpenRouterProvider):
        result = provider.filter_models(self._models(), is_free=True)
        assert [m.id for m in result] == ["meta-llama/llama-3.3-70b-instruct:free"]

    def test_filter_by_max_price(self, provider: OpenRouterProvider):
        result = provider.filter_models(self._models(), max_prompt_price=2.75)
        ids = [m.id for m in result]
        assert "openai/gpt-4o" in ids  # 2.5 <= 2.75
        assert "meta-llama/llama-3.3-70b-instruct:free" in ids  # 0
        assert "anthropic/claude-3.5-sonnet" not in ids  # 3.0 > 2.75

    def test_filter_models_without_provider_prefix_only_matches_provider_field(
        self, provider: OpenRouterProvider
    ):
        # 无前缀 id 用 model.provider 兜底
        result = provider.filter_models(
            [ModelInfo(id="gpt-4o", provider="openai")],
            providers=["openai"],
        )
        assert [m.id for m in result] == ["gpt-4o"]

    def test_get_available_providers_extracts_series(self, provider: OpenRouterProvider):
        models = self._models()
        with patch.object(provider, "fetch_models", AsyncMock(return_value=models)):
            series = asyncio.run(provider.get_available_providers())
        assert series == ["anthropic", "meta-llama", "openai"]


class TestMetadataPruning:
    def test_update_provider_prunes_metadata_of_removed_models(self):
        cfg = ProviderConfig(
            id="openai",
            name="OpenAI",
            provider="openai",
            base_url="https://api.openai.com/v1",
            models=["a", "b"],
            model_metadata={
                "a": {"id": "a", "capabilities": ["text"]},
                "b": {"id": "b", "capabilities": ["text", "vision"]},
                "c": {"id": "c"},  # 已删模型的残留
            },
        )
        cfg.updated_at = "2026-08-30T00:00:00"
        from neurova.llm.provider_manager import LLMProviderManager

        with patch.object(LLMProviderManager, "__init__", lambda self, **kw: None):
            mgr = LLMProviderManager.__new__(LLMProviderManager)
        mgr._providers = {"openai": cfg}
        mgr._config_lock = __import__("threading").RLock()
        mgr._save_config = MagicMock()

        mgr.update_provider("openai", models=["a"])
        assert set(cfg.model_metadata.keys()) == {"a"}


class TestSeriesEndpoint:
    def test_series_endpoint_returns_series(self):
        from neurova.api.endpoints import provider as provider_module

        mock_mgr = MagicMock()
        fake_instance = MagicMock()
        fake_instance.get_available_providers = AsyncMock(
            return_value=["anthropic", "openai"],
        )
        mock_mgr._get_provider_instance = MagicMock(return_value=fake_instance)
        with patch.object(
            provider_module, "_get_provider_manager", return_value=mock_mgr
        ):
            request = MagicMock()
            request.state.request_id = "series-1"
            result = asyncio.run(
                provider_module.get_provider_series(request, "openrouter"),
            )

        assert result["code"] == 0
        assert result["data"]["series"] == ["anthropic", "openai"]

    def test_series_endpoint_empty_without_support(self):
        from neurova.api.endpoints import provider as provider_module

        mock_mgr = MagicMock()
        mock_mgr._get_provider_instance = MagicMock(return_value=None)
        with patch.object(
            provider_module, "_get_provider_manager", return_value=mock_mgr
        ):
            request = MagicMock()
            request.state.request_id = "series-2"
            result = asyncio.run(
                provider_module.get_provider_series(request, "dummy"),
            )

        assert result["code"] == 0
        assert result["data"]["series"] == []


class TestFilterEndpoint:
    def test_endpoint_returns_json_models(self):
        from neurova.api.endpoints import provider as provider_module

        mock_mgr = MagicMock()
        models = [
            ModelInfo(
                id="openai/gpt-4o",
                name="GPT-4o",
                provider="openrouter",
                provider_type=ProviderType.OPENROUTER,
                capabilities=["text", "tool_use"],
                is_free=False,
            ),
        ]
        mock_mgr.filter_provider_models = AsyncMock(return_value=models)
        with patch.object(
            provider_module, "_get_provider_manager", return_value=mock_mgr
        ):
            request = MagicMock()
            request.state.request_id = "filter-1"
            request_body = MagicMock()
            request_body.providers = ["openai"]
            request_body.input_modalities = []
            request_body.output_modalities = []
            request_body.max_prompt_price = None
            request_body.is_free = None
            result = asyncio.run(
                provider_module.filter_provider_models(
                    request, "openrouter", request_body
                ),
            )

        assert result["code"] == 0
        assert result["data"]["total_count"] == 1
        assert result["data"]["models"][0]["id"] == "openai/gpt-4o"
        # 序列化后 capabilities 应为裸字符串(JSON 安全)
        assert result["data"]["models"][0]["capabilities"] == ["text", "tool_use"]
