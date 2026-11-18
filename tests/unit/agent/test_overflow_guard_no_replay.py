# -*- coding: utf-8 -*-
"""QwenPaw 对照批 C3：管线级溢出兜底的"不重放有效输出"约束。

loop 层已有 gotContent 门（openai_loop._resumeAfterOverflow：已产出即不
续跑）；但溢出逃逸到管线后，`_callAgentLoopWithOverflowGuard` 会压缩并
整体重试一次——流式路径里重试前已让出的半截正文会与新回复拼接/重复。
约束：已有可见输出（ctx.partial_reply 非空）时，重试前必须先发
reset 语义的 retry 事件（消费方清空半截，与流内切换同一协议）。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.llm_client import TokenLimitExceeded


def run(coro):
    return asyncio.run(coro)


def make_pipeline():
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = MagicMock()
    return pipeline


def overflowOnceThen(pipeline, ctx, secondReply="重试后的完整回复", markPartial=True):
    """第一次调用：标记已产出半截并抛溢出；第二次调用：返回重试结果。

    markPartial=False 模拟"产出从未出管线"（非流式路径没有半截快照）。
    """
    calls = []

    async def fake_call(ctx_, tools_):
        calls.append(1)
        if len(calls) == 1:
            if markPartial:
                ctx.partial_reply = "前半"
            raise TokenLimitExceeded("context_length_exceeded: 上下文溢出")
        return secondReply

    pipeline._call_agent_loop = fake_call
    return calls


class TestOverflowGuardNoReplay:
    def test_partial_emitted_retry_announces_reset(self):
        """已有可见输出 → 压缩重试前必须发 reset 事件（消费方清空半截）。"""
        pipeline = make_pipeline()
        ctx = ChatContext(user_input="q", stream=True,
                          metadata={"emit_status_events": True})
        seen = []
        ctx.event_emitter = lambda t, d: seen.append((t, d))
        calls = overflowOnceThen(pipeline, ctx)
        pipeline._compactTurnContext = AsyncMock(return_value=True)
        pipeline._recordCompactionFailure = MagicMock()

        reply = run(pipeline._callAgentLoopWithOverflowGuard(ctx, None))

        assert len(calls) == 2, "压缩后应重试恰好一次"
        assert reply == "重试后的完整回复"
        resets = [d for t, d in seen if t == "retry" and isinstance(d, dict) and d.get("reset")]
        assert resets, (
            f"重试前未发 reset 事件——半截正文会被新回复拼接（重放）：{seen}"
        )

    def test_no_partial_retry_without_reset_event(self):
        """无可见输出（溢出发生在任何正文之前）→ 直接重试，无需 reset。"""
        pipeline = make_pipeline()
        ctx = ChatContext(user_input="q", stream=True,
                          metadata={"emit_status_events": True})
        seen = []
        ctx.event_emitter = lambda t, d: seen.append((t, d))

        calls = []

        async def fake_call(ctx_, tools_):
            calls.append(1)
            if len(calls) == 1:
                raise TokenLimitExceeded("context_length_exceeded: 上下文溢出")
            return "完整回复"

        pipeline._call_agent_loop = fake_call
        pipeline._compactTurnContext = AsyncMock(return_value=True)
        pipeline._recordCompactionFailure = MagicMock()

        reply = run(pipeline._callAgentLoopWithOverflowGuard(ctx, None))

        assert len(calls) == 2 and reply == "完整回复"
        assert all(t != "retry" for t, _ in seen), "无半截产出时不应发 reset"

    def test_non_stream_retry_keeps_silent_recovery(self):
        """非流式：产出从未出管线，重试不构成重放——保持既有静默恢复。"""
        pipeline = make_pipeline()
        ctx = ChatContext(user_input="q", stream=False, metadata={})
        seen = []
        ctx.event_emitter = lambda t, d: seen.append((t, d))
        calls = overflowOnceThen(pipeline, ctx, markPartial=False)
        pipeline._compactTurnContext = AsyncMock(return_value=True)
        pipeline._recordCompactionFailure = MagicMock()

        reply = run(pipeline._callAgentLoopWithOverflowGuard(ctx, None))

        assert len(calls) == 2 and reply == "重试后的完整回复"
        assert all(t != "retry" for t, _ in seen), "非流式不构成重放，无需 reset 信号"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
