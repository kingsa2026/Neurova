"""
P6d 修复:OpenRouter 无 key 发现时不再回落陈旧默认模型,端点透传未配置提示。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig
from neurova.llm.providers.openrouter_provider import OpenRouterProvider


class TestNoFallbackToStaleDefaults:
    @pytest.mark.asyncio
    async def test_failure_returns_empty_not_defaults(self):
        provider = OpenRouterProvider(
            provider_id="openrouter",
            api_key="",
            base_url="https://openrouter.ai/api/v1",
        )
        # 无 key → 请求失败返回空 → 不再回落 10 个陈旧默认模型(不可用模型只误导用户)
        with patch.object(provider, "_fetch_models_from_api", AsyncMock(return_value=[])):
            models = await provider.get_available_models()
        assert models == []
        assert provider._get_default_models()  # 默认列表保留为回退素材(不再自动使用)


class TestDiscoverMessageChannel:
    def test_discover_endpoint_reports_missing_key(self):
        from neurova.api.endpoints import provider as provider_module

        fake_manager = MagicMock()
        fake_cfg = ProviderConfig(
            id="openrouter",
            name="OpenRouter",
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="",
            models=[],
        )
        fake_manager.get_provider = MagicMock(return_value=fake_cfg)
        fake_manager.fetch_provider_models = AsyncMock(return_value=[])
        with patch.object(
            provider_module, "_get_provider_manager", return_value=fake_manager,
        ):
            request = MagicMock()
            request.state.request_id = "discover-nokey"
            result = asyncio.run(
                provider_module.discover_models(request, "openrouter", {"role": "user", "user_id": "7"}),
            )

        assert result["code"] == 0
        assert result["data"]["models"] == []
        # 未配置 key 时应给用户可行动的提示,而非静默"未发现模型"
        assert result["data"].get("message")
