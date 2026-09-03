"""
P1 LLM 流式修复测试（2026-08 代码审计）

覆盖 bug:
1. LLMClient.chat_stream_async 使用同步 client 创建流，再 `async for` 同步 Stream
   → TypeError；async_client 从未被使用
2. MultiModelLLMClient.chat_stream 对同步生成器 chat_stream 使用 `async for`
   → TypeError，每次流式调用都失败并 yield {"error": ...}
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.llm_client import LLMClient, LLMConfig


class AsyncIter:
    """把普通列表包装成异步迭代器"""

    def __init__(self, items):
        self._items = list(items)

    def __aiter__(self):
        self._it = iter(self._items)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


def _make_chunk(text: str):
    delta = SimpleNamespace(content=text, tool_calls=None, reasoning_content=None)
    choice = SimpleNamespace(delta=delta, finish_reason=None)
    return SimpleNamespace(choices=[choice], model="test-model", id="chunk-1", usage=None)


def _make_client() -> LLMClient:
    client = LLMClient(LLMConfig(api_key="test-key", model="test-model"))
    client.client = MagicMock(name="sync_client")
    client.async_client = MagicMock(name="async_client")
    return client


class TestChatStreamAsync:
    @pytest.mark.asyncio
    async def test_uses_async_client_and_yields_chunks(self):
        client = _make_client()
        chunks = [_make_chunk("Hello"), _make_chunk(" world")]
        client.async_client.chat.completions.create = AsyncMock(return_value=AsyncIter(chunks))

        received = []
        async for resp in client.chat_stream_async([{"role": "user", "content": "hi"}]):
            received.append(resp.content)

        assert received == ["Hello", " world"]
        client.async_client.chat.completions.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_client_not_used_for_async_stream(self):
        client = _make_client()
        client.async_client.chat.completions.create = AsyncMock(
            return_value=AsyncIter([_make_chunk("x")])
        )

        async for _ in client.chat_stream_async([{"role": "user", "content": "hi"}]):
            pass

        client.client.chat.completions.create.assert_not_called()


class TestMultiModelChatStream:
    @pytest.mark.asyncio
    async def test_stream_yields_chunks_without_error(self):
        from neurova.llm.multi_model_client import ModelClient, MultiModelLLMClient

        mm = object.__new__(MultiModelLLMClient)

        inner = _make_client()

        async def fake_stream(messages, **kwargs):
            from neurova.llm_client import LLMResponse

            yield LLMResponse(content="part1", role="assistant", model="m")
            yield LLMResponse(content="part2", role="assistant", model="m")

        inner.chat_stream_async = fake_stream

        model_client = MagicMock(spec=ModelClient)
        model_client.client = inner

        mm._get_client_for_request = MagicMock(return_value=model_client)

        received = []
        async for chunk in mm.chat_stream([{"role": "user", "content": "hi"}]):
            received.append(chunk)

        assert len(received) == 2, f"流式调用失败或返回错误: {received}"
        assert all("error" not in (c if isinstance(c, dict) else {}) for c in received)
        assert [c.content for c in received] == ["part1", "part2"]
        model_client.increment_request.assert_called_once_with(success=True)
