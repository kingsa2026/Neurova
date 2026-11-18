"""M1 记账单源红灯：一次自动执行，同一指纹的肌肉记忆连击恰 +1。

生产链路上同一指纹此前被记两次：
  1. ToolExecutor._execute_single_tool_inner 的 finally → on_tool_executed
     → tool_memory.record_tool_usage → muscle_memory.record_usage；
  2. ChatPipeline._record_tool_outcome → _record_muscle_memory_outcome
     → muscle_memory.record_usage（重复的第二笔）。
后果：_PROMOTE_THRESHOLD=2 下，L3 新条目一次成功即升 L2，固化判据被稀释。

本测试走真实自动执行链路（真实 ToolExecutionManager + ToolExecutor 钩子 +
真实 ToolMemoryIntegration + 真实 MuscleMemory 落盘临时目录），钉住：
- 一次自动执行后 consecutive_successes 恰 +1（条目留在 L3）；
- L3 新条目需要两次独立成功才升 L2。
"""

import pytest
from unittest.mock import MagicMock

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.cognitive_layers.memory_layer.muscle_memory import MuscleMemory
from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
    ToolMemoryIntegration,
)
from neurova.tool_executor import ToolExecutor

QUERY = "帮我读取 /tmp/config.json 文件"
TOOL = "file_read"
PARAMS = {"file_path": "/tmp/config.json"}


def _make_stack(tmp_path):
    """真实肌肉记忆 + 集成层 + 真实 ToolExecutor + 真实 ChatPipeline。"""
    muscle = MuscleMemory(storage_dir=str(tmp_path / "muscle"))
    tmi = ToolMemoryIntegration(muscle_memory=muscle, muscle_memory_threshold=0.5)

    agent = MagicMock()
    agent.tool_memory = tmi
    agent.config = MagicMock()
    agent.config.agent_id = "m1-test"
    agent.config.user_id = "u1"
    # on_tool_executed 的 user_input 取 agent._current_user_input（咽喉口径）
    agent._current_user_input = QUERY
    agent.tool_lifecycle = None
    agent.evolution = None

    executor = ToolExecutor(agent)

    async def _no_governance(tool_name, params):
        return None

    async def _fake_core(tool_name, params):
        # 成败判据单源：result["success"]
        return ({"success": True, "output": "ok"}, True, "skill_system")

    executor._governance_precheck = _no_governance
    executor._execute_tool_core = _fake_core
    agent.tool_executor = executor

    pipeline = ChatPipeline(agent)
    return muscle, tmi, executor, pipeline


async def _auto_execute_once(pipeline):
    ctx = ChatContext(user_input=QUERY)
    ctx.tool_memory_result = {
        "tool_name": TOOL,
        "tool_params": PARAMS,
        "confidence": 0.9,
    }
    ctx.tool_decision = "auto_execute"
    await pipeline._auto_execute_tool(ctx)
    return ctx


class TestAutoExecuteBooksOnce:
    @pytest.mark.asyncio
    async def test_one_auto_execution_counts_once(self, tmp_path):
        """同一次自动执行后，肌肉记忆连击恰 +1（不出现 +2）。"""
        muscle, tmi, executor, pipeline = _make_stack(tmp_path)

        ctx = await _auto_execute_once(pipeline)

        assert ctx.tool_decision == "auto_executed", (
            f"自动执行应成功，实际决策: {ctx.tool_decision}"
        )
        stats = muscle.get_stats()
        assert stats["total"] == 1, f"一次自动执行只应有一个条目，实际: {stats}"
        assert stats["l3_count"] == 1, (
            f"一次成功连击=1，条目应留在 L3，实际: {stats}"
        )
        assert stats["l2_count"] == 0, (
            f"一次成功不得固化到 L2（固化阈值 2），实际: {stats}"
        )
        assert tmi.get_tool_stats(TOOL).get("total", 0) == 1, (
            "集成层使用统计同一次执行只记一笔"
        )

    @pytest.mark.asyncio
    async def test_l3_entry_needs_two_successes_to_promote(self, tmp_path):
        """L3 新条目需两次独立成功才升 L2。"""
        muscle, tmi, executor, pipeline = _make_stack(tmp_path)

        await _auto_execute_once(pipeline)
        stats = muscle.get_stats()
        assert stats["l2_count"] == 0, (
            f"第一次成功后连击=1，不得升 L2，实际: {stats}"
        )

        await _auto_execute_once(pipeline)
        stats = muscle.get_stats()
        assert stats["total"] == 1, (
            f"两次自动执行同一指纹仍应只有一个条目，实际: {stats}"
        )
        assert stats["l2_count"] == 1, (
            f"两次独立成功后应固化到 L2，实际: {stats}"
        )
        assert stats["l3_count"] == 0, f"固化后 L3 应清空，实际: {stats}"
