"""Loop 真循环执行测试（DAG 回边豁免 + 引擎迭代驱动）"""

import pytest

from neurova.collaboration.neurflow.dag import get_dag_validator
from neurova.collaboration.neurflow.execution_engine import (
    ExecutionEventType,
    WorkflowExecutor,
)
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)

# 条件表达式里的变量前缀（避免测试数据被误判）
DOLLAR = "$"


def make_workflow(nodes, edges, workflow_id="wf_loop_test"):
    return WorkflowDefinition(
        id=workflow_id,
        name="loop 测试",
        description="",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=[],
        tags=[],
        category="test",
        author="test",
        created_at=0,
        updated_at=0,
        status=WorkflowStatus.PUBLISHED,
    )


def N(id, type="builtin:transform", config=None):
    return WorkflowNode(id=id, type=type, position={"x": 0, "y": 0}, config=config or {})


def E(id, source, target, source_handle=None, target_handle=None):
    return WorkflowEdge(id=id, source=source, target=target, source_handle=source_handle, target_handle=target_handle)


def build_loop_workflow(max_iterations=3, break_condition="", workflow_id="wf_loop"):
    """start → loop --current--> body --loop_body(回边)--> loop --loop_done--> end"""
    nodes = [
        N("start", "builtin:start"),
        N("loop", "builtin:loop", {"max_iterations": max_iterations, "break_condition": break_condition}),
        N("body1", "builtin:transform", {"expression": "iter"}),
        N("end", "builtin:end"),
    ]
    edges = [
        E("e1", "start", "loop"),
        E("e2", "loop", "body1", source_handle="current"),
        E("e3", "body1", "loop", target_handle="loop_body"),
        E("e4", "loop", "end", source_handle="loop_done"),
    ]
    return make_workflow(nodes, edges, workflow_id)


class TestDagLoopBackedge:
    """DAG 回边豁免"""

    def test_backedge_not_treated_as_cycle(self):
        validator = get_dag_validator()
        workflow_def = build_loop_workflow()
        result = validator.validate(workflow_def.nodes, workflow_def.edges)
        assert result.is_valid, "loop 回边被误判为环: " + str(result.errors)
        assert result.has_cycle is False

    def test_normal_cycle_still_rejected(self):
        validator = get_dag_validator()
        nodes = [N("a"), N("b")]
        edges = [E("e1", "a", "b"), E("e2", "b", "a")]  # 普通环（无 loop_body 端口）
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        assert result.has_cycle is True


class TestLoopExecution:
    """引擎级循环执行"""

    @pytest.mark.asyncio
    async def test_loop_runs_body_max_iterations(self):
        executor = WorkflowExecutor()
        run = executor.execute
        events = []
        executor.on_event(events.append)
        workflow_def = build_loop_workflow(max_iterations=3)

        instance = await run(workflow_def, inputs={})

        assert instance.status == WorkflowStatus.COMPLETED
        # body1 每轮执行一次
        body_starts = [e for e in events if e.type == ExecutionEventType.NODE_STARTED and e.node_id == "body1"]
        assert len(body_starts) == 3
        # loop 结果
        loop_result = instance.node_results["loop"]
        assert loop_result.output["iterations"] == 3
        assert loop_result.output["broken"] is False
        # loop 每轮发 NODE_STARTED（带 iteration）
        loop_starts = [e for e in events if e.type == ExecutionEventType.NODE_STARTED and e.node_id == "loop"]
        assert len(loop_starts) == 3

    @pytest.mark.asyncio
    async def test_loop_break_condition(self):
        executor = WorkflowExecutor()
        run = executor.execute
        workflow_def = build_loop_workflow(max_iterations=10, break_condition=DOLLAR + "iteration >= 2")

        instance = await run(workflow_def, inputs={})

        assert instance.status == WorkflowStatus.COMPLETED
        loop_result = instance.node_results["loop"]
        assert loop_result.output["iterations"] == 2
        assert loop_result.output["broken"] is True

    @pytest.mark.asyncio
    async def test_loop_last_output_flows(self):
        executor = WorkflowExecutor()
        run = executor.execute
        workflow_def = build_loop_workflow(max_iterations=2)

        instance = await run(workflow_def, inputs={})

        # body1 是出口节点，其末次输出作为 loop 的 last_output
        loop_result = instance.node_results["loop"]
        assert loop_result.output["last_output"] == "transform: iter"
        # body1 的 node_results 保留末次迭代
        assert instance.node_results["body1"].status == "success"

    @pytest.mark.asyncio
    async def test_loop_without_body_degrades(self):
        nodes = [N("start", "builtin:start"), N("loop", "builtin:loop", {"max_iterations": 5}), N("end", "builtin:end")]
        edges = [E("e1", "start", "loop"), E("e2", "loop", "end", source_handle="loop_done")]
        executor = WorkflowExecutor()
        run = executor.execute

        instance = await run(make_workflow(nodes, edges, "wf_loop_nobody"), inputs={})

        assert instance.status == WorkflowStatus.COMPLETED
        assert instance.node_results["loop"].output["iterations"] == 0

    @pytest.mark.asyncio
    async def test_body_nodes_not_double_executed(self):
        """body 节点由 loop 驱动，主循环不得重复执行"""
        executor = WorkflowExecutor()
        run = executor.execute
        events = []
        executor.on_event(events.append)
        workflow_def = build_loop_workflow(max_iterations=2)

        await run(workflow_def, inputs={})

        body_completions = [
            e for e in events if e.type == ExecutionEventType.NODE_COMPLETED and e.node_id == "body1"
        ]
        assert len(body_completions) == 2  # 每轮一次，共 2 次（非 2+主循环 1 次）
