# -*- coding: utf-8 -*-
"""④ 收尾：LLMClient.chat_stream_async 消费方中断必须显式关上游流。

现象（live-verify 观察）：消费方 aclose 后依赖 GC 最终化 httpx2
aiter_bytes，与在途迭代竞态 → "aclose(): asynchronous generator is
already running"。根因：chat_stream_async 无 finally 关 stream。
契约：无论正常收流还是消费方中途放弃，上游 stream.close() 都必须被调用。
"""

from types import SimpleNamespace

import pytest

from neurova.llm_client import LLMClient, LLMConfig


class _SpyAsyncStream:
    """openai AsyncStream 替身：逐个吐分片；记录 close 是否被调用。"""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.chunks:
            raise StopAsyncIteration
        return self.chunks.pop(0)

    async def close(self):
        self.closed = True


def _chunk(content):
    return SimpleNamespace(
        id="c1", model="m",
        choices=[SimpleNamespace(
            index=0,
            delta=SimpleNamespace(content=content, reasoning_content=None,
                                  tool_calls=None),
            finish_reason=None)],
        usage=None,
    )


class TestAsyncStreamClose:
    def _wire(self, llm, stream):
        async def _create(**params):
            return stream

        llm.async_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))

    @pytest.mark.asyncio
    async def test_close_called_on_consumer_abort(self):
        """消费方中途 aclose → 上游 stream.close() 必须被调用（不留给 GC）。"""
        llm = LLMClient(LLMConfig(api_key="sk", base_url="http://127.0.0.1:1/v1",
                                  model="m"))
        spy = _SpyAsyncStream([_chunk("a"), _chunk("b")])
        self._wire(llm, spy)
        agen = llm.chat_stream_async([{"role": "user", "content": "x"}])
        first = await agen.__anext__()
        assert first.content == "a"
        await agen.aclose()
        assert spy.closed is True

    @pytest.mark.asyncio
    async def test_close_called_on_normal_completion(self):
        """正常收流完毕 → 上游 stream.close() 同样被调用。"""
        llm = LLMClient(LLMConfig(api_key="sk", base_url="http://127.0.0.1:1/v1",
                                  model="m"))
        spy = _SpyAsyncStream([_chunk("a")])
        self._wire(llm, spy)
        got = [c.content async for c in
               llm.chat_stream_async([{"role": "user", "content": "x"}])]
        assert got == ["a"]
        assert spy.closed is True


class _SpySyncStream:
    """openai 同步 Stream 替身：可迭代分片；记录 close 是否被调用。"""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if not self.chunks:
            raise StopIteration
        return self.chunks.pop(0)

    def close(self):
        self.closed = True


class TestSyncStreamClose:
    """对称契约：同步 chat_stream 与异步版同规——中断/正常都显式关流。"""

    def _wire(self, llm, stream):
        def _create(**params):
            return stream

        llm.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))

    def test_close_called_on_consumer_abort(self):
        """消费方中途 close（GeneratorExit）→ 上游 stream.close() 必须被调用。"""
        llm = LLMClient(LLMConfig(api_key="sk", base_url="http://127.0.0.1:1/v1",
                                  model="m"))
        spy = _SpySyncStream([_chunk("a"), _chunk("b")])
        self._wire(llm, spy)
        gen = llm.chat_stream([{"role": "user", "content": "x"}])
        first = next(gen)
        assert first.content == "a"
        gen.close()
        assert spy.closed is True

    def test_close_called_on_normal_completion(self):
        """正常收流完毕 → 上游 stream.close() 同样被调用。"""
        llm = LLMClient(LLMConfig(api_key="sk", base_url="http://127.0.0.1:1/v1",
                                  model="m"))
        spy = _SpySyncStream([_chunk("a")])
        self._wire(llm, spy)
        got = [c.content for c in
               llm.chat_stream([{"role": "user", "content": "x"}])]
        assert got == ["a"]
        assert spy.closed is True
