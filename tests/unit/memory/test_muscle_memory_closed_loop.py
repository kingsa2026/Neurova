"""肌肉记忆闭环修复测试（TDD 红绿）—— docs/tool-memory-muscle-analysis.md P-B/P-C/P-A/P-D/P-E/P-F

四个闭环断裂点：
- P-B: _record_tool_failure_lesson 双重字段错误（muscle.items 不存在 +
  consecutive_success 拼写）→ 失败降级静默失效
- P-C: check_tool_memory 命中即记 success=True → 回声室（成功率虚高）
- P-A/P-F: check_forgotten 与 _cleanup_deprecated_tools 无调用方 → 记忆只升不降、
  下线工具条目残留（借 record_tool_usage 计数触发维护）
- P-D: _auto_execute_tool 的 0.7 硬门与 RSI 动态阈值重叠（调参死区）
- P-E: execute_from_memory 同步版用不存在的 result 字段冒充执行（死代码删除）
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.cognitive_layers.memory_layer.muscle_memory import (
    MemoryLevel,
    MuscleMemory,
    MuscleMemoryItem,
)
from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
    ToolMemoryIntegration,
)


@pytest.fixture
def muscle(tmp_path):
    return MuscleMemory(agent_id="test-agent", storage_dir=str(tmp_path / "mm"))


def _seed_l1_item(muscle: MuscleMemory, tool_name="get_datetime", fingerprint="当前,时间", successes=3):
    """直接造一个 L1 条目（绕过自然固化路径）"""
    item = MuscleMemoryItem(
        id=muscle._generate_item_id(tool_name, "当前时间"),
        tool_name=tool_name,
        query_fingerprint=fingerprint,
        parameters={"timezone": "+08:00"},
        result_summary="ok",
        level=MemoryLevel.L1,
        success_count=successes,
        consecutive_successes=successes,
        last_used=time.time(),
    )
    muscle._l1[item.id] = item
    muscle._add_to_keyword_index(item)
    muscle._add_to_tool_index(item)
    return item


class TestFailureDemotion:
    """P-B：工具失败必须把对应肌肉记忆的 consecutive_successes 清零"""

    def test_failure_lesson_resets_consecutive_successes(self, tmp_path):
        """_record_tool_failure_lesson 遍历三级存储并清零（原实现 muscle.items 不存在）"""
        from neurova.agent_core import Agent

        muscle = MuscleMemory(agent_id="test-agent", storage_dir=str(tmp_path / "mm"))
        item = _seed_l1_item(muscle, successes=3)
        assert item.consecutive_successes == 3

        agent = Agent.__new__(Agent)  # 跳过重型 __init__，仅挂依赖
        agent.tool_memory = ToolMemoryIntegration(muscle_memory=muscle)
        agent.growth_log_manager = None

        asyncio.run(agent._record_tool_failure_lesson("get_datetime", "现在几点", "超时"))

        assert item.consecutive_successes == 0, "失败后连续成功数未清零"


class TestHitNotCountedAsSuccess:
    """P-C：肌肉记忆命中本身不得计入成功（回声室）"""

    @pytest.mark.asyncio
    async def test_match_hit_does_not_inflate_success_count(self, muscle):
        integration = ToolMemoryIntegration(muscle_memory=muscle)
        _seed_l1_item(muscle, successes=2)
        before = list(muscle._l1.values())[0].success_count

        # 命中路径（指纹可匹配的输入；check_tool_memory 为同步 API）
        result, decision = integration.check_tool_memory("当前 时间")
        assert result is not None, "前置：应命中肌肉记忆"

        after = list(muscle._l1.values())[0].success_count
        assert after == before, f"命中即记成功（回声室）: {before} -> {after}"


class TestMaintenanceTrigger:
    """P-A/P-F：遗忘与生命周期清理接入 record_tool_usage 计数触发"""

    @pytest.mark.asyncio
    async def test_maintenance_runs_after_interval(self, muscle):
        integration = ToolMemoryIntegration(muscle_memory=muscle)
        integration.maintenance_interval = 3  # 缩短间隔便于测试

        calls = {"count": 0}

        def _spy():
            calls["count"] += 1

        with patch.object(integration, "_run_maintenance", side_effect=_spy):
            for i in range(3):
                integration.record_tool_usage(tool_name=f"tool_{i}", success=True)
            assert calls["count"] == 1, "达到间隔后应触发一次维护"
            # 再来 3 次 → 再触发
            for i in range(3):
                integration.record_tool_usage(tool_name=f"tool_b{i}", success=True)
            assert calls["count"] == 2

    def test_maintenance_forgets_stale_items(self, muscle):
        """维护触发后：过期 L1 条目被降级（遗忘闭环生效）"""
        item = _seed_l1_item(muscle)
        item.last_used = time.time() - 31 * 86400  # 超过 L1 阈值 30 天

        assert muscle.check_forgotten() == 1
        assert item.id not in muscle._l1
        assert item.id in muscle._l2  # 降级而非删除


class TestThresholdGate:
    """P-D：auto_execute 不再有第二道 0.7 硬门（RSI 动态阈值单源）"""

    @pytest.mark.asyncio
    async def test_no_second_hard_gate(self, tmp_path):
        pipeline = _make_pipeline_with_tool_memory(tmp_path)

        ctx = _ctx_with_memory_result(confidence=0.65, decision="auto_execute")
        await pipeline._auto_execute_tool(ctx)

        # 执行成功后 decision 被置为过去式 auto_executed（chat_pipeline 成功标记）；
        # 若 0.7 硬门仍在，confidence 0.65 会被降级为 suggest
        assert ctx.tool_decision == "auto_executed", "0.7 硬门把 RSI 决策推翻（调参死区）"

    @pytest.mark.asyncio
    async def test_execution_still_runs_via_manager(self, tmp_path):
        pipeline = _make_pipeline_with_tool_memory(tmp_path)
        ctx = _ctx_with_memory_result(confidence=0.65, decision="auto_execute")
        await pipeline._auto_execute_tool(ctx)
        # ToolExecutionManager 被真实调用（而非被硬门短路）
        pipeline.tool_execution_manager.execute.assert_awaited_once()


class TestDeadMethodRemoval:
    """P-E：execute_from_memory 同步版（用不存在的 result 字段冒充执行）删除"""

    def test_execute_from_memory_removed(self):
        from neurova.tool_executor import ToolExecutor

        assert not hasattr(ToolExecutor, "execute_from_memory"), (
            "危险死方法仍在：用缓存冒充工具执行"
        )


# ═══════════════════ 测试辅助 ═══════════════════


def _ctx_with_memory_result(confidence: float, decision: str):
    from neurova.agent.chat_pipeline import ChatContext

    ctx = ChatContext(user_input="现在几点了", tool_decision=decision)
    ctx.tool_memory_result = {
        "tool_name": "get_datetime",
        "tool_params": {},
        "confidence": confidence,
        "match_level": "l1",
    }
    return ctx


def _make_pipeline_with_tool_memory(tmp_path):
    from neurova.agent.chat_pipeline import ChatPipeline
    from neurova.agent.tool_execution_manager import ExecutionStatus

    agent = MagicMock()
    agent.tool_memory = ToolMemoryIntegration(
        muscle_memory=MuscleMemory(agent_id="t", storage_dir=str(tmp_path / "mm"))
    )
    # tool_memory 是只读 property（代理 agent.tool_memory），经 mock agent 注入
    pipeline = ChatPipeline(agent)

    # tool_execution_manager 返回 ChatPipeline 自建的 _tool_execution_manager，
    # 测试直接替换该私有属性为 mock
    manager = MagicMock()
    manager.execute = AsyncMock(
        return_value=SimpleNamespace(
            status=ExecutionStatus.COMPLETED,
            result={"status": "success", "result": {"time": "now"}},
        )
    )
    pipeline._tool_execution_manager = manager
    return pipeline
