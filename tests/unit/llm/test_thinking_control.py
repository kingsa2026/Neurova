# -*- coding: utf-8 -*-
"""B1-3 思考控制三级旋钮（QwenPaw #6302 对齐）。

thinking_enabled（bool）/ thinking_budget（int）两级 + 既有 reasoning_effort。
按声明门控注入：仅 compat.supports_thinking_toggle=True 的网关注入
enable_thinking / thinking_budget（Qwen/DashScope 风格请求体），未声明
网关绝不注入（与 supports_reasoning_effort 同一声明式纪律，防 400）。
"""
from __future__ import annotations

from types import SimpleNamespace

from neurova.llm.provider_compat import ProviderCompat


def _client_with_compat(compat):
    from neurova.llm_client import LLMClient

    cfg = SimpleNamespace(
        model="m", temperature=0.7, max_tokens=4096, top_p=0.9,
        frequency_penalty=0.0, presence_penalty=0.0, compat=compat,
    )
    client = object.__new__(LLMClient)
    client.config = cfg
    return client


class TestProviderCompatThinkingToggle:
    def test_default_off(self):
        assert ProviderCompat().supports_thinking_toggle is False

    def test_declared_on(self):
        assert ProviderCompat(supports_thinking_toggle=True).supports_thinking_toggle is True

    def test_merged_override(self):
        merged = ProviderCompat().merged({"supports_thinking_toggle": True})
        assert merged.supports_thinking_toggle is True


class TestRequestParamsThinkingInjection:
    def test_no_injection_without_declaration(self):
        client = _client_with_compat(ProviderCompat(supports_thinking_toggle=False))
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}],
            thinking_enabled=True, thinking_budget=2048,
        )
        assert "enable_thinking" not in params
        assert "thinking_budget" not in params

    def test_injection_when_declared(self):
        client = _client_with_compat(ProviderCompat(supports_thinking_toggle=True))
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}],
            thinking_enabled=True, thinking_budget=2048,
        )
        assert params["enable_thinking"] is True
        assert params["thinking_budget"] == 2048

    def test_disabled_thinking_drops_budget(self):
        client = _client_with_compat(ProviderCompat(supports_thinking_toggle=True))
        params = client._build_request_params(
            [{"role": "user", "content": "hi"}],
            thinking_enabled=False, thinking_budget=2048,
        )
        assert params["enable_thinking"] is False
        assert "thinking_budget" not in params

    def test_no_kwargs_no_injection(self):
        client = _client_with_compat(ProviderCompat(supports_thinking_toggle=True))
        params = client._build_request_params([{"role": "user", "content": "hi"}])
        assert "enable_thinking" not in params


class TestLoopPassthrough:
    def test_openai_loop_forwards_thinking_kwargs(self):
        from neurova.agent.loops.openai_loop import OpenAILoop

        import inspect

        src = inspect.getsource(OpenAILoop)
        assert '"thinking_enabled"' in src or "'thinking_enabled'" in src
        assert '"thinking_budget"' in src or "'thinking_budget'" in src


class TestConsoleContract:
    def test_chat_request_has_thinking_fields(self):
        from neurova.api.endpoints.console import ChatRequest

        req = ChatRequest(message="hi", thinking_enabled=True, thinking_budget=1024)
        assert req.thinking_enabled is True
        assert req.thinking_budget == 1024
