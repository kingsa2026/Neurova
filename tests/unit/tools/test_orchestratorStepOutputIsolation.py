# -*- coding: utf-8 -*-
"""CORE-15：编排器的步骤输出必须是**调用局部状态**，并发编排互不串会话。

根因：`ToolOrchestrator._step_outputs` 是实例字段，`orchestrate()` 入口重建、
finally 清空；同一编排器上两个并发编排会互相清空/覆盖步骤输出，上一会话的
输出可能进入下一会话的 `{step_<idx>.<field>}` 渲染（或把本会话输出清成空串）。
另：依赖成环时原实现把整层「无法解析」的步骤同层并行放行——环依赖必须显式拒绝。
"""
from __future__ import annotations

import asyncio

import pytest

from neurova.tool_layers.tool_orchestrator import ToolOrchestrator
from neurova.tool_layers.types import ExecutionStatus


@pytest.mark.asyncio
async def testConcurrentOrchestrationsKeepSeparateStepOutputs():
    """A 编排等待期间插入一次完整 B 编排：A 的后继步骤仍读到 A 自己的输出。"""
    orchestrator = ToolOrchestrator()
    a2_started = asyncio.Event()
    release_a2 = asyncio.Event()
    seen: dict = {}

    async def executor(tool: str, params: dict):
        if tool == "a2":
            a2_started.set()
            await release_a2.wait()
        if tool == "a3":
            seen["from"] = params.get("from")
        return {"value": f"{tool.upper()}-output"}

    orchestrator.set_executor(executor)

    plan_a = [
        {"tool": "a1"},
        {"tool": "a2", "depends_on": ["a1"]},
        {"tool": "a3", "params": {"from": "{step_0.value}"}, "depends_on": ["a2"]},
    ]
    task_a = asyncio.create_task(orchestrator.orchestrate("A", tool_plan=plan_a))
    await asyncio.wait_for(a2_started.wait(), timeout=5)

    # 第二个「会话」在同编排器上完整跑一遍；修复前它会清空/覆盖 A 的步骤输出。
    result_b = await orchestrator.orchestrate(
        "B", tool_plan=[{"tool": "b1", "params": {"x": 1}}]
    )
    assert result_b.status is ExecutionStatus.COMPLETED

    release_a2.set()
    result_a = await asyncio.wait_for(task_a, timeout=10)

    assert result_a.status is ExecutionStatus.COMPLETED, result_a.error
    assert seen["from"] == "A1-output", (
        f"A 的第三步拿到 {seen['from']!r}——跨编排共享了步骤输出（CORE-15）"
    )


@pytest.mark.asyncio
async def testCyclicDependencyIsRejectedNotRunInParallel():
    """环依赖显式拒绝；不得把未解析层整层并行放行。"""
    orchestrator = ToolOrchestrator()
    calls: list = []

    async def executor(tool: str, params: dict):
        calls.append(tool)
        return {"ok": True}

    orchestrator.set_executor(executor)

    result = await orchestrator.orchestrate(
        "cycle",
        tool_plan=[
            {"tool": "x", "depends_on": ["y"]},
            {"tool": "y", "depends_on": ["x"]},
        ],
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.error and ("环" in result.error or "cycle" in result.error.lower())
    assert calls == [], f"环依赖仍被执行：{calls}"