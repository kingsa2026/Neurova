# -*- coding: utf-8 -*-
"""ToolExecutionManager 集成到 ChatPipeline（对齐现行契约）"""
import asyncio
from unittest.mock import Mock

import pytest

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.tool_execution_manager import ToolExecutionManager


# 模拟 Agent 类
class MockAgent:
    def __init__(self):
        self.config = Mock()
        self.memory_agent = Mock()
        self.context_orchestrator = Mock()
        self.tool_memory = Mock()
        self.skill_manager = Mock()
        self.tool_synthesizer = Mock()
        self.unified_retriever = Mock()
        self.crystallizer = Mock()
        self.trace_manager = Mock()
        self.neuHebb_manager = Mock()
        self.loop = Mock()
        self.llm_client = Mock()
        self.tool_executor = Mock()
        self.post_chat_pipeline = Mock()
        self.idle_tracker = Mock()


# 模拟工具执行器
class MockToolExecutor:
    async def execute_tool(self, tool_name, params, user_input):
        """模拟执行工具"""
        await asyncio.sleep(0.1)  # 模拟执行时间
        return {
            "status": "success",
            "result": f"Executed {tool_name} successfully",
            "tool_name": tool_name,
        }

    async def execute_from_memory_async(self, memory_result, user_input):
        """模拟从内存执行工具"""
        tool_name = memory_result.get('tool_name')
        params = memory_result.get('params', {})
        return await self.execute_tool(tool_name, params, user_input)


@pytest.mark.asyncio
async def test_tool_execution_manager_integration():
    """测试 ToolExecutionManager 集成"""
    # 创建模拟 Agent
    mock_agent = MockAgent()
    mock_agent.tool_executor = MockToolExecutor()

    # 创建 ChatPipeline
    pipeline = ChatPipeline(mock_agent)

    # 验证 ToolExecutionManager 已初始化
    assert hasattr(pipeline, '_tool_execution_manager')
    assert isinstance(pipeline._tool_execution_manager, ToolExecutionManager)
    assert pipeline.tool_execution_manager is pipeline._tool_execution_manager

    # 创建测试上下文
    ctx = ChatContext(
        user_input="测试用户输入",
        tool_memory_result={
            "tool_name": "test_tool",
            "params": {"query": "test"},
            "confidence": 0.8,
        },
    )

    # 测试工具执行
    await pipeline._auto_execute_tool(ctx)

    # 验证执行结果
    assert ctx.tool_decision == "auto_executed", f"Expected 'auto_executed', got '{ctx.tool_decision}'"
    assert ctx.auto_execute_result is not None
    assert ctx.auto_execute_result.get("status") == "success"

    # 测试低置信度场景：P-D 修复移除了 _auto_execute_tool 的 0.7 硬门，
    # 置信度阈值由 check_tool_memory 的 dynamic_threshold 单源裁定，
    # 本层只管执行（confidence 仅记录 metadata）→ 低置信度也执行。
    ctx2 = ChatContext(
        user_input="测试低置信度",
        tool_memory_result={
            "tool_name": "low_confidence_tool",
            "params": {},
            "confidence": 0.5,
        },
    )

    await pipeline._auto_execute_tool(ctx2)
    assert ctx2.tool_decision == "auto_executed", f"Expected 'auto_executed', got '{ctx2.tool_decision}'"

    # 测试超时场景
    class SlowToolExecutor:
        async def execute_tool(self, tool_name, params, user_input):
            await asyncio.sleep(10.0)  # 模拟慢速执行
            return {"status": "success"}

        async def execute_from_memory_async(self, memory_result, user_input):
            tool_name = memory_result.get('tool_name')
            params = memory_result.get('params', {})
            return await self.execute_tool(tool_name, params, user_input)

    mock_agent.tool_executor = SlowToolExecutor()

    ctx3 = ChatContext(
        user_input="测试超时",
        tool_memory_result={
            "tool_name": "slow_tool",
            "params": {},
            "confidence": 0.9,
        },
    )

    # 使用较短的超时时间进行测试
    pipeline._tool_execution_manager._contexts.clear()  # 清理之前的上下文

    # 修改 execute 方法使用更短的超时时间
    original_execute = pipeline._tool_execution_manager.execute

    async def short_timeout_execute(*args, **kwargs):
        kwargs['timeout'] = 0.1  # 100ms 超时
        return await original_execute(*args, **kwargs)

    pipeline._tool_execution_manager.execute = short_timeout_execute

    await pipeline._auto_execute_tool(ctx3)
    assert ctx3.tool_decision == "timeout", f"Expected 'timeout', got '{ctx3.tool_decision}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class _ShapeJudgingExecutor:
    """最小可用的工具执行器替身。

    只实现 `execute_tool`——**不**实现 `_result_is_success`。
    生产装配下肌肉记忆要保存的正是"这次执行用什么判据判成败"，
    该判据由执行器自己给出；替身不给出时，生产者无从判断，
    原实现里 `{"status": "success"}` 的替身数据会把这一步盖住。
    """

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def execute_tool(self, tool_name, params, user_input):
        self.calls += 1
        return self.payload


class _ShapeJudgingExecutorWithVerdict(_ShapeJudgingExecutor):
    """同上，但显式给出判据（与生产 `ToolExecutor._result_is_success` 同形）。"""

    @staticmethod
    def _result_is_success(result):
        return not (isinstance(result, dict) and result.get("error"))


async def _run_auto_execute(payload, executor_cls=_ShapeJudgingExecutor):
    executor = executor_cls(payload)
    agent = MockAgent()
    agent.tool_executor = executor
    pipeline = ChatPipeline(agent)

    recorded = []

    class _Muscle:
        def record_usage(self, tool_name, query, parameters, success, **kwargs):
            recorded.append({"tool_name": tool_name, "success": success})
            return Mock()

    class _ToolMemory:
        muscle_memory = _Muscle()

    # 生产装配点：agent.tool_memory 就是肌肉记忆的持有者
    # （`ChatPipeline.tool_memory` 走 `getattr(self._agent, "tool_memory", None)`）。
    agent.tool_memory = _ToolMemory()
    pipeline._record_tool_failure = _AsyncRecorder(recorded)

    ctx = ChatContext(
        user_input="再来一次",
        tool_memory_result={
            "tool_name": "get_datetime",
            "tool_params": {},
            "confidence": 0.9,
        },
    )
    await pipeline._auto_execute_tool(ctx)
    return ctx, recorded


class _AsyncRecorder:
    def __init__(self, sink):
        self._sink = sink

    async def __call__(self, tool_name, user_input, error_msg):
        self._sink.append({"tool_name": tool_name, "success": False, "error": error_msg})


class TestAutoExecuteJudgesToolOutcomeAtTheExecutor:
    """自动执行臂必须按**执行器给出的判据**判成败，并把成败回流给肌肉记忆。

    现场（构建 cnb-1h8-1k341hkm9，Issue #99 工具↔经验↔再调用环路）：
    自动执行臂把 `{"error": …}` 的原生工具结果当成成功，且 `_record_tool_failure`
    从不是生产调用的——失败教训不落账、肌肉记忆的连续成功数不清零。
    """

    @pytest.mark.asyncio
    async def test_error_payload_is_reported_as_failed(self):
        """`{"error": …}` 必须被**判成失败**，而不是"没成功但也没说失败"。"""
        ctx, recorded = await _run_auto_execute({"error": "boom"})
        assert ctx.tool_decision == "failed", (
            f"`{{'error': …}}` 的裁定不是失败（现场形态是静默当成成功）：{ctx.auto_execute_result}"
        )
        assert ctx.auto_execute_result.get("success") is False
        assert recorded and recorded[0]["success"] is False, (
            f"失败结果没有回流到肌肉记忆（成败信号断链）：{recorded}"
        )

    @pytest.mark.asyncio
    async def test_success_payload_flows_back_to_muscle_memory(self):
        ctx, recorded = await _run_auto_execute(
            {"result": 42}, executor_cls=_ShapeJudgingExecutorWithVerdict
        )
        assert ctx.tool_decision == "auto_executed", ctx.auto_execute_result
        assert recorded and recorded[0]["success"] is True, (
            f"成功结果没有回流到肌肉记忆：{recorded}"
        )

    @pytest.mark.asyncio
    async def test_executor_without_verdict_is_a_named_failure(self):
        """判据缺席时不得默认成功——那正是本次事故的形态（无判据 ⇒ 静默绿）。"""
        ctx, recorded = await _run_auto_execute({"anything": 1})
        assert ctx.tool_decision == "failed", (
            f"执行器未给出成败判据时未被判失败（默认成功即本次事故形态）：{ctx.auto_execute_result}"
        )
        assert ctx.auto_execute_result and "判据" not in str(ctx.auto_execute_result.get("error", "")), (
            "失败结论应当点名真实原因，而不是把判据缺失伪装成工具报错"
        )
        assert recorded and recorded[0]["success"] is False
