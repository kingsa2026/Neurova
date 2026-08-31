# -*- coding: utf-8 -*-
"""
execution_engine 基础契约测试（对齐现行 API）

历史说明：本文件原为脚本式验证（try/except 吞异常 + 返回值代替断言 +
__main__ 自跑），对已删除的 mcp_manager 模块和旧版异步 create_plan 契约
断言，在 pytest 下空转通过/静默失败。现已重写为真实断言，锁定现行契约：
- create_plan 为同步签名 (name, description, steps, priority, metadata)
- ExecutionStep/ExecutionPlan 字段为 id/name/step_type/metadata 系列
- mcp_manager 已随 MCP 层重构删除，不再属于本包契约
"""
import pytest

from neurova.execution_engine.plan_orchestrator import (
    ExecutionPlan,
    ExecutionStep,
    get_plan_orchestrator,
    reset_plan_orchestrator,
)
from neurova.execution_engine.tool_engine import ToolEngine
from neurova.execution_engine.workflow_engine import WorkflowEngine


def test_imports():
    """核心模块可导入"""
    import neurova.execution_engine.execution_monitor  # noqa: F401
    import neurova.execution_engine.plan_orchestrator  # noqa: F401
    import neurova.execution_engine.tool_engine  # noqa: F401
    import neurova.execution_engine.workflow_engine  # noqa: F401


def test_dataclasses():
    """dataclass 现行字段（旧脚本曾断言 step_id/plan_id/goal——均已不存在）"""
    step = ExecutionStep(name="Test Step", step_type="task")
    assert step.id
    assert step.status.value == "pending"

    plan = ExecutionPlan(name="Test Goal", steps=[step])
    assert plan.id
    assert plan.steps == [step]
    assert plan.status.value == "created"
    assert not plan.is_complete()  # 空步骤的 plan 不算完成


@pytest.fixture()
def plan_orch():
    reset_plan_orchestrator()
    yield get_plan_orchestrator()
    reset_plan_orchestrator()


@pytest.mark.asyncio
async def test_plan_orchestrator(plan_orch):
    """create_plan 为同步签名：name 入参、无步骤自动生成（旧契约 async + await 已废弃）"""
    plan = plan_orch.create_plan("Test task")
    assert plan.name == "Test task"
    assert plan.steps == []

    retrieved = plan_orch.get_plan(plan.id)
    assert retrieved is plan

    assert plan in plan_orch.get_all_plans()


@pytest.mark.asyncio
async def test_engine_instantiation():
    """ToolEngine/WorkflowEngine 构造仅收 config（旧契约 WorkflowEngine(tool_engine=) 已废弃）"""
    tool_engine = ToolEngine()
    assert tool_engine.list_tools() == []

    workflow_engine = WorkflowEngine()
    assert workflow_engine.list_workflows() == []
