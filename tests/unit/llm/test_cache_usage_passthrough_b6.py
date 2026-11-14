# -*- coding: utf-8 -*-
"""B6（billion-context 对照 · 改进项 B6）：cache token 计量断链接通。

背景：`MultiModelLLMClient._extract_cache_tokens` 与记账/落库/命中率端点
（B1-5 #7342）早已就绪，但四条上游归一化路径把 cache 字段剥掉，导致除
「OpenAI 兼容流式」外 `cache_read_tokens` 实际恒 0。本文件按教义第 5 条
钉住全部四处命中点的透传契约：

1. OpenAI 兼容非流式（`llm_client.chat`）：usage 保留
   `prompt_tokens_details.cached_tokens`；
2. Anthropic 非流式（`normalize_anthropic_response`）：usage 带
   `cache_read_input_tokens` / `cache_creation_input_tokens`；
3. Anthropic 流式（`iter_anthropic_stream_events`）：`message_start` 携带的
   input/cache usage 与 `message_delta` 的 output 合并到末 chunk usage
   （下游「取最后一个非空 usage」才拿得到完整值）；
4. Gemini（`normalize_gemini_response`）：`usageMetadata.cachedContentTokenCount`
   → `prompt_tokens_details.cached_tokens`。

另钉 usage_accounting 的 `model_switches` 归因计数（换模型必破前缀缓存，
是 cache miss 归因的第一信号）。
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.llm_client import LLMClient, LLMConfig, LLMResponse
from neurova.llm.multi_model_client import MultiModelLLMClient
from neurova.llm.providers.protocol_thinking import (
    iter_anthropic_stream_events,
    normalize_anthropic_response,
    normalize_gemini_response,
)


def _extract(usage):
    return MultiModelLLMClient._extract_cache_tokens(usage)


class TestOpenAINonStreamPassthrough:
    def _chat_with_usage(self, usage_obj):
        client = LLMClient(LLMConfig(api_key="sk-test", model="gpt-4o"))
        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="ok", tool_calls=None),
                    finish_reason="stop",
                )
            ],
            usage=usage_obj,
            model="gpt-4o",
            id="resp_1",
        )
        client._createCompletion = lambda cli, params: fake_response
        return client.chat([{"role": "user", "content": "hi"}])

    def test_usage_keeps_prompt_tokens_details(self):
        usage_obj = SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=50,
            total_tokens=1050,
            prompt_tokens_details=SimpleNamespace(cached_tokens=900),
        )
        resp = self._chat_with_usage(usage_obj)
        details = resp.usage.get("prompt_tokens_details") or {}
        assert details.get("cached_tokens") == 900, (
            f"非流式 usage 丢弃了 prompt_tokens_details：{resp.usage}"
        )

    def test_extract_cache_tokens_sees_nonstream_read(self):
        usage_obj = SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=50,
            total_tokens=1050,
            prompt_tokens_details=SimpleNamespace(cached_tokens=900),
        )
        resp = self._chat_with_usage(usage_obj)
        read, write = _extract(resp.usage)
        assert (read, write) == (900, 0), f"提取器读到 read={read} write={write}"

    def test_missing_details_stays_honest_zero(self):
        usage_obj = SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=50,
            total_tokens=1050,
            prompt_tokens_details=None,
        )
        resp = self._chat_with_usage(usage_obj)
        read, write = _extract(resp.usage)
        assert (read, write) == (0, 0)


class TestAnthropicNormalizePassthrough:
    def test_nonstream_keeps_cache_read_write(self):
        resp = normalize_anthropic_response(
            {
                "model": "claude-x",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 900,
                    "cache_creation_input_tokens": 40,
                },
            }
        )
        assert resp.usage.get("cache_read_input_tokens") == 900
        assert resp.usage.get("cache_creation_input_tokens") == 40
        read, write = _extract(resp.usage)
        assert (read, write) == (900, 40)

    def test_nonstream_without_cache_fields_stays_honest(self):
        resp = normalize_anthropic_response(
            {
                "model": "claude-x",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1000, "output_tokens": 50},
            }
        )
        read, write = _extract(resp.usage)
        assert (read, write) == (0, 0)

    def test_stream_merges_start_usage_into_delta(self):
        events = [
            {
                "type": "message_start",
                "message": {
                    "model": "claude-x",
                    "usage": {
                        "input_tokens": 1000,
                        "cache_read_input_tokens": 900,
                        "cache_creation_input_tokens": 40,
                    },
                },
            },
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn"},
                "usage": {"output_tokens": 50},
            },
        ]
        chunks = list(iter_anthropic_stream_events(events))
        usage_chunks = [c for c in chunks if c.usage]
        assert usage_chunks, "流式路径没有任何 chunk 携带 usage"
        final = usage_chunks[-1].usage
        assert final.get("prompt_tokens") == 1000, f"末 chunk 缺 input 侧：{final}"
        assert final.get("completion_tokens") == 50, f"末 chunk 缺 output 侧：{final}"
        read, write = _extract(final)
        assert (read, write) == (900, 40), f"流式 cache 提取 read={read} write={write}"


class TestGeminiPassthrough:
    def test_normalize_keeps_cached_content_tokens(self):
        resp = normalize_gemini_response(
            {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
                "usageMetadata": {
                    "promptTokenCount": 1000,
                    "candidatesTokenCount": 50,
                    "cachedContentTokenCount": 800,
                },
            }
        )
        details = resp.usage.get("prompt_tokens_details") or {}
        assert details.get("cached_tokens") == 800, f"Gemini cache 计数被丢弃：{resp.usage}"
        read, write = _extract(resp.usage)
        assert (read, write) == (800, 0)

    def test_without_cached_count_stays_honest(self):
        resp = normalize_gemini_response(
            {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 50},
            }
        )
        read, write = _extract(resp.usage)
        assert (read, write) == (0, 0)


class TestModelSwitchAttribution:
    def test_model_switch_counted_in_snapshot(self):
        from neurova.core.usage_accounting import TokenUsageAccounting

        acc = TokenUsageAccounting()
        acc.record(model="m1", provider="p1", prompt_tokens=100, completion_tokens=10,
                   cache_read_tokens=80)
        acc.record(model="m1", provider="p1", prompt_tokens=100, completion_tokens=10,
                   cache_read_tokens=80)
        acc.record(model="m2", provider="p1", prompt_tokens=100, completion_tokens=10)
        snap = acc.snapshot()
        assert snap["total"]["model_switches"] == 1, (
            f"换模型次数未入账：{snap['total']}"
        )

    def test_first_call_is_not_a_switch(self):
        from neurova.core.usage_accounting import TokenUsageAccounting

        acc = TokenUsageAccounting()
        acc.record(model="m1", provider="p1", prompt_tokens=10, completion_tokens=1)
        assert acc.snapshot()["total"]["model_switches"] == 0
