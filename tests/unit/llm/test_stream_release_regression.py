"""RES-P0-1 回归测试：chat_stream 成功/中断路径必须释放并发槽位。

背景（docs/资源型Bug扫描报告_2026-09-11.md P0-1）：
df34c204（BUG AUDIT L-03）把成功路径的 limiter.release 误判为"重复 release"
删除，导致 ModelRateLimiter._concurrent 单调递增——默认 max_concurrent=8，
8 次成功/中断流式后该模型对所有用户永久返回"模型限流"，直到进程重启。
消费方中途放弃（aclose → GeneratorExit）与 CancelledError 是 BaseException，
不走 except Exception 分支，同样漏释放。

验收：任意退出路径（成功/异常/中途放弃）后 current_concurrent 必须归零；
连续 max_concurrent+1 次成功流式不得触发限流。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.llm.model_rate_limiter import ModelRateLimiter
from neurova.llm_client import LLMClient, LLMConfig


def _make_chunk(text: str, with_usage: bool = False):
    usage = None
    if with_usage:
        usage = SimpleNamespace(prompt_tokens=1, completion_tokens=1, cache_read_tokens=0, cache_write_tokens=0)
    return SimpleNamespace(
        content=text, reasoning_content=None, usage=usage,
        tool_calls=None, finish_reason="stop" if with_usage else None,
    )


def _make_inner() -> LLMClient:
    client = LLMClient(LLMConfig(api_key="test-key", model="test-model"))
    client.client = MagicMock(name="sync_client")
    client.async_client = MagicMock(name="async_client")
    return client


def _make_mm_with_stream(fake_stream):
    """构造 MultiModelLLMClient 骨架，注入假流与隔离限流器。"""
    from neurova.llm.multi_model_client import ModelClient, MultiModelLLMClient

    mm = object.__new__(MultiModelLLMClient)
    inner = _make_inner()
    inner.chat_stream_async = fake_stream
    # 隔离真实 usage 落库：单测不写 usage_history
    inner.count_message_tokens = MagicMock(return_value=0)

    model_client = MagicMock(spec=ModelClient)
    model_client.client = inner
    model_client.model = "m"
    model_client.provider = MagicMock(id="p")
    mm._get_client_for_request = MagicMock(return_value=model_client)
    return mm


@pytest.fixture
def isolated_limiter(monkeypatch):
    """每次测试给一个干净的共享限流器（max_concurrent=8，与生产默认一致）。"""
    limiter = ModelRateLimiter(max_concurrent=8)
    monkeypatch.setattr(
        "neurova.llm.model_rate_limiter.get_shared_limiter", lambda: limiter
    )
    return limiter


@pytest.fixture(autouse=True)
def isolate_usage_recording(monkeypatch):
    """隔离 usage_accounting / usage_history 真实落库（单测无副作用）。"""
    import neurova.core.usage_accounting as ua
    import neurova.core.usage_history as uh

    ua_mock = MagicMock()
    ua_mock.record.return_value = 1
    monkeypatch.setattr(ua, "get_usage_accounting", lambda: ua_mock)
    monkeypatch.setattr(ua, "set_task_last_call", lambda *_: None)
    uh_mock = MagicMock()
    monkeypatch.setattr(uh, "get_usage_history", lambda: uh_mock)


def _ok_stream(chunks):
    async def fake_stream(messages, **kwargs):
        for c in chunks:
            yield c
    return fake_stream


@pytest.mark.asyncio
async def test_stream_success_releases_concurrency_slot(isolated_limiter):
    """成功消费完整流后并发槽位必须归还。"""
    mm = _make_mm_with_stream(_ok_stream([_make_chunk("a"), _make_chunk("b", with_usage=True)]))

    received = [c async for c in mm.chat_stream([{"role": "user", "content": "hi"}])]
    assert [c.content for c in received] == ["a", "b"]
    assert isolated_limiter.current_concurrent("m") == 0, (
        "流式成功路径未释放并发槽位（RES-P0-1）"
    )


@pytest.mark.asyncio
async def test_stream_abandon_releases_concurrency_slot(isolated_limiter):
    """消费方中途放弃（aclose 触发 GeneratorExit）也必须归还槽位。"""

    async def fake_stream(messages, **kwargs):
        yield _make_chunk("first")
        await asyncio.sleep(30)  # 模拟上游长流，被 aclose 打断

    mm = _make_mm_with_stream(fake_stream)
    gen = mm.chat_stream([{"role": "user", "content": "hi"}])
    first = await gen.__anext__()
    assert first.content == "first"

    await gen.aclose()
    # 给 done_callback / finally 一拍机会
    await asyncio.sleep(0)
    assert isolated_limiter.current_concurrent("m") == 0, (
        "流式被消费方中断后未释放并发槽位（RES-P0-1，GeneratorExit 漏斗）"
    )


@pytest.mark.asyncio
async def test_stream_error_releases_concurrency_slot(isolated_limiter):
    """流内异常路径必须归还槽位（既有 finally 行为，防回归守卫）。"""
    got_exc = asyncio.Event()

    async def fake_stream(messages, **kwargs):
        yield _make_chunk("x")
        got_exc.set()
        raise RuntimeError("upstream boom")

    mm = _make_mm_with_stream(fake_stream)
    received = [c async for c in mm.chat_stream([{"role": "user", "content": "hi"}])]
    assert got_exc.is_set()
    assert any(isinstance(c, dict) and "error" in c for c in received), received
    assert isolated_limiter.current_concurrent("m") == 0


@pytest.mark.asyncio
async def test_nine_successive_streams_do_not_hit_concurrency_cap(isolated_limiter):
    """max_concurrent=8 下连续 9 次成功流式必须全部可用（核心复现场景）。"""
    for i in range(9):
        mm = _make_mm_with_stream(_ok_stream([_make_chunk(f"r{i}", with_usage=True)]))
        received = [c async for c in mm.chat_stream([{"role": "user", "content": "hi"}])]
        errors = [c for c in received if isinstance(c, dict) and "error" in c]
        assert not errors, f"第 {i + 1} 次流式被误限流: {errors}"
        assert isolated_limiter.current_concurrent("m") == 0
