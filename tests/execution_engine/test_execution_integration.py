# -*- coding: utf-8 -*-
"""
Integration tests for Execution Engine modules（对齐现行 API）

历史说明：原版按臆想契约编写——await 同步 create_plan、WorkflowEngine(tool_engine=)
构造、reset_mcp_manager 引用已删除模块、plan.plan_id/plan.context 字段——
统一修复为现行真实契约：
- create_plan(name, description, steps, priority, metadata) 为同步 API
- WorkflowEngine(config) + register_action + execute(workflow_id)
- 共享状态经 execute_plan(plan_id, context) 流入步骤执行器
"""

import asyncio

import pytest

from neurova.execution_engine.plan_orchestrator import (
    PlanStatus,
    StepStatus,
    get_plan_orchestrator,
    reset_plan_orchestrator,
)
from neurova.execution_engine.tool_engine import ToolEngine
from neurova.execution_engine.workflow_engine import (
    NodeType,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowNode,
)


class TestPlanOrchestratorCognitionIntegration:
    """PlanOrchestrator 认知上下文集成"""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Reset singleton before and after each test."""
        reset_plan_orchestrator()
        yield
        reset_plan_orchestrator()

    def test_create_plan_for_cognition(self):
        """认知上下文经 metadata 携带，步骤显式传入（旧契约 task=/context=/自动生步 已废弃）"""
        plan_orch = get_plan_orchestrator()

        cognition_context = {
            "user_input": "开发一个用户登录功能",
            "attention_level": "high",
            "memory_context": {"previous_tasks": ["task1", "task2"]},
        }

        plan = plan_orch.create_plan(
            name=cognition_context["user_input"],
            metadata=cognition_context,
            steps=[
                {"name": "解析需求", "step_type": "task"},
                {"name": "生成方案", "step_type": "task"},
            ],
        )

        assert plan.name == cognition_context["user_input"]
        assert plan.metadata == cognition_context
        assert [s.name for s in plan.steps] == ["解析需求", "生成方案"]

    def test_plan_includes_cognitive_state(self):
        """create_plan 为同步 API（旧版 await 同步返回值必崩）"""
        plan_orch = get_plan_orchestrator()

        context = {
            "cognitive_state": {
                "attention": "high",
                "memory_load": 0.8,
            }
        }

        plan = plan_orch.create_plan("Test task", metadata=context)

        assert plan.metadata["cognitive_state"]["attention"] == "high"


class TestToolEngineWorkflowIntegration:
    """ToolEngine 与 WorkflowEngine 协作"""

    @pytest.mark.asyncio
    async def test_workflow_uses_tool_engine(self):
        """工作流动作处理器委托 ToolEngine 执行已注册工具（旧契约 WorkflowEngine(tool_engine=) 已废弃）"""
        tool_engine = ToolEngine()

        async def test_tool():
            return {"result": "success"}

        tool_engine.register_tool("test_tool", test_tool)

        workflow_engine = WorkflowEngine()

        async def execute_tool_handler(tool_name=None, parameters=None, **_):
            return await tool_engine.execute(tool_name, parameters or {})

        workflow_engine.register_action("execute_tool", execute_tool_handler)

        definition = WorkflowDefinition(
            name="Test Workflow",
            nodes={
                "step1": WorkflowNode(
                    node_id="step1",
                    name="Tool Step",
                    node_type=NodeType.TASK,
                    action="execute_tool",
                    parameters={"tool_name": "test_tool"},
                )
            },
            start_node="step1",
        )
        workflow_engine.register_workflow(definition)

        result = await workflow_engine.execute(definition.workflow_id)

        assert result == {"result": "success"}


class TestCompleteExecutionFlow:
    """Plan → ToolEngine 完整执行流（mcp_manager 已随 MCP 重构删除，fixture 不再引用）"""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Reset singleton before and after each test."""
        reset_plan_orchestrator()
        yield
        reset_plan_orchestrator()

    @pytest.mark.asyncio
    async def test_full_execution_pipeline(self):
        """计划步骤经 step_type 执行器委托 ToolEngine，结果落回 step.result"""
        plan_orch = get_plan_orchestrator()

        tool_engine = ToolEngine()

        async def test_tool():
            return {"status": "step_completed"}

        tool_engine.register_tool("test_tool", test_tool)

        async def tool_executor(step, context, parameters):
            return await tool_engine.execute(parameters["tool_name"], {})

        plan_orch.register_step_executor("tool", tool_executor)

        plan = plan_orch.create_plan(
            "Complete test task",
            steps=[{"name": "调用工具", "step_type": "tool", "parameters": {"tool_name": "test_tool"}}],
        )
        assert len(plan.steps) == 1

        result = await plan_orch.execute_plan(plan.id)

        assert result.status == PlanStatus.COMPLETED
        assert result.steps[0].result == {"status": "step_completed"}

    @pytest.mark.asyncio
    async def test_error_handling_across_modules(self):
        """步骤失败向上汇总：plan FAILED + step.error 保留（旧断言 dict step_results 已废弃）"""
        plan_orch = get_plan_orchestrator()

        async def boom_executor(step, context, parameters):
            raise RuntimeError("Test error")

        plan_orch.register_step_executor("boom", boom_executor)

        plan = plan_orch.create_plan(
            "Error test task",
            steps=[{"name": "bad", "step_type": "boom", "max_retries": 0}],
        )

        result = await plan_orch.execute_plan(plan.id)

        assert result.status == PlanStatus.FAILED
        assert result.steps[0].status == StepStatus.FAILED
        assert "Test error" in result.steps[0].error


class TestExecutionEngineIntegration:
    """ExecutionEngine 组件协作"""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        reset_plan_orchestrator()
        yield
        reset_plan_orchestrator()

    @pytest.mark.asyncio
    async def test_components_share_state(self):
        """共享状态经 execute_plan(context) 流入步骤执行器（旧断言 plan.context 字段已不存在）"""
        plan_orch = get_plan_orchestrator()

        received = {}

        async def capture_executor(step, context, parameters):
            received.update(context)
            return "ok"

        plan_orch.register_step_executor("task", capture_executor)

        plan = plan_orch.create_plan(
            "Shared state test",
            steps=[{"name": "s1", "step_type": "task"}],
        )

        await plan_orch.execute_plan(plan.id, {"shared_state": {"key": "value"}})

        assert received["shared_state"]["key"] == "value"
        assert plan.steps[0].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_concurrent_execution(self):
        """多计划并发执行：gather 协程而非同步返回值（旧代码 gather 同步结果必崩）"""
        plan_orch = get_plan_orchestrator()

        async def ok_executor(step, context, parameters):
            return "done"

        plan_orch.register_step_executor("task", ok_executor)

        plans = [
            plan_orch.create_plan(f"Concurrent task {i}", steps=[{"name": "s", "step_type": "task"}])
            for i in range(3)
        ]
        assert len({p.id for p in plans}) == 3  # All unique IDs

        results = await asyncio.gather(*(plan_orch.execute_plan(p.id) for p in plans))

        assert all(r.status == PlanStatus.COMPLETED for r in results)
        assert all(r.steps[0].result == "done" for r in results)
