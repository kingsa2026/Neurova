"""
P2 剩余清单：chat_pipeline 伪造 total_tokens 切换到真实 usage 对账

- TokenUsageAccounting.last_call()：最近一次调用的真实 usage（新增 API）
- chat_pipeline._step_post_processing：trace total_tokens 优先取
  usage_accounting.last_call()，无真实值时回退字符估算（向后兼容）
"""

import pytest
from unittest.mock import MagicMock

from neurova.core.usage_accounting import (
    TokenUsageAccounting,
    get_usage_accounting,
    reset_usage_accounting,
)


class TestLastCall:
    def test_last_call_returns_latest(self):
        reset_usage_accounting()
        acc = get_usage_accounting()
        acc.record(model="m1", provider="p", prompt_tokens=100, completion_tokens=30)
        acc.record(model="m2", provider="p", prompt_tokens=200, completion_tokens=50)
        last = acc.last_call()
        assert last["model"] == "m2"
        assert last["prompt_tokens"] == 200
        assert last["completion_tokens"] == 50

    def test_last_call_empty_none(self):
        reset_usage_accounting()
        acc = get_usage_accounting()
        assert acc.last_call() is None


class TestPipelineSwitch:
    """_step_post_processing 的 total_tokens 切换：真实 usage 优先，字符估算回退"""

    def _make_pipeline(self, tmp_path):
        """最小 ChatPipeline + 完整 agent 桩（全部只读 property 走 agent 层）"""
        from unittest.mock import AsyncMock, MagicMock

        from neurova.agent.chat_pipeline import ChatPipeline

        captured = {}

        class _FakeTrace:
            def finish_trace(self, trace_id, reply, total_tokens=0):
                captured["total_tokens"] = total_tokens

        agent = MagicMock()
        agent._current_user_id = "u1"
        agent.trace_manager = _FakeTrace()
        agent.memory_agent = MagicMock()
        agent._trajectory_recorder = None
        agent.pipeline_executor = None
        agent.post_chat_pipeline = MagicMock()
        agent.post_chat_pipeline.process = AsyncMock(return_value={"actual_session_id": "s"})

        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = agent
        return pipeline, captured

    @pytest.mark.asyncio
    async def test_trace_uses_real_tokens_when_available(self, tmp_path):
        from neurova.core.usage_accounting import get_usage_accounting, reset_usage_accounting

        reset_usage_accounting()
        acc = get_usage_accounting()
        acc.record(model="test-model", provider="p", prompt_tokens=100, completion_tokens=30)

        pipeline, captured = self._make_pipeline(tmp_path)
        ctx = MagicMock()
        ctx.trace_id = "tr1"
        ctx.user_input = "hello world"  # 11 字符 → 伪造值会是 11
        ctx.reply = "reply text"

        await pipeline._step_post_processing(ctx)
        assert captured["total_tokens"] == 130  # 真实 usage 而非 11

    @pytest.mark.asyncio
    async def test_trace_falls_back_to_char_estimate(self, tmp_path):
        """无真实 usage：回退字符长度估算（11 + 10 = 21）"""
        from neurova.core.usage_accounting import reset_usage_accounting

        reset_usage_accounting()
        pipeline, captured = self._make_pipeline(tmp_path)
        ctx = MagicMock()
        ctx.trace_id = "tr1"
        ctx.user_input = "hello world"
        ctx.reply = "reply text"

        await pipeline._step_post_processing(ctx)
        assert captured["total_tokens"] == 21


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
