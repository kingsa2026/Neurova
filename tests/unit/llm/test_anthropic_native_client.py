"""AnthropicNativeClient 单元测试：请求体组装 + thinking 映射 + 接口鸭子兼容"""
import pytest

from neurova.llm.providers.anthropic_client import (
    AnthropicNativeClient,
    anthropic_endpoint_url,
    build_anthropic_body,
)
from neurova.llm_client import LLMConfig


class TestBodyBuilder:
    def test_system_extracted_and_roles_filtered(self):
        body = build_anthropic_body(
            [
                {"role": "system", "content": "你是助手"},
                {"role": "user", "content": "hi"},
                {"role": "tool", "content": "工具消息应被丢弃"},
                {"role": "assistant", "content": "previous"},
            ],
            model="claude-sonnet-4",
        )
        assert body["system"] == "你是助手"
        assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
        assert body["max_tokens"] > 0
        assert "thinking" not in body

    def test_thinking_effort_maps_budget(self):
        deep = build_anthropic_body([{"role": "user", "content": "hi"}], model="m", thinking_effort="deep")
        assert deep["thinking"] == {"type": "enabled", "budget_tokens": 16384}
        assert deep["temperature"] == 1
        assert deep["max_tokens"] > 16384

        std = build_anthropic_body([{"role": "user", "content": "hi"}], model="m", thinking_effort="standard")
        assert std["thinking"]["budget_tokens"] == 4096

    def test_light_no_thinking(self):
        body = build_anthropic_body([{"role": "user", "content": "hi"}], model="m", thinking_effort="light")
        assert "thinking" not in body


class TestEndpointUrl:
    def test_official_base(self):
        assert anthropic_endpoint_url("https://api.anthropic.com") == "https://api.anthropic.com/v1/messages"

    def test_v1_suffixed_base(self):
        assert anthropic_endpoint_url("https://developer.amd.com.cn/radeon/api/v1") == (
            "https://developer.amd.com.cn/radeon/api/v1/messages"
        )


class TestClientDuckTyping:
    """multi_model_client 消费的鸭子接口：count_tokens/count_message_tokens"""

    def _client(self):
        cfg = LLMConfig(api_key="k", base_url="https://api.anthropic.com", model="claude-sonnet-4")
        return AnthropicNativeClient(cfg)

    def test_count_tokens_rough(self):
        c = self._client()
        assert c.count_tokens("abcd" * 10) == 10
        assert c.count_message_tokens([{"role": "user", "content": "hi"}]) > 0

    def test_stream_sync_rejects_inside_loop(self):
        import asyncio

        c = self._client()
        async def inside():
            it = c.chat_stream([{"role": "user", "content": "hi"}])
            next(iter(it))
        with pytest.raises(RuntimeError, match="chat_stream_async"):
            asyncio.run(inside())

    @pytest.mark.asyncio
    async def test_chat_normalizes_response(self, monkeypatch):
        c = self._client()
        async def fake_post(body):
            return {
                "content": [
                    {"type": "thinking", "thinking": "想"},
                    {"type": "text", "text": "答"},
                ],
                "stop_reason": "end_turn",
                "model": body["model"],
            }
        monkeypatch.setattr(c, "_post_json", fake_post)
        resp = await c.chat([{"role": "user", "content": "hi"}], thinking_effort="deep")
        assert resp.reasoning_content == "想"
        assert resp.content == "答"
        assert resp.finish_reason == "stop"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
