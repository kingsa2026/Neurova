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
