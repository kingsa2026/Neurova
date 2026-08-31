"""ChatPipeline 事件发射通道（蜂群子 Agent 逐 token 流式）单元测试"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline


def make_pipeline(loop=None):
    """绕过 __init__ 的重依赖，构造最小可用 pipeline"""
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = MagicMock()
    pipeline._agent._tool_messages_list = []
    if loop is not None:
        pipeline._agent.loop = loop
    return pipeline


def make_loop_stream(events):
    """构造 predict_step 返回 async 事件流的 mock loop"""

    async def gen():
        for e in events:
            yield e

    loop = MagicMock()

    async def predict_step(**kwargs):
        return gen()

    loop.predict_step = AsyncMock(side_effect=predict_step)
    return loop


def run(coro):
    return asyncio.run(coro)


class TestStreamEmitterForwarding:
    """流式 chunk 转发给 event_emitter"""

    def test_content_and_reasoning_forwarded(self):
        pipeline = make_pipeline(loop=make_loop_stream(
            [
                {"type": "reasoning", "data": "思考中"},
                {"type": "content", "data": "你好"},
                {"type": "content", "data": "，世界"},
                {"type": "tool_call", "data": {"name": "t"}},
                {"type": "done", "reply": "你好，世界"},
            ]
        ))
        ctx = ChatContext(user_input="q", stream=True)
        collected = []
        ctx.event_emitter = lambda t, d: collected.append((t, d))

        reply = run(pipeline._call_loop_stream(ctx, tools_for_llm=None))

        assert reply == "你好，世界"
        # reasoning + 2 个 content 转发；tool_call/done 不转发
        assert ("reasoning", "思考中") in collected
        assert ("content", "你好") in collected
        assert ("content", "，世界") in collected
        assert all(t != "tool_call" for t, _ in collected)

    def test_emitter_exception_does_not_break_stream(self):
        pipeline = make_pipeline(loop=make_loop_stream([{"type": "content", "data": "ok"}]))
        ctx = ChatContext(user_input="q", stream=True)

        def bad_emitter(t, d):
            raise RuntimeError("发射失败")

        ctx.event_emitter = bad_emitter
        reply = run(pipeline._call_loop_stream(ctx, tools_for_llm=None))
        assert reply == "ok"

    def test_no_emitter_still_aggregates(self):
        pipeline = make_pipeline(loop=make_loop_stream([{"type": "content", "data": "abc"}]))
        ctx = ChatContext(user_input="q", stream=True)
        reply = run(pipeline._call_loop_stream(ctx, tools_for_llm=None))
        assert reply == "abc"


class TestSessionIdPassthrough:
    """_init_agent_state 透传 session_id 与 metadata 中的 emitter"""

    def test_session_id_stored_on_agent(self):
        pipeline = make_pipeline()
        ctx = ChatContext(user_input="q", session_id="sess-9")
        pipeline._init_agent_state(ctx)
        # P3-c 收窄：身份经 set_request_identity 显式 API 透传（MagicMock 记录调用；
        # user_id 缺省由 Agent.set_request_identity 内部落 "default"，管线只透传原值）
        pipeline._agent.set_request_identity.assert_called_once_with(
            user_input="q", session_id="sess-9", user_id=None
        )

    def test_emitter_promoted_from_metadata(self):
        pipeline = make_pipeline()
        emitter = MagicMock()
        ctx = ChatContext(user_input="q", metadata={"event_emitter": emitter})
        assert ctx.event_emitter is None
        pipeline._init_agent_state(ctx)
        assert ctx.event_emitter is emitter

    def test_explicit_emitter_not_overridden(self):
        pipeline = make_pipeline()
        explicit, in_metadata = MagicMock(), MagicMock()
        ctx = ChatContext(user_input="q", metadata={"event_emitter": in_metadata}, event_emitter=explicit)
        pipeline._init_agent_state(ctx)
        assert ctx.event_emitter is explicit
