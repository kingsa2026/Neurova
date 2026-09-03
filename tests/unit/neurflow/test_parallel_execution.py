"""分层并行执行测试（asyncio.gather 层内并发）"""

import time

import pytest

from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
    NodeDefinition,
)
from neurova.collaboration.neurflow.node_registry import get_node_registry


def N(id, type, config=None):
    return WorkflowNode(id=id, type=type, position={"x": 0, "y": 0}, config=config or {})


def E(id, source, target):
    return WorkflowEdge(id=id, source=source, target=target)


def make_workflow(nodes, edges, workflow_id="wf_par_test"):
    return WorkflowDefinition(
        id=workflow_id,
        name="parallel 测试",
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


@pytest.fixture
def slow_node_registered():
    """注册测试用慢节点（0.15s），验证层内并发"""
    registry = get_node_registry()

    async def exec_slow(config, ctx):
        await asyncio_sleep(0.15)
        return {"status": "success", "output": config.get("tag", "slow-done")}

    async def asyncio_sleep(sec):
        import asyncio

        await asyncio.sleep(sec)

    definition = NodeDefinition(
        type="test:slow",
        label="慢节点",
        icon="🐢",
        category="flow",
        description="测试用慢节点",
        sub_blocks=[],
        inputs=[],
        outputs=[],
    )
    registry.register(definition, exec_slow)
    yield "test:slow"


def diamond_workflow(node_type):
    """start → a / b（同层） → end 的菱形"""
    nodes = [
        N("start", "builtin:start"),
        N("a", node_type, {"tag": "A"}),
        N("b", node_type, {"tag": "B"}),
        N("end", "builtin:end"),
    ]
    edges = [E("e1", "start", "a"), E("e2", "start", "b"), E("e3", "a", "end"), E("e4", "b", "end")]
    return make_workflow(nodes, edges)


class TestParallelLayers:
    @pytest.mark.asyncio
    async def test_same_layer_nodes_run_concurrently(self, slow_node_registered):
        """同层两个 0.15s 慢节点并发执行：总耗时接近单节点而非两倍"""
        executor = WorkflowExecutor()
        run = executor.execute
        workflow_def = diamond_workflow("test:slow")

        t0 = time.monotonic()
        instance = await run(workflow_def, inputs={})
        wall = time.monotonic() - t0

        assert instance.status == WorkflowStatus.COMPLETED
        assert instance.node_results["a"].status == "success"
        assert instance.node_results["b"].status == "success"
        # 串行需 ≥0.30s，并发应 <0.28s（留调度余量）
        assert wall < 0.28, f"同层节点疑似串行执行，耗时 {wall:.3f}s"

    @pytest.mark.asyncio
    async def test_failure_in_layer_fails_workflow(self, slow_node_registered):
        """层内节点失败 → 工作流失败且带节点定位"""
        registry = get_node_registry()

        async def exec_boom(config, ctx):
            raise RuntimeError("节点内部爆炸")

        definition = NodeDefinition(
            type="test:boom",
            label="爆炸节点",
            icon="💥",
            category="flow",
            description="测试用失败节点",
            sub_blocks=[],
            inputs=[],
            outputs=[],
        )
        registry.register(definition, exec_boom)

        nodes = [
            N("start", "builtin:start"),
            N("boom", "test:boom"),
            N("end", "builtin:end"),
        ]
        edges = [E("e1", "start", "boom"), E("e2", "boom", "end")]
        executor = WorkflowExecutor()
        run = executor.execute

        instance = await run(make_workflow(nodes, edges, "wf_boom"), inputs={})

        assert instance.status == WorkflowStatus.FAILED
        assert "boom" in (instance.error or "")
        assert instance.node_results["boom"].status == "failed"
