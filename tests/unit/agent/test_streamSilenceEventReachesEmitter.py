# -*- coding: utf-8 -*-
"""静默事件的转发链（§6-397 批 H · C）：环 → 管道 → emitter。

`multi_model_client.chat_stream` 让出 `{"stream_status": {...}}` 只是第一步；这条链上
任何一环不认识它，用户就什么都看不见——而"上游静默几分钟"的体感恰恰发生在**用户那一侧**，
日志留痕再多也不解决问题（2026-10-22 事故里 60/120/180/240s 四段 WARNING 全在日志里）。

转发形态与既有 `retry_status` 同族：环转 typed 事件 → 管道在 `emit_status_events`
门控下 emit → 端点映射成 SSE。门控的理由也一样：这条通道同时服务蜂群子 Agent 的
纯文本流，默认不透传。

另钉一格：状态事件**不入正文**（Bug N-6 的老形态——非 content 事件被拼进回复文本）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.loops.anthropic_loop import AnthropicLoop
from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse

PAYLOAD = {
    "phase": "silence",
    "provider": "amd",
    "model": "GLM-5.3-Flash",
    "silent_seconds": 180.4,
    "reasoning_chars": 16384,
    "content_chars": 0,
    "read_timeout": 300,
}


def run(coro):
    return asyncio.run(coro)


def _statusItem():
    return {"stream_status": dict(PAYLOAD)}


class _Stream:
    def __init__(self, items):
        self.items = items

    async def chat_stream(self, messages, **kwargs):
        for item in self.items:
            yield item


def makeOpenAiLoop(items):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent._round_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    agent.skill_registry = None
    stream = _Stream(items)
    loop = OpenAILoop(agent)
    loop.llm_client = stream
    loop.agent.llm_client = stream
    return loop


def makeAnthropicLoop(items):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent._round_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    agent.skill_registry = None
    agent.config.name = "silence-probe"
    agent.config.agent_id = "silence-probe-id"
    agent.config.llm_model = "claude-3-5-sonnet"
    stream = _Stream(items)
    loop = AnthropicLoop(agent)
    loop.llm_client = stream
    loop.agent.llm_client = stream
    return loop


def collect(genFactory):
    async def go():
        gen = genFactory()
        if not hasattr(gen, "__aiter__"):
            gen = await gen
        return [e async for e in gen]

    return run(go())


class TestLoopsForwardStatusEvent:
    def testOpenAiLoopEmitsTypedStreamStatusEvent(self):
        loop = makeOpenAiLoop([
            LLMResponse(content="我先看一下。"),
            _statusItem(),
            LLMResponse(content="", finish_reason="stop"),
        ])
        events = collect(lambda: loop._predict_stream(
            {"messages": [{"role": "user", "content": "hi"}], "stream": True}
        ))
        statuses = [e for e in events if isinstance(e, dict) and e.get("type") == "stream_status"]
        assert len(statuses) == 1, f"环把不认识的控制字典丢了：{[e.get('type') for e in events]}"
        assert statuses[0]["data"]["silent_seconds"] == PAYLOAD["silent_seconds"], statuses[0]
        # 反向格：状态事件不入正文（Bug N-6 形态）
        done = [e for e in events if e.get("type") == "done"]
        assert done[0]["reply"] == "我先看一下。", done[0]

    def testAnthropicLoopEmitsTypedStreamStatusEvent(self):
        loop = makeAnthropicLoop([
            LLMResponse(content="我先看一下。"),
            _statusItem(),
            LLMResponse(content="", finish_reason="stop"),
        ])
        events = collect(lambda: loop.predict_step(
            [{"role": "user", "content": "hi"}], tools=None, stream=True
        ))
        statuses = [e for e in events if isinstance(e, dict) and e.get("type") == "stream_status"]
        assert len(statuses) == 1, [e.get("type") for e in events]
        assert statuses[0]["data"]["provider"] == "amd", statuses[0]


def makePipeline(loop):
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = MagicMock()
    pipeline._agent._tool_messages_list = []
    pipeline._agent.loop = loop
    return pipeline


def makeLoopStream(events):
    async def gen():
        for e in events:
            yield e

    loop = MagicMock()

    async def predict_step(**kwargs):
        return gen()

    loop.predict_step = AsyncMock(side_effect=predict_step)
    return loop


class TestPipelineEmitsUpstreamStatus:
    EVENTS = [
        {"type": "content", "data": "我先看一下。"},
        {"type": "stream_status", "data": dict(PAYLOAD)},
        {"type": "done", "reply": "我先看一下。", "finish_reason": "stop"},
    ]

    def _drive(self, metadata):
        pipeline = makePipeline(loop=makeLoopStream(self.EVENTS))
        ctx = ChatContext(user_input="q", stream=True, metadata=metadata)
        collected = []
        ctx.event_emitter = lambda t, d: collected.append((t, d))
        reply = run(pipeline._call_loop_stream(ctx, tools_for_llm=None))
        return reply, collected

    def testEmittedUnderStatusGate(self):
        reply, collected = self._drive({"emit_status_events": True})
        assert ("upstream_status", dict(PAYLOAD)) in collected, collected
        assert reply == "我先看一下。", f"状态事件混进了正文：{reply!r}"

    def testNotEmittedWithoutGate(self):
        """默认关：蜂群子 Agent 的纯文本流不受污染（与 retry 同律）。"""
        _reply, collected = self._drive({})
        assert all(t != "upstream_status" for t, _ in collected), collected


class TestSseFrameMapping:
    """端点映射：`("upstream_status", payload)` 必须变成一个 SSE 事件而不是被丢掉。

    `chat.py` 那侧的帧在生产端点生成器里，单测拿不到——由本批活体走真
    `/api/v1/chat/stream` 取帧证明（见提交说明）。
    """

    def testConsoleMapsUpstreamStatusToItsOwnEvent(self):
        from neurova.api.endpoints.console import _sse_events_from_emitter_item

        events = _sse_events_from_emitter_item(("upstream_status", dict(PAYLOAD)), set(), set())
        assert events == [{"type": "upstream_status", **PAYLOAD}], events

    def testConsoleIgnoresEmptyPayload(self):
        """空 payload 不出空帧（与 retry/usage 同律，前端不该收到无内容的事件）。"""
        from neurova.api.endpoints.console import _sse_events_from_emitter_item

        assert _sse_events_from_emitter_item(("upstream_status", {}), set(), set()) == []


class TestLegacyPathAlsoForwards:
    """`_call_legacy_stream` 直读 chat_stream、不经环——同一个上游事件在这条路上也不能哑。"""

    def testLegacyEmitsUpstreamStatusUnderGate(self):
        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = SimpleNamespace(_tool_messages_list=[])
        items = [
            SimpleNamespace(content="先看一下。", reasoning_content=None, usage=None,
                            tool_calls=None, finish_reason=None),
            _statusItem(),
            SimpleNamespace(content="", reasoning_content=None, usage=None,
                            tool_calls=None, finish_reason="stop"),
        ]

        class _LegacyClient:
            async def chat_stream(self, messages, **kwargs):
                for item in items:
                    yield item

        pipeline._agent.llm_client = _LegacyClient()
        ctx = ChatContext(user_input="q", stream=True, metadata={"emit_status_events": True})
        collected = []
        ctx.event_emitter = lambda t, d: collected.append((t, d))
        reply = run(pipeline._call_legacy_stream(ctx))
        assert ("upstream_status", dict(PAYLOAD)) in collected, collected
        assert reply == "先看一下。", reply
