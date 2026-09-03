"""condition 真分支执行测试（分支跳过 + 汇聚点保护）"""

import pytest

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

DOLLAR = "$"


def N(id, type="builtin:transform", config=None):
    return WorkflowNode(id=id, type=type, position={"x": 0, "y": 0}, config=config or {})


def E(id, source, target, source_handle=None):
    return WorkflowEdge(id=id, source=source, target=target, source_handle=source_handle)


def branch_workflow(expression, with_join=False):
    """start → cond -true→ a -→ end ; cond -false→ b → end（with_join 时 b 直连 join）"""
    nodes = [
        N("start", "builtin:start"),
        N("cond", "builtin:condition", {"expression": expression}),
        N("a", "builtin:transform", {"expression": "branch_a"}),
        N("end", "builtin:end"),
    ]
    edges = [E("e1", "start", "cond"), E("e2", "cond", "a", source_handle="true"), E("e3", "cond", "end", source_handle="false")]
    if with_join:
        # cond -false→ join → end；a → join
        nodes.append(N("join", "builtin:transform", {"expression": "joined"}))
        edges = [
            E("e1", "start", "cond"),
            E("e2", "cond", "a", source_handle="true"),
            E("e3", "cond", "join", source_handle="false"),
            E("e4", "a", "join"),
            E("e5", "join", "end"),
        ]
    return WorkflowDefinition(
        id="wf_cond_test",
        name="condition 测试",
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


class TestConditionBranching:
    @pytest.mark.asyncio
    async def test_true_branch_executes_true_side(self):
        executor = WorkflowExecutor()
        run = executor.execute
        events = []
        executor.on_event(events.append)

        instance = await run(branch_workflow("True"), inputs={})

        assert instance.status == WorkflowStatus.COMPLETED
        assert "a" in instance.node_results and instance.node_results["a"].status == "success"
        # false 侧无独立节点（false 直连 end），此处验证 true 侧执行即可

    @pytest.mark.asyncio
    async def test_false_branch_skips_true_side(self):
        executor = WorkflowExecutor()
        run = executor.execute
        events = []
        executor.on_event(events.append)

        instance = await run(branch_workflow("False"), inputs={})

        assert instance.status == WorkflowStatus.COMPLETED
        # true 侧节点 a 被跳过
        assert instance.node_results["a"].status == "skipped"
        skipped_events = [e for e in events if e.type == ExecutionEventType.NODE_SKIPPED and e.node_id == "a"]
        assert len(skipped_events) == 1

    @pytest.mark.asyncio
    async def test_expression_with_input_context(self):
        executor = WorkflowExecutor()
        run = executor.execute
        workflow_def = branch_workflow(DOLLAR + "input.count > 2")

        instance = await run(workflow_def, inputs={"count": 5})

        assert instance.node_results["a"].status == "success"

    @pytest.mark.asyncio
    async def test_expression_false_with_input_context(self):
        executor = WorkflowExecutor()
        run = executor.execute
        workflow_def = branch_workflow(DOLLAR + "input.count > 2")

        instance = await run(workflow_def, inputs={"count": 1})

        assert instance.node_results["a"].status == "skipped"

    @pytest.mark.asyncio
    async def test_convergence_point_not_skipped(self):
        """汇聚点（两条分支的汇合处）不被误跳过"""
        executor = WorkflowExecutor()
        run = executor.execute
        events = []
        executor.on_event(events.append)

        instance = await run(branch_workflow("False", with_join=True), inputs={})

        assert instance.status == WorkflowStatus.COMPLETED
        # a 被跳过，但 join 有活跃前驱（cond -false→ join），必须执行
        assert instance.node_results["a"].status == "skipped"
        assert instance.node_results["join"].status == "success"
