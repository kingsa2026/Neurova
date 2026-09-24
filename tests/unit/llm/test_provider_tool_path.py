# -*- coding: utf-8 -*-
"""provider 工具通路：声明位、请求键转发、原生协议 tools/tool_use 接线（Issue #177）。

## 三个缺陷各一条判据（每条都可证伪）

1. **`tool_choice` 是死字段**：`openai_loop` 写了它，`LLMClient._build_request_params`
   逐键挑选时漏了它 ⇒ 模型从未被告知 auto/required/none。判据：转发面必须带上它，
   且只在**声明支持 tool_choice 的网关**上发。
2. **原生协议下工具静默不可用**：`build_anthropic_body` / `build_gemini_body` 没有
   tools 形参，归一化又把 `tool_use` / `functionCall` 丢掉 ⇒ 配了原生 provider
   函数调用能力直接消失，无声无息。判据：请求体真带 tools、响应真出 tool_calls，
   且归一不再静默丢块。
3. **声明位单源**：能力声明落在 `provider_compat.ProviderCompat`，不新开第二份判断
   逻辑。判据：协议面与 provider 行字段级合并，互不抹掉。

转换经 `neurova/tool_layers/openai_schema.py` 的转换器完成（不是「有 import 无调用」）：
判据落在转换产物能被下游 `parse_tool_call` 反解回同一工具名与参数上。
"""
from __future__ import annotations

import json
import logging

import pytest

from neurova.llm.provider_compat import ProviderCompat, resolve_compat
from neurova.llm_client import LLMClient, LLMConfig


# ---------------------------------------------------------------------------
# 1) 声明位：能力声明单源（协议面 + provider 行字段级合并）
# ---------------------------------------------------------------------------


class TestCompatDeclaresToolCapabilities:
    def test_defaults_are_openai_protocol_behaviour(self):
        c = ProviderCompat()
        assert c.supports_tools is True
        assert c.supports_tool_choice is True

    def test_protocol_face_resolves_for_native_protocols(self):
        for protocol in ("anthropic", "gemini", "google", "openai"):
            c = resolve_compat(protocol=protocol)
            assert c.supports_tools is True, f"{protocol} 协议面未声明 supports_tools"
            assert c.supports_tool_choice is True, f"{protocol} 协议面未声明 supports_tool_choice"

    def test_provider_row_and_protocol_row_merge_fieldwise(self):
        """协议行与 provider 行各管各的字段，不得互相抹掉。

        sensetime 静态表只声明 include_stream_usage=False；协议面只声明工具能力。
        两者合并后必须同时生效。
        """
        c = resolve_compat(provider_id="sensetime", protocol="openai")
        assert c.include_stream_usage is False
        assert c.supports_tools is True

    def test_explicit_declaration_wins_over_both(self):
        c = resolve_compat(
            provider_id="sensetime",
            protocol="anthropic",
            compat_dict={"supports_tools": False, "include_stream_usage": True},
        )
        assert c.supports_tools is False
        assert c.include_stream_usage is True


# ---------------------------------------------------------------------------
# 2) 请求键转发：tool_choice 必须真的走到网关
# ---------------------------------------------------------------------------


def _clientWithCompat(compat: ProviderCompat) -> tuple:
    client = LLMClient.__new__(LLMClient)
    client.config = LLMConfig(api_key="sk-test", base_url="https://example.com/v1", model="m")
    client.config.compat = compat
    return client, client.config


class TestToolChoiceForwarding:
    def test_tool_choice_forwarded_when_declared(self):
        client, _ = _clientWithCompat(ProviderCompat())
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "t"}}],
            tool_choice="required",
        )
        assert params.get("tool_choice") == "required", (
            "tool_choice 未进转发面 —— 模型永远收不到 auto/required/none"
        )
        assert "tools" in params

    def test_tool_choice_omitted_when_gateway_lacks_it(self):
        client, _ = _clientWithCompat(ProviderCompat(supports_tool_choice=False))
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "t"}}],
            tool_choice="required",
        )
        assert "tool_choice" not in params
        assert "tools" in params

    def test_tools_omitted_when_gateway_lacks_them(self):
        client, _ = _clientWithCompat(ProviderCompat(supports_tools=False))
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "t"}}],
            tool_choice="auto",
        )
        assert "tools" not in params
        assert "tool_choice" not in params

    def test_tool_choice_absent_when_no_tools(self):
        client, _ = _clientWithCompat(ProviderCompat())
        params = client._build_request_params([{"role": "user", "content": "hi"}])
        assert "tools" not in params
        assert "tool_choice" not in params


class TestDropUnsupportedToolKeys:
    def test_drops_and_reports_explicitly(self, caplog):
        """声明不支持即剔除，且留一行点名 not_supported 的可检索日志（不静默）。"""
        from neurova.llm.provider_compat import dropUnsupportedToolKeys

        kwargs = {
            "tools": [{"type": "function", "function": {"name": "t"}}],
            "tool_choice": "auto",
            "temperature": 0.3,
        }
        with caplog.at_level(logging.WARNING):
            dropped = dropUnsupportedToolKeys(
                ProviderCompat(supports_tools=False, supports_tool_choice=False),
                kwargs,
                logging.getLogger("neurova.test.toolpath"),
                where="unit-test",
            )
        assert sorted(dropped) == ["tool_choice", "tools"]
        assert "tools" not in kwargs and "tool_choice" not in kwargs
        assert kwargs["temperature"] == 0.3
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "not_supported" in joined and "unit-test" in joined


# ---------------------------------------------------------------------------
# 3) 原生协议请求体：tools 真带出去
# ---------------------------------------------------------------------------

_OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "按关键词搜文件",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        },
    }
]


class TestAnthropicRequestBody:
    def test_tools_converted_to_input_schema(self):
        from neurova.llm.providers.anthropic_client import build_anthropic_body

        body = build_anthropic_body(
            [{"role": "user", "content": "hi"}], model="claude-sonnet-4", tools=_OPENAI_TOOLS
        )
        assert body["tools"] == [
            {
                "name": "search_files",
                "description": "按关键词搜文件",
                "input_schema": _OPENAI_TOOLS[0]["function"]["parameters"],
            }
        ]

    def test_tool_choice_mapping(self):
        from neurova.llm.providers.anthropic_client import build_anthropic_body

        auto = build_anthropic_body(
            [{"role": "user", "content": "hi"}], model="m", tools=_OPENAI_TOOLS, tool_choice="auto"
        )
        assert auto["tool_choice"] == {"type": "auto"}
        required = build_anthropic_body(
            [{"role": "user", "content": "hi"}], model="m", tools=_OPENAI_TOOLS, tool_choice="required"
        )
        assert required["tool_choice"] == {"type": "any"}

    def test_no_tools_no_key(self):
        from neurova.llm.providers.anthropic_client import build_anthropic_body

        body = build_anthropic_body([{"role": "user", "content": "hi"}], model="m")
        assert "tools" not in body and "tool_choice" not in body


class TestGeminiRequestBody:
    def test_tools_as_function_declarations(self):
        from neurova.llm.providers.gemini_client import build_gemini_body

        body = build_gemini_body([{"role": "user", "content": "hi"}], tools=_OPENAI_TOOLS)
        decls = body["tools"][0]["functionDeclarations"]
        assert decls[0]["name"] == "search_files"
        assert decls[0]["parameters"] == _OPENAI_TOOLS[0]["function"]["parameters"]

    def test_tool_choice_mapping(self):
        from neurova.llm.providers.gemini_client import build_gemini_body

        auto = build_gemini_body([{"role": "user", "content": "hi"}], tools=_OPENAI_TOOLS, tool_choice="auto")
        assert auto["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
        req = build_gemini_body([{"role": "user", "content": "hi"}], tools=_OPENAI_TOOLS, tool_choice="required")
        assert req["toolConfig"]["functionCallingConfig"]["mode"] == "ANY"

    def test_no_tools_no_key(self):
        from neurova.llm.providers.gemini_client import build_gemini_body

        body = build_gemini_body([{"role": "user", "content": "hi"}])
        assert "tools" not in body


# ---------------------------------------------------------------------------
# 4) 原生协议响应：tool_use / functionCall 归一为 LLMResponse.tool_calls
# ---------------------------------------------------------------------------


class TestAnthropicResponseToolUse:
    def _data(self):
        return {
            "model": "claude-sonnet-4",
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "我来搜索。"},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "search_files",
                    "input": {"q": "neurova"},
                },
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    def test_tool_use_normalized_into_tool_calls(self):
        from neurova.llm.providers.protocol_thinking import normalize_anthropic_response

        resp = normalize_anthropic_response(self._data())
        assert resp.finish_reason == "tool_calls"
        assert resp.content == "我来搜索。"
        assert resp.tool_calls, "tool_use 块被静默丢弃 —— 原生链路上工具调用能力消失"
        call = resp.tool_calls[0]
        assert call["id"] == "toolu_1"
        assert call["type"] == "function"
        assert call["function"]["name"] == "search_files"
        assert json.loads(call["function"]["arguments"]) == {"q": "neurova"}

    def test_converted_call_reparses_to_same_tool(self):
        """经 openai_schema 转换器接线：转换产物必须能被下游解析器反解回同一工具。"""
        from neurova.tool_layers.openai_schema import ToolCallParser
        from neurova.llm.providers.protocol_thinking import normalize_anthropic_response

        resp = normalize_anthropic_response(self._data())
        parsed = ToolCallParser().parse_tool_call(resp.tool_calls[0])
        assert parsed["name"] == "search_files"
        assert parsed["arguments"] == {"q": "neurova"}


class TestAnthropicStreamToolUse:
    def _events(self):
        return [
            {"type": "message_start", "message": {"model": "claude-sonnet-4"}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "搜索中"}},
            {"type": "content_block_stop", "index": 0},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "id": "toolu_2", "name": "search_files"},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"q": '},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '"neurova"}'},
            },
            {"type": "content_block_stop", "index": 1},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use"}},
        ]

    def test_stream_emits_mergeable_tool_call(self):
        from neurova.agent.loops.openai_loop import OpenAILoop
        from neurova.llm.providers.protocol_thinking import iter_anthropic_stream_events

        chunks = list(iter_anthropic_stream_events(self._events()))
        calls = [tc for ch in chunks for tc in (ch.tool_calls or [])]
        assert calls, "流式 tool_use 被丢弃"
        merged: list = []
        for tc in calls:
            OpenAILoop._merge_tool_call_delta(merged, tc)
        assert len(merged) == 1, f"流式分片未按 index 合并到一条调用: {merged}"
        assert merged[0]["id"] == "toolu_2"
        assert merged[0]["function"]["name"] == "search_files"
        assert json.loads(merged[0]["function"]["arguments"]) == {"q": "neurova"}

    def test_stream_text_only_has_no_tool_calls(self):
        from neurova.llm.providers.protocol_thinking import iter_anthropic_stream_events

        events = [e for e in self._events() if "tool_use" not in json.dumps(e)]
        chunks = list(iter_anthropic_stream_events(events))
        assert not [tc for ch in chunks for tc in (ch.tool_calls or [])]


class TestGeminiResponseFunctionCall:
    def _data(self):
        return {
            "modelVersion": "gemini-2.5-flash",
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [{"functionCall": {"name": "search_files", "args": {"q": "neurova"}}}],
                    },
                    "finishReason": "STOP",
                }
            ],
        }

    def test_function_call_normalized(self):
        from neurova.llm.providers.protocol_thinking import normalize_gemini_response

        resp = normalize_gemini_response(self._data())
        assert resp.tool_calls, "functionCall part 被静默丢弃"
        call = resp.tool_calls[0]
        assert call["type"] == "function"
        assert call["function"]["name"] == "search_files"
        assert json.loads(call["function"]["arguments"]) == {"q": "neurova"}


# ---------------------------------------------------------------------------
# 5) 原生客户端：声明为不支持即显式剔除（不静默），支持则真带出去
# ---------------------------------------------------------------------------


class TestNativeClientHonesty:
    def _cfg(self, **compat_kw):
        cfg = LLMConfig(api_key="k", base_url="https://api.anthropic.com", model="claude-sonnet-4")
        cfg.compat = ProviderCompat(**compat_kw)
        return cfg

    def test_anthropic_body_carries_tools(self):
        from neurova.llm.providers.anthropic_client import AnthropicNativeClient

        c = AnthropicNativeClient(self._cfg())
        body = c._body([{"role": "user", "content": "q"}], tools=_OPENAI_TOOLS, tool_choice="auto")
        assert body["tools"][0]["name"] == "search_files"

    def test_anthropic_body_drops_when_declared_unsupported(self, caplog):
        from neurova.llm.providers.anthropic_client import AnthropicNativeClient

        c = AnthropicNativeClient(self._cfg(supports_tools=False, supports_tool_choice=False))
        with caplog.at_level(logging.WARNING):
            body = c._body([{"role": "user", "content": "q"}], tools=_OPENAI_TOOLS, tool_choice="auto")
        assert "tools" not in body
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "not_supported" in joined

    def test_gemini_body_carries_tools(self):
        from neurova.llm.providers.gemini_client import GeminiNativeClient

        cfg = LLMConfig(api_key="k", base_url="https://gen.example.com/v1beta", model="gemini-2.5-flash")
        cfg.compat = ProviderCompat()
        c = GeminiNativeClient(cfg)
        body = c._body([{"role": "user", "content": "q"}], tools=_OPENAI_TOOLS)
        assert body["tools"][0]["functionDeclarations"][0]["name"] == "search_files"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ---------------------------------------------------------------------------
# 6) 幂等：调用方已按目标协议转好时不得被二次转换清空
# ---------------------------------------------------------------------------


class TestPreConvertedToolsSurvive:
    """`AnthropicLoop._convert_tools_to_anthropic` 已把 tools 转成 Anthropic
    形态；客户端若只认 OpenAI 形态，`tool.get("function")` 取空 ⇒ **全部工具被
    静默清空**。这是同一根因的第二个命中点（请求侧两条转码路径相撞）。"""

    def test_anthropic_body_accepts_preconverted_tools(self):
        from neurova.llm.providers.anthropic_client import build_anthropic_body

        preconverted = [
            {"name": "search_files", "description": "按关键词搜文件", "input_schema": {"type": "object"}}
        ]
        body = build_anthropic_body([{"role": "user", "content": "hi"}], model="m", tools=preconverted)
        assert body["tools"] == preconverted

    def test_gemini_body_accepts_preconverted_declarations(self):
        from neurova.llm.providers.gemini_client import build_gemini_body

        preconverted = [{"name": "search_files", "description": "d", "parameters": {"type": "object"}}]
        body = build_gemini_body([{"role": "user", "content": "hi"}], tools=preconverted)
        assert body["tools"][0]["functionDeclarations"][0]["name"] == "search_files"

    def test_empty_name_tool_is_skipped_not_crashed(self):
        from neurova.llm.providers.anthropic_client import build_anthropic_body

        body = build_anthropic_body(
            [{"role": "user", "content": "hi"}],
            model="m",
            tools=[{"type": "function", "function": {"name": ""}}],
        )
        assert "tools" not in body


# ---------------------------------------------------------------------------
# 7) 输入预算：原生客户端不得静默忽略 tools
# ---------------------------------------------------------------------------


class TestNativeTokenCountingCountsTools:
    """`count_message_tokens(messages, tools=...)` 的 `tools` 形参在原生客户端里
    只被接收、从不读取 —— 与 `tool_choice` 同型的「接受但不读」死参。

    真消费方存在：`multi_model_client.py` 的工具轮记账路径就是
    `client.client.count_message_tokens(messages, tools=kwargs.get("tools"))`。
    工具目录占上下文预算，少算即预算闸门偏松（同一契约的第二个命中点）。
    """

    _TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "search_files",
                "description": "按关键词搜文件" * 200,
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
        }
    ]

    def test_anthropic_counts_tool_catalog(self):
        from neurova.llm.providers.anthropic_client import AnthropicNativeClient

        c = AnthropicNativeClient(
            LLMConfig(api_key="k", base_url="https://api.anthropic.com", model="claude-sonnet-4")
        )
        msgs = [{"role": "user", "content": "hi"}]
        assert c.count_message_tokens(msgs, tools=self._TOOLS) > c.count_message_tokens(msgs)

    def test_gemini_counts_tool_catalog(self):
        from neurova.llm.providers.gemini_client import GeminiNativeClient

        c = GeminiNativeClient(
            LLMConfig(api_key="k", base_url="https://g/v1beta", model="gemini-2.5-flash")
        )
        msgs = [{"role": "user", "content": "hi"}]
        assert c.count_message_tokens(msgs, tools=self._TOOLS) > c.count_message_tokens(msgs)

    def test_native_counting_matches_openai_formula(self):
        """两条链路对同一输入必须给出同一口径读数（单一事实源，不另立尺子）。"""
        from neurova.llm.providers.anthropic_client import AnthropicNativeClient

        c = AnthropicNativeClient(
            LLMConfig(api_key="k", base_url="https://api.anthropic.com", model="claude-sonnet-4")
        )
        msgs = [{"role": "user", "content": "hi"}]
        bare = c.count_message_tokens(msgs, tools=None)
        with_tools = c.count_message_tokens(msgs, tools=self._TOOLS)
        # 工具目录按「逐条序列化后计 token」的同一口径增量，量级必须可解释
        assert with_tools - bare >= c.count_tokens(str(self._TOOLS[0]))

    def test_openai_formula_consistent_with_native(self):
        from neurova.llm.providers.anthropic_client import AnthropicNativeClient

        native = AnthropicNativeClient(
            LLMConfig(api_key="k", base_url="https://api.anthropic.com", model="claude-sonnet-4")
        )
        oai = LLMClient.__new__(LLMClient)
        oai.config = LLMConfig(api_key="k", model="gpt-4")
        msgs = [{"role": "user", "content": "hi"}]
        assert native.count_message_tokens(msgs, tools=self._TOOLS) == oai.count_message_tokens(
            msgs, tools=self._TOOLS
        )
