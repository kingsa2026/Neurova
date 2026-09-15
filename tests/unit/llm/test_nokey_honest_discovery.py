"""无 API Key 诚实性回归（2026-09-14）：获取模型/测试连接不得产生假数据与假成功。

锁定契约：
1. 需 key 未配置的 provider：discover 预检直接报 configuration"请先配置 API Key"，
   不触上游、不回落静态默认模型；check_provider_connection / check_model_connection
   同口径失败（缺 key 不得提示连接成功），模型级结果持久化 availability。
2. 免 key 白名单（openrouter/openai/opencode/kilo-code + 本地 ollama/lm_studio）
   不受预检限制；openrouter /models 公开端点无 key 也能拿真实列表。
3. openai/gemini 的 API 失败不再回落静态默认列表（假数据根治），非 200 抛错。
4. 余额/积分不足归一为独立类别 insufficient_balance（402 / 429+insufficient_quota /
   "余额不足"/"欠费"等），hint 引导充值，availability 派生同名状态。
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig
from neurova.llm.providers.error_mapping import (
    ErrorCategory,
    availability_status_of,
    normalize_provider_error,
)
from neurova.llm.providers.openai_provider import OpenAIProvider
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


def _provider(pid: str, provider_type: str = "openai", api_key: str = "", models=None) -> ProviderConfig:
    return ProviderConfig(
        id=pid,
        name=pid,
        provider=provider_type,
        base_url=f"https://api.{pid}.test/v1",
        api_key=api_key,
        models=list(models or []),
    )


class TestDiscoverRequiresApiKey:
    def test_no_key_provider_refused_with_actionable_message(self, manager):
        """需 key 的服务商未配 key：拒绝发现并提示先配置，绝不触上游拿假数据。"""
        manager._providers["deepseek"] = _provider("deepseek", models=["deepseek-chat"])
        instance_spy = MagicMock()
        manager._get_provider_instance = lambda pid: instance_spy

        result = asyncio.run(manager.discover_provider_models("deepseek"))

        assert result["success"] is False
        assert result["error_kind"] == "configuration"
        assert "API Key" in result["message"]
        assert [m.id for m in result["models"]] == ["deepseek-chat"], "应回退已配置存量而非上游/默认列表"
        instance_spy.fetch_models.assert_not_called()

    def test_keyless_whitelist_not_blocked(self, manager):
        """openrouter 属免 key 白名单：预检不得拦截（真实列表走公开端点）。"""
        manager._providers["openrouter"] = _provider("openrouter")
        instance = MagicMock()
        instance.fetch_models = AsyncMock(return_value=[ModelInfo(id="x/y:free", name="x/y:free", is_free=True)])
        manager._get_provider_instance = lambda pid: instance

        result = asyncio.run(manager.discover_provider_models("openrouter"))

        assert result["success"] is True
        instance.fetch_models.assert_called()

    def test_configured_key_provider_not_blocked(self, manager):
        manager._providers["deepseek"] = _provider("deepseek", api_key="sk-real")
        instance = MagicMock()
        instance.fetch_models = AsyncMock(return_value=[ModelInfo(id="deepseek-chat", name="c")])
        manager._check_provider_connection_stub = None
        manager.check_provider_connection = AsyncMock(return_value=MagicMock(success=True, error=None))
        manager._get_provider_instance = lambda pid: instance

        result = asyncio.run(manager.discover_provider_models("deepseek"))
        assert result["success"] is True


class TestConnectionChecksHonest:
    def test_provider_connection_no_key_reports_missing_api_key(self, manager):
        manager._providers["deepseek"] = _provider("deepseek")
        result = asyncio.run(manager.check_provider_connection("deepseek"))
        assert result.success is False
        assert result.error_category == "configuration"
        assert "API Key" in (result.error_hint or result.error)

    def test_model_connection_no_key_reports_missing_api_key(self, manager):
        manager._providers["deepseek"] = _provider("deepseek", models=["deepseek-chat"])
        result = asyncio.run(manager.check_model_connection("deepseek-chat"))
        assert result.success is False
        assert result.error_category == "configuration"
        assert "API Key" in (result.error_hint or result.error)

    def test_model_connection_no_key_persisted_to_availability(self, manager):
        """缺 key 结论须落进可用性元数据（前端徽标/容器同一数据源）。"""
        manager._providers["deepseek"] = _provider("deepseek", models=["deepseek-chat"])
        asyncio.run(manager.check_model_connection("deepseek-chat"))
        meta = manager._providers["deepseek"].model_metadata or {}
        avail = (meta.get("deepseek-chat") or {}).get("availability") or {}
        assert avail.get("message"), "可用性应记录缺 key 信息"

    def test_local_provider_no_key_still_checked(self, manager):
        """ollama 本地服务无 key 属正常：预检不得误伤。"""
        manager._providers["ollama"] = _provider("ollama", provider_type="ollama")
        instance = MagicMock()
        instance.check_connection = AsyncMock(return_value=MagicMock(success=True, error=None))
        manager._get_provider_instance = lambda pid: instance
        result = asyncio.run(manager.check_provider_connection("ollama"))
        assert result.success is True


class TestNoStaticFallbackFakeData:
    def test_openai_empty_api_result_returns_empty_not_defaults(self):
        p = OpenAIProvider(provider_id="openai", api_key="", base_url="https://api.openai.com/v1")
        with patch.object(p, "_fetch_models_from_api", AsyncMock(return_value=[])):
            models = asyncio.run(p.get_available_models())
        assert models == []
        assert p._get_default_models(), "默认列表保留为素材，但不再自动回落"

    def test_openai_api_error_propagates_not_swallowed(self):
        """API 失败必须上抛（归一为可行动错误），不得吞掉后喂默认假数据。"""
        p = OpenAIProvider(provider_id="openai", api_key="sk-bad", base_url="https://api.openai.com/v1")
        err = RuntimeError("HTTP 401: unauthorized")
        err.status_code = 401
        with patch.object(p, "_fetch_models_from_api", AsyncMock(side_effect=err)):
            with pytest.raises(RuntimeError):
                asyncio.run(p.get_available_models())


class TestInsufficientBalanceCategory:
    def test_http_402_is_insufficient_balance(self):
        err = RuntimeError("payment required")
        err.status_code = 402
        normalized = normalize_provider_error(err)
        assert normalized.category == ErrorCategory.INSUFFICIENT_BALANCE
        assert ("余额" in normalized.user_hint) or ("积分" in normalized.user_hint)
        assert normalized.retryable is False

    def test_429_with_insufficient_quota_is_balance(self):
        err = RuntimeError("Error code: 429 - {'error': {'type': 'insufficient_quota'}}")
        err.status_code = 429
        normalized = normalize_provider_error(err)
        assert normalized.category == ErrorCategory.INSUFFICIENT_BALANCE

    def test_chinese_balance_messages(self):
        for msg in ("账户余额不足，请充值", "欠费停服", "credit 积分不足"):
            normalized = normalize_provider_error(RuntimeError(msg))
            assert normalized.category == ErrorCategory.INSUFFICIENT_BALANCE, msg

    def test_availability_status_derives_balance_state(self):
        assert availability_status_of(
            success=False, error_category="insufficient_balance", message="余额不足",
        ) == "insufficient_balance"
