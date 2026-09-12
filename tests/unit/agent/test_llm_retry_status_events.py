"""429 retry_status 事件转发链路单元测试（ZCode 对齐，2026-09-11）。

链路：multi_model_client.chat_stream 产出 ``{"retry_status": {...}}`` dict →
openai_loop._predict_stream_once 转成 ``{"type": "retry_status", "data": ...}``
事件（reset 时清空本轮半截回复）→ chat_pipeline._call_loop_stream 经
event_emitter 以 ("retry", data) 转发（emit_status_events 门控，蜂群子 Agent
纯文本流不受污染）→ console/chat SSE 桥映射为 ``{"type": "retry", ...}``。
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.loops.openai_loop import OpenAILoop


def run(coro):
    return asyncio.run(coro)


def _chunk(text):
    return SimpleNamespace(content=text, reasoning_content=None, usage=None,
                           tool_calls=None, finish_reason=None)


def _status(phase, reset=False, **extra):
    payload = {"phase": phase, "model": "m2", "reason": "rate_limited"}
    if reset:
        payload["reset"] = True
    payload.update(extra)
    return {"retry_status": payload}


class TestOpenAILoopRetryStatusEvents:
    def _loop(self, chunks):
        loop = OpenAILoop.__new__(OpenAILoop)
        loop.agent = MagicMock()
        loop.llm_client = SimpleNamespace(chat_stream=lambda messages, **kw: self._agen(chunks))
        return loop

    async def _agen(self, chunks):
        for c in chunks:
            yield c

    def test_retry_status_dict_forwarded_as_event(self):
        loop = self._loop([
            _chunk("前半"),
            _status("waiting", retry=1, max_retries=10, wait_seconds=10.0),
            _chunk("后半"),
        ])

        async def collect():
            events = []
            async for e in loop._predict_stream_once({"messages": [{"role": "user", "content": "q"}]}):
                events.append(e)
            return events

        events = run(collect())
        types = [e["type"] for e in events]
        assert types.count("retry_status") == 1
        assert types.count("content") == 2
        done = [e for e in events if e["type"] == "done"][0]
        # 无 reset：前半+后半都计入回复
        assert done["reply"] == "前半后半"

    def test_reset_event_clears_partial_reply(self):
        loop = self._loop([
            _chunk("前半"),
            _status("waiting", reset=True, retry=1),
            _chunk("后半"),
        ])

        async def collect():
            events = []
            async for e in loop._predict_stream_once({"messages": [{"role": "user", "content": "q"}]}):
                events.append(e)
            return events

        events = run(collect())
        rs = [e for e in events if e["type"] == "retry_status"]
        assert len(rs) == 1 and rs[0]["data"]["reset"] is True
        done = [e for e in events if e["type"] == "done"][0]
        # reset：半截"前半"作废，回复只剩重试后的"后半"（防重复拼接）
        assert done["reply"] == "后半"

    def test_error_dict_still_raises(self):
        loop = self._loop([{"error": "boom", "error_type": "rate_limited"}])

        async def collect():
            events = []
            async for e in loop._predict_stream_once({"messages": [{"role": "user", "content": "q"}]}):
                events.append(e)
            return events

        with pytest.raises(Exception):
            run(collect())


def make_pipeline(loop):
    """绕过 __init__ 的重依赖，构造最小可用 pipeline。"""
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = MagicMock()
    pipeline._agent._tool_messages_list = []
    pipeline._agent.loop = loop
    return pipeline


def make_loop_stream(events):
    async def gen():
        for e in events:
            yield e

    loop = MagicMock()

    async def predict_step(**kwargs):
        return gen()

    loop.predict_step = AsyncMock(side_effect=predict_step)
    return loop


class TestPipelineRetryForwarding:
    EVENTS = [
        {"type": "content", "data": "前半"},
        {"type": "retry_status", "data": {"phase": "waiting", "reset": True, "retry": 1}},
        {"type": "content", "data": "后半"},
        {"type": "done", "reply": "后半"},
    ]

    def test_forwarded_when_emit_status_events_enabled(self):
        pipeline = make_pipeline(loop=make_loop_stream(self.EVENTS))
        ctx = ChatContext(user_input="q", stream=True, metadata={"emit_status_events": True})
        collected = []
        ctx.event_emitter = lambda t, d: collected.append((t, d))

        reply = run(pipeline._call_loop_stream(ctx, tools_for_llm=None))

        assert reply == "后半"  # reset 清掉"前半"
        assert ("retry", {"phase": "waiting", "reset": True, "retry": 1}) in collected

    def test_not_forwarded_without_flag(self):
        """未开 emit_status_events（蜂群纯文本流）→ 不转发 retry 事件。"""
        pipeline = make_pipeline(loop=make_loop_stream(self.EVENTS))
        ctx = ChatContext(user_input="q", stream=True, metadata={})
        collected = []
        ctx.event_emitter = lambda t, d: collected.append((t, d))

        reply = run(pipeline._call_loop_stream(ctx, tools_for_llm=None))

        assert reply == "后半"
        assert all(t != "retry" for t, _ in collected)

    def test_emitter_exception_does_not_break_stream(self):
        pipeline = make_pipeline(loop=make_loop_stream(self.EVENTS))
        ctx = ChatContext(user_input="q", stream=True, metadata={"emit_status_events": True})

        def bad_emitter(t, d):
            raise RuntimeError("发射失败")

        ctx.event_emitter = bad_emitter
        reply = run(pipeline._call_loop_stream(ctx, tools_for_llm=None))
        assert reply == "后半"


class TestLegacyStreamReset:
    def test_legacy_clears_reply_on_reset(self):
        pipeline = ChatPipeline.__new__(ChatPipeline)
        chunks = [_chunk("前半"), _status("waiting", reset=True), _chunk("后半")]

        async def _agen(cs):
            for c in cs:
                yield c

        pipeline._agent = MagicMock()
        # llm_client 是只读属性（读 self._agent.llm_client），经 agent 注入
        pipeline._agent.llm_client = SimpleNamespace(chat_stream=lambda messages: _agen(chunks))

        reply = run(pipeline._call_legacy_stream(
            ChatContext(user_input="q", stream=True, metadata={})
        ))
        assert reply == "后半"


class TestConsoleBridgeMapping:
    def test_retry_kind_mapped_to_sse_event(self):
        from neurova.api.endpoints.console import _sse_events_from_emitter_item

        events = _sse_events_from_emitter_item(
            ("retry", {"phase": "waiting", "retry": 2, "wait_seconds": 10.0}),
            set(), set(),
        )
        assert events == [{"type": "retry", "phase": "waiting", "retry": 2, "wait_seconds": 10.0}]

    def test_retry_kind_non_dict_ignored(self):
        from neurova.api.endpoints.console import _sse_events_from_emitter_item

        assert _sse_events_from_emitter_item(("retry", None), set(), set()) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
