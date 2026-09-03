"""
P0 升级:对齐 QwenPaw 服务商管理 — 模型元数据化 + 真实现替换占位。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。

升级点(对应 provider_manager.py):
1. ProviderConfig 携带模型元数据(model_metadata),保持 models 字符串兼容
2. get_all_models 返回带能力/上下文/价格信息的真 ModelInfo
3. fetch_provider_models 真调用 provider 实例并将结果写回 model_metadata
4. probe_model_multimodal / check_model_connection 仅凭 model_id 定位 provider
5. check_provider_connection 真调用实例,健康状态反映真实结果(不再恒 healthy)
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig
from neurova.llm.providers.types import ConnectionResult, ModelInfo as ProviderModelInfo


@pytest.fixture
def manager():
    """Create an LLMProviderManager with mocked init to avoid config file I/O."""
    with patch.object(LLMProviderManager, "__init__", lambda self, **kw: None):
        mgr = LLMProviderManager.__new__(LLMProviderManager)
        mgr._providers = {}
        mgr._default_provider_id = None
        mgr._config_lock = threading.RLock()
        mgr._save_config = MagicMock()
        mgr._config_path = MagicMock()
        mgr._provider_instances = {}
        return mgr


def _provider(pid: str, models, **kw) -> ProviderConfig:
    return ProviderConfig(
        id=pid,
        name=kw.pop("name", pid),
        provider=kw.pop("provider", "openai"),
        base_url=kw.pop("base_url", "https://api.example.com/v1"),
        models=list(models),
        **kw,
    )


# ---------------------------------------------------------------------------
# 1. ProviderConfig 元数据持久化
# ---------------------------------------------------------------------------

class TestProviderConfigMetadata:
    def test_to_dict_carries_model_metadata(self):
        cfg = _provider(
            "openai",
            ["gpt-4o"],
            model_metadata={
                "gpt-4o": {
                    "id": "gpt-4o",
                    "name": "GPT-4o",
                    "capabilities": ["text", "vision"],
                    "context_window": 128000,
                    "pricing": {"input": 2.5, "output": 10.0},
                },
            },
        )
        data = cfg.to_dict(encrypt=False)
        assert data["models"] == ["gpt-4o"]  # 字符串契约不变
        assert data["model_metadata"]["gpt-4o"]["context_window"] == 128000

    def test_from_dict_roundtrip_preserves_metadata(self):
        cfg = _provider(
            "openai",
            ["gpt-4o"],
            model_metadata={
                "gpt-4o": {
                    "id": "gpt-4o",
                    "capabilities": ["text", "vision"],
                    "context_window": 128000,
                },
            },
        )
        restored = ProviderConfig.from_dict(cfg.to_dict(encrypt=False))
        assert restored.model_metadata["gpt-4o"]["context_window"] == 128000

    def test_from_dict_accepts_legacy_config_without_metadata(self):
        legacy = {
            "id": "openai",
            "name": "OpenAI",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "models": ["gpt-4o"],
        }
        restored = ProviderConfig.from_dict(legacy)
        assert restored.models == ["gpt-4o"]
        assert restored.model_metadata == {}


# ---------------------------------------------------------------------------
# 2. get_all_models 元数据嵌入
# ---------------------------------------------------------------------------

class TestGetAllModelsMetadata:
    def test_models_with_metadata_carry_capabilities(self, manager):
        manager._providers["openai"] = _provider(
            "openai",
            ["gpt-4o"],
            model_metadata={
                "gpt-4o": {
                    "id": "gpt-4o",
                    "name": "GPT-4o",
                    "capabilities": ["text", "vision"],
                    "context_window": 128000,
                    "pricing": {"input": 2.5},
                },
            },
        )
        models = manager.get_all_models()
        assert len(models) == 1
        m = models[0]
        assert m.id == "gpt-4o"
        assert m.owned_by == "openai"
        assert m.name == "GPT-4o"
        assert "vision" in m.capabilities
        assert m.context_window == 128000
        assert m.pricing.get("input") == 2.5

    def test_models_without_metadata_keep_id_as_name(self, manager):
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        models = manager.get_all_models()
        assert models[0].name == "gpt-4o"
        assert models[0].owned_by == "openai"


# ---------------------------------------------------------------------------
# 3. fetch_provider_models 真调用实例并写回元数据
# ---------------------------------------------------------------------------

class TestFetchProviderModels:
    def test_invokes_instance_and_stores_metadata(self, manager):
        manager._providers["openrouter"] = _provider(
            "openrouter",
            ["openai/gpt-4o"],
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
        )
        fetched = [
            ProviderModelInfo(
                id="openai/gpt-4o",
                name="GPT-4o",
                capabilities=["text", "vision"],
                context_window=128000,
            ),
        ]
        instance = MagicMock()
        instance.fetch_models = AsyncMock(return_value=fetched)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            models = asyncio.run(manager.fetch_provider_models("openrouter"))

        assert models == fetched
        provider = manager.get_provider("openrouter")
        assert provider.model_metadata["openai/gpt-4o"]["context_window"] == 128000
        manager._save_config.assert_called_once()

    def test_failure_keeps_previous_models(self, manager):
        manager._providers["openrouter"] = _provider(
            "openrouter",
            ["openai/gpt-4o"],
            provider="openrouter",
        )
        instance = MagicMock()
        instance.fetch_models = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            models = asyncio.run(manager.fetch_provider_models("openrouter"))

        assert models == []
        assert manager.get_provider("openrouter").models == ["openai/gpt-4o"]


# ---------------------------------------------------------------------------
# 4. probe / check-model 仅凭 model_id 定位 provider
# ---------------------------------------------------------------------------

class TestProbeModelLocatesProvider:
    def test_uses_metadata_first(self, manager):
        manager._providers["openrouter"] = _provider(
            "openrouter",
            ["openai/gpt-4o"],
            provider="openrouter",
            model_metadata={
                "openai/gpt-4o": {
                    "id": "openai/gpt-4o",
                    "capabilities": ["text", "vision"],
                },
            },
        )
        result = asyncio.run(manager.probe_model_multimodal("openai/gpt-4o"))
        assert result.supported is True
        assert "vision" in [c.value for c in result.capabilities]
        assert result.metadata.get("detection_method") == "metadata"

    def test_falls_back_to_provider_instance(self, manager):
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        probe_result = MagicMock()
        probe_result.supported = True
        probe_result.capabilities = ["text"]
        instance = MagicMock()
        instance.probe_model_multimodal = AsyncMock(return_value=probe_result)
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            result = asyncio.run(manager.probe_model_multimodal("gpt-4o"))
        assert result.supported is True
        instance.probe_model_multimodal.assert_awaited_once_with("gpt-4o")

    def test_unknown_model_returns_unsupported(self, manager):
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        result = asyncio.run(manager.probe_model_multimodal("does-not-exist"))
        assert result.supported is False


class TestCheckModelConnectionLocatesProvider:
    def test_with_model_id_only(self, manager):
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        instance = MagicMock()
        instance.check_model_connection = AsyncMock(
            return_value=ConnectionResult(success=True, latency_ms=12.3),
        )
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            result = asyncio.run(manager.check_model_connection("gpt-4o"))

        assert result.success is True
        assert result.latency_ms == 12.3
        instance.check_model_connection.assert_awaited_once_with("gpt-4o")

    def test_unknown_model_returns_failure(self, manager):
        manager._providers["openai"] = _provider("openai", ["gpt-4o"])
        result = asyncio.run(manager.check_model_connection("does-not-exist"))
        assert result.success is False


# ---------------------------------------------------------------------------
# 5. check_provider_connection 真实反映实例状态
# ---------------------------------------------------------------------------

class TestCheckProviderConnection:
    def test_success_marks_healthy(self, manager):
        manager._providers["openrouter"] = _provider(
            "openrouter", ["openai/gpt-4o"], provider="openrouter",
        )
        instance = MagicMock()
        instance.check_connection = AsyncMock(
            return_value=ConnectionResult(success=True, models_available=200),
        )
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            result = asyncio.run(manager.check_provider_connection("openrouter"))

        assert result.success is True
        assert result.models_available == 200
        assert manager.get_provider("openrouter").health_status == "healthy"

    def test_failure_marks_unhealthy(self, manager):
        manager._providers["openrouter"] = _provider(
            "openrouter", ["openai/gpt-4o"], provider="openrouter",
        )
        instance = MagicMock()
        instance.check_connection = AsyncMock(
            return_value=ConnectionResult(success=False, error="401 unauthorized"),
        )
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            result = asyncio.run(manager.check_provider_connection("openrouter"))

        assert result.success is False
        assert result.error == "401 unauthorized"
        assert manager.get_provider("openrouter").health_status == "unhealthy"

    def test_health_check_provider_reflects_instance(self, manager):
        manager._providers["openrouter"] = _provider(
            "openrouter", ["openai/gpt-4o"], provider="openrouter",
        )
        instance = MagicMock()
        instance.check_connection = AsyncMock(
            return_value=ConnectionResult(success=False, error="timeout"),
        )
        with patch.object(manager, "_get_provider_instance", return_value=instance):
            ok = asyncio.run(manager.health_check_provider("openrouter"))
        assert ok is False
        assert manager.get_provider("openrouter").health_status == "unhealthy"
