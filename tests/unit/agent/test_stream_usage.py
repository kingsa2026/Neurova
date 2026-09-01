"""
P2-4d 流式路径 usage 聚合红测

- openai_loop._predict_stream_once：流式 chunk 的 usage 聚合进 done 事件
  （多轮工具调用时逐轮 done 均携带本轮 usage）
- chat_pipeline._call_loop_stream：done 事件的 usage 入账
  （usage_accounting.record），非流式无 usage 时不入账
"""

import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from neurova.core.usage_accounting import (
    get_usage_accounting,
    reset_usage_accounting,
)


def _llm_response(content="", usage=None, finish_reason=None, tool_calls=None):
    return SimpleNamespace(
        content=content,
        usage=usage,
        finish_reason=finish_reason,
        tool_calls=tool_calls,
        reasoning_content=None,
    )


def _make_loop(script):
    """最小 OpenAILoop：chat_stream 按脚本出牌"""
    from neurova.agent.loops.openai_loop import OpenAILoop

    agent = SimpleNamespace(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(name="t", user_id="u1", agent_id="a1"),
        _current_user_id="u1",
        _tool_messages_list=[],
        skill_registry=None,
        tool_router=None,
    )
    loop = OpenAILoop(agent)

    async def chat_stream(messages, **kwargs):
        for piece in script:
            yield piece

    loop.llm_client.chat_stream = chat_stream
    return loop, agent


class TestStreamUsageAggregation:
    @pytest.mark.asyncio
    async def test_done_event_carries_usage(self):
        """流式最后一 chunk 的 usage 聚合进 done 事件"""
        loop, agent = _make_loop([
            _llm_response(content="hel", usage=None),
            _llm_response(
                content="lo",
                usage=SimpleNamespace(prompt_tokens=100, completion_tokens=30, total_tokens=130),
                finish_reason="stop",
            ),
        ])
        events = [e async for e in loop._predict_stream_once({"messages": [{"role": "user", "content": "hi"}]})]
        done = next(e for e in events if e.get("type") == "done")
        assert done.get("usage") == {
            "prompt_tokens": 100,
            "completion_tokens": 30,
            "total_tokens": 130,
        }

    @pytest.mark.asyncio
    async def test_no_usage_chunk_done_has_none(self):
        loop, _agent = _make_loop([_llm_response(content="hi", finish_reason="stop")])
        events = [e async for e in loop._predict_stream_once({"messages": [{"role": "user", "content": "hi"}]})]
        done = next(e for e in events if e.get("type") == "done")
        assert done.get("usage") is None


class TestPipelineRecords:
    @pytest.mark.asyncio
    async def test_pipeline_does_not_double_record(self):
        """入账已下沉到 MultiModelLLMClient.chat_stream（根因修复 2026-09-02）。

        原实现由 chat_pipeline 消费 done.usage 入账，但 model/provider 为
        config 值 + "stream"，且与调用层计数不一致；且 done 携带 usage 依赖
        流式回传（从未请求 include_usage，恒 None）。
        新契约：调用层单点 record（calls 每次调用 +1、usage 末 chunk 全量），
        pipeline 只透传 done 事件，绝不重复入账——防双计（1 次调用记 2 次）。
        """
        from neurova.agent.chat_pipeline import ChatPipeline

        reset_usage_accounting()
        loop, agent = _make_loop([
            _llm_response(
                content="ok",
                usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20, total_tokens=70),
                finish_reason="stop",
            ),
        ])

        pipeline = ChatPipeline.__new__(ChatPipeline)
        agent.loop = MagicMock()
        agent.loop.predict_step = AsyncMock(return_value=loop._predict_stream_once({"messages": []}))
        pipeline._agent = agent
        pipeline._agent._current_user_id = "u1"

        ctx = MagicMock()
        ctx.stream = True
        ctx.trace_id = None
        ctx.context = [{"role": "user", "content": "hi"}]
        ctx.tools = None
        ctx.event_emitter = None

        await pipeline._call_loop_stream(ctx, None)

        snap = get_usage_accounting().snapshot()
        # done.usage 可在事件流中使用，但 pipeline 层不得入账（防双计）
        assert snap["total"]["calls"] == 0
        assert snap["total"]["prompt_tokens"] == 0
        assert snap["total"]["completion_tokens"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
