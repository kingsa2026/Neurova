"""GeminiNativeClient 单元测试：请求体组装 + 鸭子接口 + SSE 流归一"""
import pytest

from neurova.llm.providers.gemini_client import (
    GeminiNativeClient,
    build_gemini_body,
    gemini_endpoint_urls,
)
from neurova.llm_client import LLMConfig


class TestBodyBuilder:
    def test_system_instruction_and_roles(self):
        body = build_gemini_body(
            [
                {"role": "system", "content": "你是助手"},
                {"role": "user", "content": "hi"},
                {"role": "tool", "content": "丢弃"},
                {"role": "assistant", "content": "prev"},
            ],
            max_tokens=1024,
        )
        assert body["systemInstruction"]["parts"][0]["text"] == "你是助手"
        assert [c["role"] for c in body["contents"]] == ["user", "model"]
        assert body["generationConfig"]["maxOutputTokens"] == 1024
        assert "thinkingConfig" not in body["generationConfig"]

    def test_thinking_budget_mapping(self):
        body = build_gemini_body([{"role": "user", "content": "hi"}], thinking_effort="deep")
        assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 8192}
        std = build_gemini_body([{"role": "user", "content": "hi"}], thinking_effort="standard")
        assert std["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 2048}
        light = build_gemini_body([{"role": "user", "content": "hi"}], thinking_effort="light")
        assert "thinkingConfig" not in light["generationConfig"]


class TestEndpointUrls:
    def test_official_base(self):
        plain, stream = gemini_endpoint_urls(
            "https://generativelanguage.googleapis.com/v1beta", "gemini-2.5-flash"
        )
        assert plain.endswith("/models/gemini-2.5-flash:generateContent")
        assert "streamGenerateContent?alt=sse" in stream

    def test_bare_domain_gets_v1beta(self):
        plain, _ = gemini_endpoint_urls("https://proxy.example.com", "models/gemini-2.5-flash")
        assert "/v1beta/models/gemini-2.5-flash:generateContent" in plain


class TestStreamNormalization:
    @pytest.mark.asyncio
    async def test_sse_frames_yield_delta_chunks(self, monkeypatch):
        cfg = LLMConfig(api_key="k", base_url="https://gen.example.com/v1beta", model="gemini-2.5-flash")
        c = GeminiNativeClient(cfg)

        frames = [
            'data: {"candidates":[{"content":{"parts":[{"text":"设鸡 x。","thought":true}],"role":"model"}}]}',
            'data: {"candidates":[{"content":{"parts":[{"text":"答案："}],"role":"model"}}]}',
            "",
            'data: {"candidates":[{"content":{"parts":[{"text":"鸡23兔12"}],"role":"model"},"finishReason":"STOP"}]}',
        ]
        async def fake_stream(url, body):
            for f in frames:
                yield f
        monkeypatch.setattr(c, "_stream_sse_lines", fake_stream)

        chunks = [ch async for ch in c.chat_stream_async([{"role": "user", "content": "q"}])]
        reasoning = "".join(ch.reasoning_content or "" for ch in chunks)
        content = "".join(ch.content or "" for ch in chunks)
        assert reasoning == "设鸡 x。"
        assert content == "答案：鸡23兔12"
        assert chunks[-1].finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_chat_normalizes(self, monkeypatch):
        cfg = LLMConfig(api_key="k", base_url="https://gen.example.com/v1beta", model="m")
        c = GeminiNativeClient(cfg)
        async def fake_post(url, body):
            return {
                "candidates": [{"content": {"parts": [{"text": "答案"}], "role": "model"}, "finishReason": "STOP"}],
                "modelVersion": "gemini-2.5-flash",
            }
        monkeypatch.setattr(c, "_post_json", fake_post)
        resp = await c.chat([{"role": "user", "content": "q"}])
        assert resp.content == "答案"
        assert resp.finish_reason == "stop"
        assert resp.model == "gemini-2.5-flash"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
