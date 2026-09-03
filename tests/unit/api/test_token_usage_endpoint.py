"""
/stats/token-usage 端点测试（防回归）

锁定：TokenUsageAccounting（进程级真实记账）必须经 /api/v1/stats/token-usage 暴露，
否则 Dashboard 的 token/调用统计永远拿不到数据（stub 恒 0）。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import stats as stats_endpoint
from neurova.core.usage_accounting import get_usage_accounting, reset_usage_accounting


@pytest.fixture(autouse=True)
def _clean_usage():
    reset_usage_accounting()
    yield
    reset_usage_accounting()


class TestTokenUsageEndpoint:
    @pytest.mark.asyncio
    async def test_returns_snapshot_totals(self):
        """total.calls / total_tokens 应取自记账器真实累计。"""
        acc = get_usage_accounting()
        acc.record(model="gpt-4o", provider="openai", prompt_tokens=100, completion_tokens=50)
        acc.record(model="deepseek-chat", provider="deepseek", prompt_tokens=10, completion_tokens=5)

        res = await stats_endpoint.get_token_usage(MagicMock())

        assert res["total"]["calls"] == 2
        assert res["total"]["prompt_tokens"] == 110
        assert res["total"]["completion_tokens"] == 55
        assert res["total"]["total_tokens"] == 165

    @pytest.mark.asyncio
    async def test_by_model_breakdown(self):
        """by_model 应按模型拆分明细（供前端 token 分布图）。"""
        acc = get_usage_accounting()
        acc.record(model="gpt-4o", provider="openai", prompt_tokens=100, completion_tokens=50)

        res = await stats_endpoint.get_token_usage(MagicMock())

        models = {m["model"]: m for m in res["by_model"]}
        assert "gpt-4o" in models
        assert models["gpt-4o"]["calls"] == 1
        assert models["gpt-4o"]["total_tokens"] == 150

    @pytest.mark.asyncio
    async def test_no_records_returns_zero_state(self):
        """无调用记录时返回零态而非报错。"""
        res = await stats_endpoint.get_token_usage(MagicMock())
        assert res["total"]["calls"] == 0
        assert res["total"]["total_tokens"] == 0
        assert res["by_model"] == []


class TestStreamUsageAccounting:
    """流式链路必须真实入账（根因：底层从不请求 usage + 流式路径无 record 接线）。

    反向锁定：Dashboard 的 token/调用显示 0 不是前端问题，而是
      a) LLMClient 流式 params 从未发 stream_options.include_usage（OpenAI 协议不回传 usage）
      b) MultiModelLLMClient.chat_stream 真实分支只透传 chunk，从不记录调用
    """

    @pytest.mark.asyncio
    async def test_chat_stream_records_call_and_usage(self, monkeypatch):
        """multi_model chat_stream 透传结束必须 record（calls+1、usage 聚合）。"""
        from types import SimpleNamespace

        from neurova.core.usage_accounting import get_usage_accounting
        from neurova.llm.multi_model_client import MultiModelLLMClient
        from neurova.llm_client import LLMResponse

        async def fake_stream(messages, **kwargs):
            yield LLMResponse(content="hello", model="gpt-4o", usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7})
            yield LLMResponse(content="", model="gpt-4o", usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5})

        fake_client = SimpleNamespace(
            client=SimpleNamespace(chat_stream_async=fake_stream),
            model="gpt-4o",
            provider=SimpleNamespace(id="openai"),
            increment_request=lambda success=None: None,
            error_count=0,
            request_count=0,
        )

        multi = MultiModelLLMClient.__new__(MultiModelLLMClient)
        multi._get_client_for_request = lambda model=None, provider_id=None: fake_client  # type: ignore[attr-defined]
        multi.increment_request = lambda *a, **k: None  # type: ignore[attr-defined]

        chunks = [c async for c in multi.chat_stream([{"role": "user", "content": "hi"}])]

        assert any(getattr(c, "content", "") == "hello" for c in chunks)
        acc = get_usage_accounting().snapshot()
        assert acc["total"]["calls"] == 1, acc
        # OpenAI 流式 usage 在末 chunk 携带全量 → last-wins（5），逐 chunk 累加才得 12（双计）
        assert acc["total"]["total_tokens"] == 5, acc

    @pytest.mark.asyncio
    async def test_chat_stream_falls_back_to_tiktoken_estimate_when_usage_missing(self, monkeypatch):
        """网关不回传 usage（实测 sensetime 流式恒空）时按 tiktoken 估值入账并标记 estimated。"""
        from neurova.core.usage_accounting import get_usage_accounting
        from neurova.llm.multi_model_client import MultiModelLLMClient
        from neurova.llm_client import LLMResponse

        async def fake_stream(messages, **kwargs):
            yield LLMResponse(content="你好呀朋友", model="deepseek-v4-flash")
            yield LLMResponse(content="", model="deepseek-v4-flash")

        fake_client = SimpleNamespace(
            client=SimpleNamespace(
                chat_stream_async=fake_stream,
                count_tokens=lambda text: 7,
                count_message_tokens=lambda messages, tools=None: 11,
            ),
            model="deepseek-v4-flash",
            provider=SimpleNamespace(id="sensetime"),
            increment_request=lambda success=None: None,
            error_count=0,
            request_count=0,
        )

        multi = MultiModelLLMClient.__new__(MultiModelLLMClient)
        multi._get_client_for_request = lambda model=None, provider_id=None: fake_client  # type: ignore[attr-defined]

        chunks = [c async for c in multi.chat_stream([{"role": "user", "content": "hi"}])]
        assert len(chunks) == 2

        acc = get_usage_accounting().snapshot()
        assert acc["total"]["calls"] == 1, acc
        assert acc["total"]["estimated_calls"] == 1, acc
        assert acc["total"]["prompt_tokens"] == 11, acc
        assert acc["total"]["completion_tokens"] == 7, acc
        assert acc["by_model"]["deepseek-v4-flash"]["estimated_calls"] == 1, acc

    @pytest.mark.asyncio
    async def test_llm_client_stream_params_request_usage(self, monkeypatch):
        """LLMClient 流式请求必须携带 stream_options.include_usage（否则 chunk.usage 恒 None）。"""
        from neurova.llm_client import LLMClient, LLMConfig

        client = LLMClient(LLMConfig(api_key="sk-test", base_url="https://example.com/v1", model="gpt-4o"))

        captured: dict = {}

        class FakeCompletions:
            async def create(self, **params):
                captured.update(params)
                return _FakeStream()

        client.async_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))  # type: ignore[attr-defined]

        collected = []
        async for chunk in client.chat_stream_async([{"role": "user", "content": "hi"}]):
            collected.append(chunk)

        # 根因断言：请求参数必须请求 usage 回传（OpenAI 协议默认不回传）
        assert captured, "chat.completions.create 必须被调用"
        assert captured.get("stream_options") == {"include_usage": True}, captured


class _FakeStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        from types import SimpleNamespace

        raise StopAsyncIteration  # 无 chunk 也返回（params 断言在 create 捕获层完成）
