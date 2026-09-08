"""原生协议思考归一层测试（TDD 红）

统一契约（2026-09-09）：各协议的思考内容在 provider 解析处归一为
LLMResponse.reasoning_content，Router 以上（Loop/Pipeline/SSE/前端）零改动。

覆盖：
- Anthropic 非流式：content 数组中 type=thinking 的 block → reasoning_content
- Anthropic 流式：SSE 事件流 content_block_delta(thinking_delta) → 增量 reasoning_content
- Gemini 原生 generateContent：parts[] 中 thought=true 的 part → reasoning_content
"""
import json

import pytest

from neurova.llm.providers.protocol_thinking import (
    iter_anthropic_stream_events,
    normalize_anthropic_response,
    normalize_gemini_response,
)


class TestAnthropicNonStream:
    def test_thinking_block_becomes_reasoning_content(self):
        data = {
            "id": "msg_01",
            "model": "claude-sonnet-4",
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "让我算一下鸡兔同笼。"},
                {"type": "text", "text": "鸡 23 只，兔 12 只。"},
            ],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 20},
        }
        resp = normalize_anthropic_response(data)
        assert resp.content == "鸡 23 只，兔 12 只。"
        assert resp.reasoning_content == "让我算一下鸡兔同笼。"
        assert resp.finish_reason == "stop"
        assert resp.model == "claude-sonnet-4"

    def test_no_thinking_blocks(self):
        data = {
            "content": [{"type": "text", "text": "普通回答"}],
            "stop_reason": "end_turn",
        }
        resp = normalize_anthropic_response(data)
        assert resp.content == "普通回答"
        assert resp.reasoning_content is None

    def test_redacted_thinking_skipped_not_leaked(self):
        """redacted_thinking 是加密占位，不能当思考文本展示"""
        data = {
            "content": [
                {"type": "redacted_thinking", "data": "encXXX"},
                {"type": "text", "text": "答案"},
            ],
            "stop_reason": "end_turn",
        }
        resp = normalize_anthropic_response(data)
        assert resp.content == "答案"
        assert resp.reasoning_content is None


class TestAnthropicStream:
    def _events(self):
        return [
            {"type": "message_start", "message": {"id": "msg_1", "model": "claude-x", "role": "assistant"}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "先想"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "一下"}},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "答案"}},
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}},
            {"type": "message_stop"},
        ]

    def test_stream_chunks_normalized(self):
        chunks = list(iter_anthropic_stream_events(self._events()))
        reasoning = "".join(c.reasoning_content or "" for c in chunks)
        content = "".join(c.content or "" for c in chunks)
        assert reasoning == "先想一下"
        assert content == "答案"
        last = chunks[-1]
        assert last.finish_reason == "stop"
        assert last.model == "claude-x"

    def test_parses_raw_sse_lines(self):
        """从原始 SSE 文本行（data: {...}）解析，ping/空行/非 JSON 忽略"""
        lines = [
            "event: message_start",
            'data: {"type": "message_start", "message": {"id": "m", "model": "claude-x"}}',
            "",
            ": ping",
            'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "思考中"}}',
            'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "答"}}',
            "data: [DONE]",
            'data: {"type": "message_stop"}',
        ]
        chunks = list(iter_anthropic_stream_events(lines))
        reasoning = "".join(c.reasoning_content or "" for c in chunks)
        content = "".join(c.content or "" for c in chunks)
        assert reasoning == "思考中"
        assert content == "答"


class TestGeminiThoughtParts:
    def test_thought_parts_become_reasoning(self):
        data = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "设鸡 x 只。", "thought": True},
                            {"text": "答案：鸡 23，兔 12。"},
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 21},
            "modelVersion": "gemini-2.5-flash",
        }
        resp = normalize_gemini_response(data)
        assert resp.reasoning_content == "设鸡 x 只。"
        assert resp.content == "答案：鸡 23，兔 12。"
        assert resp.finish_reason == "stop"
        assert resp.model == "gemini-2.5-flash"

    def test_plain_response_no_thought(self):
        data = {"candidates": [{"content": {"parts": [{"text": "直接答案"}], "role": "model"}}]}
        resp = normalize_gemini_response(data)
        assert resp.content == "直接答案"
        assert resp.reasoning_content is None

    def test_no_candidates(self):
        resp = normalize_gemini_response({})
        assert resp.content == ""
        assert resp.reasoning_content is None
        assert resp.finish_reason is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
