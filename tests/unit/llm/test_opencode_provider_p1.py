"""
P1 升级:OpenCode Provider 特化 — free 后缀判定、失效模型封禁、免 key 发现。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。

对齐 QwenPaw:
1. OpenCode 网关模型以 ``-free`` 后缀标识;部分模型网关列出但不再服务
   (deepseek-v4-flash-free / nemotron-3-super-free),发现时必须剔除。
2. 网关无 API key 要求(free tier),空 key 也应能发现。
"""

from __future__ import annotations

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.llm.providers.opencode_provider import OpenCodeProvider
from neurova.llm.providers.types import (
    ModelInfo,
    ProbeResult,
    ProviderCapability,
    ProviderType,
)


@pytest.fixture
def provider() -> OpenCodeProvider:
    return OpenCodeProvider(
        provider_id="opencode",
        api_key="",
        base_url="https://opencode.ai/zen/v1",
    )


def _fake_session(resp_payload: dict):
    """构造 aiohttp 场景:GET /models 返回 payload 的 ClientSession mock。

    aiohttp 的 ``session.get(url)`` 返回 RequestContextManager(async with 兼容),
    因此 mock 的 __call__ 须返回带 __aenter__/__aexit__ 的对象,而非 coroutine。
    """
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=resp_payload)
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_response)
    mock_context.__aexit__ = AsyncMock(return_value=False)
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_context)
    mock_client_session = MagicMock()
    mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_client_session.__aexit__ = AsyncMock(return_value=False)
    return mock_client_session


class TestProviderType:
    def test_opencode_provider_type_exists(self):
        assert ProviderType.OPENCODE.value == "opencode"

    def test_opencode_provider_is_openai_compatible(self, provider: OpenCodeProvider):
        assert isinstance(provider, OpenCodeProvider)
        assert provider.provider_type == ProviderType.OPENCODE
        assert provider.provider_id == "opencode"


class TestFetchModels:
    @pytest.mark.asyncio
    async def test_fetch_marks_free_by_suffix(self, provider: OpenCodeProvider):
        session = _fake_session(
            {
                "data": [
                    {"id": "mimo-v2.5-free"},
                    {"id": "nemotron-3-ultra-free"},
                ],
            },
        )
        provider._models_cache = []
        provider._models_cache_time = 0
        with patch(
            "neurova.llm.providers.openai_provider.aiohttp.ClientSession",
            return_value=session,
        ):
            models = await provider.fetch_models()

        ids = [m.id for m in models]
        assert len(ids) == 2
        assert all(m.is_free for m in models)

    @pytest.mark.asyncio
    async def test_fetch_prefers_apifree_flag(self, provider: OpenCodeProvider):
        session = _fake_session(
            {
                "data": [
                    {"id": "kilo-auto/free", "isFree": True},
                    {"id": "paid-model", "is_free": False},
                ],
            },
        )
        provider._models_cache = []
        provider._models_cache_time = 0
        with patch(
            "neurova.llm.providers.openai_provider.aiohttp.ClientSession",
            return_value=session,
        ):
            models = await provider.fetch_models()

        by_id = {m.id: m for m in models}
        assert by_id["kilo-auto/free"].is_free is True  # 网关标志,无 -free 后缀
        assert by_id["paid-model"].is_free is False  # 显式非免费

    @pytest.mark.asyncio
    async def test_hardcoded_blocklist_excluded(self, provider: OpenCodeProvider):
        session = _fake_session(
            {
                "data": [
                    {"id": "deepseek-v4-flash-free"},
                    {"id": "nemotron-3-super-free"},
                    {"id": "mimo-v2.5-free"},
                ],
            },
        )
        provider._models_cache = []
        provider._models_cache_time = 0
        with patch(
            "neurova.llm.providers.openai_provider.aiohttp.ClientSession",
            return_value=session,
        ):
            models = await provider.fetch_models()

        ids = [m.id for m in models]
        assert "deepseek-v4-flash-free" not in ids  # 网关仍列出但已停止服务
        assert "nemotron-3-super-free" not in ids
        assert ids == ["mimo-v2.5-free"]

    @pytest.mark.asyncio
    async def test_empty_key_still_fetches(self, provider: OpenCodeProvider):
        session = _fake_session({"data": [{"id": "mimo-v2.5-free"}]})
        provider._models_cache = []
        provider._models_cache_time = 0
        with patch(
            "neurova.llm.providers.openai_provider.aiohttp.ClientSession",
            return_value=session,
        ):
            models = await provider.fetch_models()
        assert models and models[0].id == "mimo-v2.5-free"


class TestDefaults:
    def test_default_models_are_free(self, provider: OpenCodeProvider):
        defaults = provider._get_default_models()
        assert defaults
        assert all(m.is_free for m in defaults)
        # 封禁清单中的模型不允许出现在默认列表
        assert all(m.id not in provider._UNAVAILABLE_MODEL_IDS for m in defaults)


class TestCapabilities:
    def test_text_and_tool_use_by_default(self, provider: OpenCodeProvider):
        model = provider._parse_api_model({"id": "mimo-v2.5-free"})
        caps = [c for c in model.capabilities]
        assert ProviderCapability.TEXT in caps
        assert ProviderCapability.TOOL_USE in caps
