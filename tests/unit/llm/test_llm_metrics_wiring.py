# -*- coding: utf-8 -*-
"""
P2-4 补刀：LLM 路径 prometheus 埋点接线测试

P2-4 宣称"tool/llm 埋点"，实际只有 tool_executor 接了 record_tool_execution；
record_llm_call 零调用点 → /metrics 的 neurova_llm_calls_total 恒 0。
本套件锁定：chat() 成功/失败/熔断三分支 + chat_stream 收尾都必须出埋点。
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.llm_client import LLMResponse
from neurova.llm.multi_model_client import MultiModelLLMClient
from neurova.llm.providers.rate_limiter import CircuitBreakerOpen


class _FakeMetrics:
    def __init__(self):
        self.llm_calls = []
        self.circuit_rejections = []

    def record_llm_call(self, provider, model, success, duration_s):
        self.llm_calls.append(
            {"provider": provider, "model": model, "success": success, "duration_s": duration_s}
        )

    def record_circuit_rejection(self, provider):
        self.circuit_rejections.append(provider)


class _ScriptedInner:
    def __init__(self, script):
        self.script = list(script)

    def chat(self, messages, **kwargs):
        behavior = self.script.pop(0)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _make_mmc(script, monkeypatch):
    inner = _ScriptedInner(script)
    client = SimpleNamespace(
        client=inner,
        model="test-model",
        provider=SimpleNamespace(id="p1"),
        increment_request=MagicMock(),
    )
    mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
    mmc._get_client_for_request = lambda model=None, provider_id=None: client

    fake = _FakeMetrics()
    monkeypatch.setattr("neurova.core.metrics.get_metrics", lambda: fake)
    return mmc, fake


class TestChatMetricsWiring:
    @pytest.mark.asyncio
    async def test_success_records_llm_call(self, monkeypatch):
        mmc, fake = _make_mmc([LLMResponse(content="ok")], monkeypatch)

        result = await mmc.chat([{"role": "user", "content": "hi"}])

        assert result["success"] is True
        assert len(fake.llm_calls) == 1
        rec = fake.llm_calls[0]
        assert rec["provider"] == "p1"
        assert rec["model"] == "test-model"
        assert rec["success"] is True
        assert rec["duration_s"] >= 0

    @pytest.mark.asyncio
    async def test_failure_records_llm_call_failed(self, monkeypatch):
        mmc, fake = _make_mmc([RuntimeError("boom")], monkeypatch)

        result = await mmc.chat([{"role": "user", "content": "hi"}])

        assert result["success"] is False
        assert len(fake.llm_calls) == 1
        assert fake.llm_calls[0]["success"] is False

    @pytest.mark.asyncio
    async def test_circuit_open_records_rejection_and_failure(self, monkeypatch):
        mmc, fake = _make_mmc([CircuitBreakerOpen("open")], monkeypatch)

        result = await mmc.chat([{"role": "user", "content": "hi"}])

        assert result["success"] is False
        assert fake.circuit_rejections == ["p1"]  # 既有行为保持
        assert len(fake.llm_calls) == 1
        assert fake.llm_calls[0]["success"] is False


class TestChatStreamMetricsWiring:
    @pytest.mark.asyncio
    async def test_stream_success_records_llm_call(self, monkeypatch):
        inner = SimpleNamespace(
            chat_stream_async=None,
        )

        async def fake_stream(messages, **kwargs):
            yield {"type": "content", "content": "a"}
            yield {"type": "done", "content": ""}

        inner.chat_stream_async = fake_stream

        client = SimpleNamespace(
            client=inner,
            model="test-model",
            provider=SimpleNamespace(id="p1"),
            increment_request=MagicMock(),
        )
        mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
        mmc._get_client_for_request = lambda model=None, provider_id=None: client

        fake = _FakeMetrics()
        monkeypatch.setattr("neurova.core.metrics.get_metrics", lambda: fake)

        chunks = [c async for c in mmc.chat_stream([{"role": "user", "content": "hi"}])]

        assert chunks and "error" not in chunks[-1]
        assert len(fake.llm_calls) == 1
        assert fake.llm_calls[0]["success"] is True

    @pytest.mark.asyncio
    async def test_stream_failure_records_llm_call_failed(self, monkeypatch):
        async def bad_stream(messages, **kwargs):
            yield {"type": "content", "content": "partial"}
            raise RuntimeError("stream broke")

        inner = SimpleNamespace(chat_stream_async=bad_stream)
        client = SimpleNamespace(
            client=inner,
            model="test-model",
            provider=SimpleNamespace(id="p1"),
            increment_request=MagicMock(),
        )
        mmc = MultiModelLLMClient.__new__(MultiModelLLMClient)
        mmc._get_client_for_request = lambda model=None, provider_id=None: client

        fake = _FakeMetrics()
        monkeypatch.setattr("neurova.core.metrics.get_metrics", lambda: fake)

        chunks = [c async for c in mmc.chat_stream([{"role": "user", "content": "hi"}])]

        assert chunks[-1].get("error")
        assert len(fake.llm_calls) == 1
        assert fake.llm_calls[0]["success"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
