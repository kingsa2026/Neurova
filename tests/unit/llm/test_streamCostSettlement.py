# -*- coding: utf-8 -*-
"""CORE-06：流式 LLM 在异常/取消/消费方提前结束时也必须结算已收 usage。

根因：`record_llm_cost()` 写在完整流循环之后，异常、取消、消费方提前 `break`
都会跳过；`finally` 只关上游流。已消耗 token 因此不入账，配额与账单失真。
判据走真实成本账本（安装 LlmCostStore 到临时库后查 llm_calls 行），不替身记账函数。
"""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from neurova.llm_client import LLMClient, LLMConfig
from neurova.models.cost_store import LlmCostStore


def _usage(prompt: int = 10, completion: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion
    )


def _chunk(content: str = "hi", usage: SimpleNamespace | None = None,
           finish_reason: str | None = None) -> SimpleNamespace:
    delta = SimpleNamespace(content=content, tool_calls=None, reasoning_content=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        model="gpt-4o",
        usage=usage,
        id="chunk-1",
    )


class _ExplodingStream:
    """先给一个带 usage 的 chunk，再模拟上游断流。"""

    def __init__(self) -> None:
        self._items = [_chunk(usage=_usage())]
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._items:
            return self._items.pop(0)
        raise RuntimeError("upstream stream cut")

    def close(self) -> None:
        self.closed = True


class _ExplodingAsyncStream:
    def __init__(self) -> None:
        self._items = [_chunk(usage=_usage())]
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._items:
            return self._items.pop(0)
        raise RuntimeError("upstream async stream cut")

    async def close(self) -> None:
        self.closed = True


class _CleanStream:
    """正常收流：末 chunk 携带 usage。"""

    def __init__(self) -> None:
        self._items = [_chunk(content="a"), _chunk(usage=_usage(7, 3), finish_reason="stop")]

    def __iter__(self):
        return self

    def __next__(self):
        if self._items:
            return self._items.pop(0)
        raise StopIteration

    def close(self) -> None:
        pass


@pytest.fixture()
def costDb(tmp_path):
    LlmCostStore.uninstall()
    LlmCostStore.install(str(tmp_path / "llm_cost.db"))
    try:
        yield tmp_path / "llm_cost.db"
    finally:
        LlmCostStore.uninstall()


def _client(fakeStream, *, isAsync: bool = False) -> LLMClient:
    client = LLMClient(LLMConfig(api_key="", model="gpt-4o"))
    client.client = object()
    client.async_client = object()
    if isAsync:
        async def _create(_c, _p):
            return fakeStream
        client._createCompletionAsync = _create
    else:
        client._createCompletion = lambda _c, _p: fakeStream
    return client


def _rows(dbPath):
    conn = sqlite3.connect(str(dbPath))
    try:
        return conn.execute(
            "SELECT direction, input_tokens, output_tokens FROM llm_calls ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def testStreamExceptionStillSettlesCapturedUsage(costDb):
    """流中途断流：已收 usage 必须入账（异常照常上抛）。"""
    stream = _ExplodingStream()
    client = _client(stream)

    with pytest.raises(Exception):
        for _ in client.chat_stream([{"role": "user", "content": "x"}]):
            pass

    assert _rows(costDb) == [("output", 10, 5)]
    assert stream.closed is True


def testConsumerBreakStillSettlesCapturedUsage(costDb):
    """消费方提前 break（GeneratorExit）：已收 usage 入账。"""
    client = _client(_ExplodingStream())

    gen = client.chat_stream([{"role": "user", "content": "x"}])
    next(gen)
    gen.close()

    assert _rows(costDb) == [("output", 10, 5)]


def testSuccessPathRecordsExactlyOnce(costDb):
    """正常收流：一次且仅一次，无 finally 重复记账。"""
    client = _client(_CleanStream())

    chunks = list(client.chat_stream([{"role": "user", "content": "x"}]))

    assert len(chunks) == 2
    assert _rows(costDb) == [("output", 7, 3)]


@pytest.mark.asyncio
async def testAsyncStreamExceptionStillSettlesCapturedUsage(costDb):
    """异步流中途断流：已收 usage 必须入账。"""
    stream = _ExplodingAsyncStream()
    client = _client(stream, isAsync=True)

    gen = client.chat_stream_async([{"role": "user", "content": "x"}])
    with pytest.raises(Exception):
        async for _ in gen:
            pass

    assert _rows(costDb) == [("output", 10, 5)]
    assert stream.closed is True