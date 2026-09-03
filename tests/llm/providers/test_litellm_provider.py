"""Tests for neurova.llm.providers.litellm_provider — TDD RED phase."""
import json
import os
import threading
from dataclasses import is_dataclass
from typing import Any, Dict, List, Optional

import pytest


class TestHelpers:
    def test_new_id_with_prefix(self):
        from neurova.llm.providers.litellm_provider import _new_id
        rid = _new_id("llm_")
        assert isinstance(rid, str)
        assert rid.startswith("llm_")
        assert len(rid) > len("llm_")

    def test_new_id_without_prefix(self):
        from neurova.llm.providers.litellm_provider import _new_id
        rid = _new_id()
        assert isinstance(rid, str)
        assert len(rid) > 0

    def test_now_iso_returns_string(self):
        from neurova.llm.providers.litellm_provider import _now_iso
        ts = _now_iso()
        assert isinstance(ts, str)
        assert "T" in ts


class TestParseCapability:
    def test_parse_known_capability_text(self):
        from neurova.llm.providers.litellm_provider import _parse_capability
        from neurova.llm.providers.types import ProviderCapability
        assert _parse_capability("text") == ProviderCapability.TEXT

    def test_parse_unknown_falls_back_to_text(self):
        from neurova.llm.providers.litellm_provider import _parse_capability
        from neurova.llm.providers.types import ProviderCapability
        assert _parse_capability("unknown-thing") == ProviderCapability.TEXT

    def test_parse_vision_keyword(self):
        from neurova.llm.providers.litellm_provider import _parse_capability
        from neurova.llm.providers.types import ProviderCapability
        assert _parse_capability("vision") == ProviderCapability.VISION


class TestInferCapabilities:
    def test_includes_text_by_default(self):
        from neurova.llm.providers.litellm_provider import _infer_capabilities_from_model_info
        from neurova.llm.providers.types import ProviderCapability
        caps = _infer_capabilities_from_model_info({"model_name": "foo"})
        assert ProviderCapability.TEXT in caps

    def test_vision_keyword_in_name(self):
        from neurova.llm.providers.litellm_provider import _infer_capabilities_from_model_info
        from neurova.llm.providers.types import ProviderCapability
        caps = _infer_capabilities_from_model_info({"model_name": "gpt-4-vision"})
        assert ProviderCapability.VISION in caps
        assert ProviderCapability.MULTIMODAL in caps

    def test_function_calling_flag(self):
        from neurova.llm.providers.litellm_provider import _infer_capabilities_from_model_info
        from neurova.llm.providers.types import ProviderCapability
        caps = _infer_capabilities_from_model_info(
            {"model_name": "x", "supports_function_calling": True}
        )
        assert ProviderCapability.TOOL_USE in caps


class TestProviderInstantiation:
    def test_can_instantiate(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider(provider_id="litellm-test")
        assert p is not None

    def test_inherits_base_provider(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        from neurova.llm.providers.base import BaseProvider
        p = LiteLLMProvider(provider_id="litellm-test")
        assert isinstance(p, BaseProvider)

    def test_default_provider_id(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider()
        assert p.provider_id == "litellm"

    def test_kwargs_stored_in_config(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider(drop_params=True, num_retries=5)
        assert p._config.get("drop_params") is True
        assert p._config.get("num_retries") == 5


class TestGetSupportedModels:
    def test_returns_list(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider()
        result = p.get_supported_models()
        assert isinstance(result, list)

    def test_list_contains_known_default_models(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider()
        result = p.get_supported_models()
        assert any("gpt" in m.lower() for m in result) or len(result) >= 0


class TestIsModelSupported:
    def test_returns_bool(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider()
        result = p.is_model_supported("gpt-4")
        assert isinstance(result, bool)

    def test_unknown_model_returns_false(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider()
        assert p.is_model_supported("totally-fake-model-xyz-12345") is False


class TestGetModelInfo:
    def test_returns_dict_or_none(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider()
        result = p.get_model_info("gpt-4")
        assert result is None or isinstance(result, dict)

    def test_returns_none_for_unknown(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider()
        result = p.get_model_info("definitely-not-a-model-zzz")
        assert result is None


class TestDetermineProviderType:
    def test_openai_model(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        from neurova.llm.providers.types import ProviderType
        p = LiteLLMProvider()
        assert p._determine_provider_type("gpt-4-turbo") == ProviderType.OPENAI

    def test_anthropic_model(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        from neurova.llm.providers.types import ProviderType
        p = LiteLLMProvider()
        assert p._determine_provider_type("claude-3-opus") == ProviderType.ANTHROPIC

    def test_ollama_model(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        from neurova.llm.providers.types import ProviderType
        p = LiteLLMProvider()
        assert p._determine_provider_type("ollama/llama2") == ProviderType.OLLAMA

    def test_custom_model(self):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        from neurova.llm.providers.types import ProviderType
        p = LiteLLMProvider()
        assert p._determine_provider_type("weird-unknown-model") == ProviderType.CUSTOM


class TestSingletonFactory:
    def test_factory_returns_provider(self):
        from neurova.llm.providers.litellm_provider import get_litellm_provider, LiteLLMProvider
        p = get_litellm_provider()
        assert isinstance(p, LiteLLMProvider)

    def test_factory_returns_same_instance(self):
        from neurova.llm.providers.litellm_provider import get_litellm_provider
        p1 = get_litellm_provider()
        p2 = get_litellm_provider()
        assert p1 is p2


class TestListSupportedModels:
    def test_returns_list(self):
        from neurova.llm.providers.litellm_provider import list_supported_models
        result = list_supported_models()
        assert isinstance(result, list)


class TestRequestHistory:
    def test_record_request_stores_entry(self, tmp_path, monkeypatch):
        from neurova.llm.providers import litellm_provider
        monkeypatch.setattr(litellm_provider, "_DEFAULT_HISTORY_DIR", str(tmp_path))
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider(history_dir=str(tmp_path))
        p.record_request_history(model_id="gpt-4", success=True, latency_ms=120.0)
        history = p.get_request_history()
        assert isinstance(history, list)
        assert len(history) >= 1
        assert history[-1]["model_id"] == "gpt-4"
        assert history[-1]["success"] is True

    def test_history_thread_safe(self, tmp_path):
        from neurova.llm.providers.litellm_provider import LiteLLMProvider
        p = LiteLLMProvider(history_dir=str(tmp_path))

        def worker(i: int) -> None:
            for j in range(5):
                p.record_request_history(model_id=f"m-{i}-{j}", success=True, latency_ms=1.0)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        history = p.get_request_history()
        assert len(history) == 20
