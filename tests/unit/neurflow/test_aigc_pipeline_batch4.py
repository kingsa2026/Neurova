# -*- coding: utf-8 -*-
"""批次4（打通画布）引擎侧：loop items_from 数组迭代 + 节点注册时序。

1. items_from：分镜 shots[] → 逐镜扇出的正解挂载点（火宝式批量逐镜生成）。
   配置变量引用（resolve 后为 list）时按数组逐元素迭代，body 经
   ``${loopId.output}`` 取当轮元素；迭代次数=数组长度（优先于 max_iterations，
   上限仍受 1000 保护）。非数组引用回退既有计数循环语义（增强不替换）。
2. canvas_bridge._known_node_types 只 ensure_builtin+custom → 新进程未先拉
   节点库（GET /neurflow/nodes）时，含 drama/comfyui 节点的画布 run 被
   "未注册类型" 400 拒绝。收口：校验前同步适配器（幂等，失败降级不阻塞）。
"""
from __future__ import annotations

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


def N(id, type="builtin:transform", config=None):
    return WorkflowNode(id=id, type=type, position={"x": 0, "y": 0}, config=config or {})


def E(id, source, target, source_handle=None, target_handle=None):
    return WorkflowEdge(id=id, source=source, target=target, source_handle=source_handle, target_handle=target_handle)


def wf(nodes, edges, workflow_id="wf_items_from"):
    return WorkflowDefinition(
        id=workflow_id, name="items_from 测试", description="", version="1.0.0",
        nodes=nodes, edges=edges, variables=[], tags=[], category="test",
        author="test", created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
    )


def build_loop(items_from=None, max_iterations=3):
    loop_cfg = {"max_iterations": max_iterations}
    if items_from is not None:
        loop_cfg["items_from"] = items_from
    nodes = [
        N("start", "builtin:start"),
        N("loop", "builtin:loop", loop_cfg),
        N("body1", "builtin:transform", {"expression": "iter"}),
        N("end", "builtin:end"),
    ]
    edges = [
        E("e1", "start", "loop"),
        E("e2", "loop", "body1", source_handle="current"),
        E("e3", "body1", "loop", target_handle="loop_body"),
        E("e4", "loop", "end", source_handle="loop_done"),
    ]
    return wf(nodes, edges)


class TestLoopItemsFrom:
    @pytest.mark.asyncio
    async def test_array_iterates_element_per_round(self):
        shots = [{"title": "镜头1"}, {"title": "镜头2"}, {"title": "镜头3"}]
        executor = WorkflowExecutor()
        events = []
        executor.on_event(events.append)

        instance = await executor.execute(build_loop(items_from=shots), inputs={})

        assert instance.status == WorkflowStatus.COMPLETED
        out = instance.node_results["loop"].output
        assert out["iterations"] == 3
        assert out["last_output"] == shots[-1]
        assert out["broken"] is False
        # body 每轮收到当轮元素：loop.output 在迭代内 = 当前元素
        assert instance.node_results["body1"].output == "transform: iter"

    @pytest.mark.asyncio
    async def test_array_length_overrides_max_iterations(self):
        items = [1, 2, 3, 4, 5]
        executor = WorkflowExecutor()
        instance = await executor.execute(
            build_loop(items_from=items, max_iterations=2), inputs={})
        assert instance.node_results["loop"].output["iterations"] == 5

    @pytest.mark.asyncio
    async def test_empty_array_zero_iterations(self):
        executor = WorkflowExecutor()
        instance = await executor.execute(build_loop(items_from=[]), inputs={})
        out = instance.node_results["loop"].output
        assert out["iterations"] == 0

    @pytest.mark.asyncio
    async def test_non_list_items_from_falls_back_to_count_loop(self):
        # 变量解析失败留下原始字符串 → 回退既有计数循环（增强不替换）
        executor = WorkflowExecutor()
        instance = await executor.execute(
            build_loop(items_from="$missing.output.shots", max_iterations=2), inputs={})
        assert instance.node_results["loop"].output["iterations"] == 2

    @pytest.mark.asyncio
    async def test_body_sees_current_element(self):
        """逐镜生图扇出：body 配置 ${node.loop.output.title} 取到当轮元素字段。"""
        items = [{"title": "A镜"}, {"title": "B镜"}]
        nodes = [
            N("start", "builtin:start"),
            N("loop", "builtin:loop", {"max_iterations": 10, "items_from": items}),
            N("body1", "builtin:transform", {"expression": "$node.loop.output.title"}),
            N("end", "builtin:end"),
        ]
        edges = [
            E("e1", "start", "loop"),
            E("e2", "loop", "body1", source_handle="current"),
            E("e3", "body1", "loop", target_handle="loop_body"),
            E("e4", "loop", "end", source_handle="loop_done"),
        ]
        executor = WorkflowExecutor()
        # 末轮 body 输出 = 末元素字段（${loop.output.title} → "B镜"）
        instance = await executor.execute(wf(nodes, edges, "wf_elem"), inputs={})
        assert instance.node_results["body1"].output == "transform: B镜"


class TestCanvasBridgeSyncAdapters:
    def test_known_types_include_drama_after_reset(self):
        """新进程语义：仅 reset 后走 canvas_bridge 校验路径，drama 节点必须已知。"""
        from neurova.collaboration import canvas_bridge
        from neurova.collaboration.neurflow.node_registry import reset_node_registry

        reset_node_registry()
        try:
            known = canvas_bridge._known_node_types()
            assert "builtin:storyboard" in known
            assert "builtin:short-drama-script" in known
        finally:
            reset_node_registry()


class TestEndOutputMapping:
    """批次5 验收发现：end 的 output_mapping 从未被消费（media/short_drama
    模板恒声明），execution.outputs 恒为 {"result": 末节点裸输出}。"""

    @pytest.mark.asyncio
    async def test_output_mapping_structured(self):
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowStatus,
        )
        nodes = [
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="src", type="builtin:variable", position={"x": 1, "y": 0},
                         config={"name": "k", "value": [{"shot": 1, "url": "/f/a.png"}]}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 2, "y": 0}, config={
                "output_mapping": {"storyboard": "$node.src.output.value",
                                   "plain": "literal-tag"},
            }),
        ]
        edges = [WorkflowEdge(id="e1", source="start", target="src"),
                 WorkflowEdge(id="e2", source="src", target="end")]
        wf = WorkflowDefinition(
            id="wf_map", name="m", description="", version="1.0.0", nodes=nodes,
            edges=edges, variables=[], tags=[], category="t", author="t",
            created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
        )
        instance = await WorkflowExecutor().execute(wf, inputs={})
        assert instance.status == WorkflowStatus.COMPLETED
        result = instance.outputs["result"]
        assert result["plain"] == "literal-tag"
        assert result["storyboard"] == [{"shot": 1, "url": "/f/a.png"}]

    @pytest.mark.asyncio
    async def test_end_without_mapping_keeps_last_output(self):
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowStatus,
        )
        nodes = [
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="src", type="builtin:variable", position={"x": 1, "y": 0},
                         config={"name": "k", "value": "hello"}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 2, "y": 0}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="start", target="src"),
                 WorkflowEdge(id="e2", source="src", target="end")]
        wf = WorkflowDefinition(
            id="wf_nomap", name="m", description="", version="1.0.0", nodes=nodes,
            edges=edges, variables=[], tags=[], category="t", author="t",
            created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
        )
        instance = await WorkflowExecutor().execute(wf, inputs={})
        # 向后兼容：无 mapping 的 end 仍传末节点输出
        assert instance.outputs["result"] == {"name": "k", "value": "hello"}


class TestLazyExecutorSync:
    """批次5 验收根修：模板 execute 路径此前不触发 sync_all——drama 执行器
    未注册时节点静默 {"output": None} 假成功（一键成片产物恒空的真因）。
    引擎现惰性补偿同步（幂等）+ 仍无执行器时节点失败。"""

    @pytest.mark.asyncio
    async def test_drama_nodes_execute_without_prior_sync(self):
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        from neurova.collaboration.neurflow.node_registry import reset_node_registry
        from neurova.collaboration.neurflow.templates.short_drama import get_short_drama_template

        reset_node_registry()  # 新进程语义：仅 builtin
        try:
            instance = await WorkflowExecutor().execute(
                get_short_drama_template(),
                inputs={"theme": "测试", "genre": "都市逆袭", "style": "国风",
                        "aspect_ratio": "9:16", "image_provider": "openai"},
            )
        finally:
            reset_node_registry()
        from neurova.collaboration.neurflow.models import WorkflowStatus
        assert instance.status == WorkflowStatus.COMPLETED
        result = (instance.outputs or {}).get("result") or {}
        # drama 节点经惰性补偿真实执行：分镜/合成产物非 None
        assert result.get("storyboard"), "storyboard 输出不应为 None"
        assert result.get("compose"), "compose 输出不应为 None"

    @pytest.mark.asyncio
    async def test_unknown_type_fails_honest(self):
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowStatus,
        )
        nodes = [
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="x", type="builtin:definitely_not_registered_zz",
                         position={"x": 1, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 2, "y": 0}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="start", target="x"),
                 WorkflowEdge(id="e2", source="x", target="end")]
        wf = WorkflowDefinition(
            id="wf_unknown", name="m", description="", version="1.0.0", nodes=nodes,
            edges=edges, variables=[], tags=[], category="t", author="t",
            created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
        )
        instance = await WorkflowExecutor().execute(wf, inputs={})
        # 诚实失败：不再静默 output=None 假成功
        assert instance.status == WorkflowStatus.FAILED
        assert "未注册执行器" in str(instance.error)
