"""
P0 升级:OpenRouter Provider — 必备请求头 + API 元数据能力判定 + None 容错。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。

问题根因(对照 QwenPaw):
1. 缺少 OpenRouter 强制要求的 HTTP-Referer / X-OpenRouter-Title 请求头,
   请求会被拒绝/限流 — 这是"免费模型可用但实际调不通"的最可能根因。
2. 能力判定走名称关键字启发式,而不是 API 返回的 architecture.input_modalities
   (QwenPaw 以 OpenRouter /models 元数据为权威)。
3. top_provider.max_completion_tokens 为 None 时(常见字段缺失),
   ModelInfo(max_tokens=None) 触发 pydantic 校验错误,导致整批模型发现被吞
   并回落到 10 个陈旧默认模型 — 这是发现机制失效的深层根因之一。
"""

from __future__ import annotations

import pytest

from neurova.llm.providers.openrouter_provider import OpenRouterProvider

# 测试用虚构凭据,非真实密钥;任何真实 key 都应来自配置/环境变量。
_API_KEY_PLACEHOLDER = "t-esta-ke-y0-000"


@pytest.fixture
def provider() -> OpenRouterProvider:
    return OpenRouterProvider(
        provider_id="openrouter",
        api_key=_API_KEY_PLACEHOLDER,
        base_url="https://openrouter.ai/api/v1",
    )


class TestRequiredHeaders:
    def test_headers_include_referer_and_title(self, provider: OpenRouterProvider):
        headers = provider._make_headers()
        assert headers.get("HTTP-Referer", "").startswith("https://")
        assert "X-OpenRouter-Title" in headers
        assert headers["Authorization"] == f"Bearer {_API_KEY_PLACEHOLDER}"


class TestParseApiModelModalities:
    def test_capabilities_from_architecture_input_modalities(
        self, provider: OpenRouterProvider
    ):
        model = provider._parse_api_model(
            {
                "id": "openai/gpt-4o",
                "architecture": {
                    "input_modalities": ["image", "text"],
                    "output_modalities": ["text"],
                },
            },
        )
        caps = [c.value for c in model.capabilities]
        assert "vision" in caps
        assert "text" in caps
        assert "tool_use" in caps  # 默认工具使用能力保留

    def test_video_modality_maps_to_video(self, provider: OpenRouterProvider):
        model = provider._parse_api_model(
            {
                "id": "google/gemini-2.5-pro-preview",
                "architecture": {"input_modalities": ["video", "text"]},
            },
        )
        caps = [c.value for c in model.capabilities]
        assert "video" in caps

    def test_plain_text_model_stays_text_only(self, provider: OpenRouterProvider):
        model = provider._parse_api_model(
            {
                "id": "deepseek/deepseek-chat",
                "architecture": {"input_modalities": ["text"]},
            },
        )
        caps = [c.value for c in model.capabilities]
        assert caps == ["text", "tool_use"]


class TestParseApiModelNoneTolerance:
    def test_none_max_completion_tokens_falls_back_to_default(
        self, provider: OpenRouterProvider
    ):
        # 真实 OpenRouter 数据:top_provider 存在但 max_completion_tokens=null
        model = provider._parse_api_model(
            {
                "id": "deepseek/deepseek-chat",
                "top_provider": {"max_completion_tokens": None},
                "context_length": 32768,
            },
        )
        assert model.max_tokens == 4096
        assert model.context_window == 32768

    def test_none_context_length_falls_back_to_default(
        self, provider: OpenRouterProvider
    ):
        model = provider._parse_api_model(
            {
                "id": "gpt-4o",
                "context_length": None,
            },
        )
        assert model.context_window == 4096

    def test_pricing_strings_converted_to_per_million(
        self, provider: OpenRouterProvider
    ):
        # OpenRouter pricing 为 per-token 字符串,现有实现换算为每 1M tokens
        model = provider._parse_api_model(
            {
                "id": "openai/gpt-4o",
                "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            },
        )
        assert abs(model.pricing["input"] - 2.5) < 1e-9
        assert abs(model.pricing["output"] - 10.0) < 1e-9
