# -*- coding: utf-8 -*-
"""C6 规划器拆步两阶段适配器（OSWorld 失败驱动改进卡）红灯测试。

M1 反例教训 + multi_apps 1/5 最难域：单模型直接出动作在长链上步数与注意力
都不够。两阶段 = 规划器先按任务+首帧拆出**带验收条件的步骤清单**，执行器
逐步驱动；步失败可重规划（有界）。判据与 failure_class 口径与单阶段完全
一致（task.check 吃终态证据；blocked → CuaInfraError 记 infra）。

步验收语义（诚实口径）：
- 带 ``verify`` 的步：验收判 (pass/fail)；fail → 触发重规划（有界）；
- 无 ``verify`` 的步：如实记 ``unverified``（没量到 ≠ 通过）；
- 步内动作全部 invalid（C1 口径）＝步失败 → 触发重规划；
- 步内动作被环境拒（blocked）→ CuaInfraError：器械故障口径不变，不重规划。
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from neurova.benchmark.cua_eval import (
    CuaInfraError,
    CuaTask,
    PlannerExecutorEpisodeAdapter,
    PlannedStep,
    runCuaTasks,
)


def _executorStub():
    executor = MagicMock()
    executor.execute = MagicMock()

    async def _execute(tool_name, params):
        if tool_name == "computer_screenshot":
            return {"success": True, "format": "png", "size_bytes": 100,
                    "frame_id": "f"}
        return {"success": True, "tool_name": tool_name}

    executor.execute.side_effect = _execute
    return executor


def _task(taskId="t1", passed=True):
    def _check(evidence):
        return passed, (1.0 if passed else 0.0), {}
    return CuaTask(task_id=taskId, instruction="任务", check=_check, description="样例")


def _run(coro):
    return asyncio.run(coro)


class TestPlannerExecutorAdapter:
    def test_plannedStepsRunInOrderThenTerminal(self):
        calls = []

        def planner(task, context):
            calls.append(dict(context))
            return [
                PlannedStep(description="点开菜单",
                            actions=[{"tool": "computer_click", "params": {"x": 1, "y": 2}}]),
                PlannedStep(description="输入文本",
                            actions=[{"tool": "computer_type", "params": {"text": "hi"}}]),
            ]

        executor = _executorStub()
        adapter = PlannerExecutorEpisodeAdapter(executor, planner)
        evidence = _run(adapter(_task()))
        assert [c.args[0] for c in executor.execute.call_args_list] == [
            "computer_screenshot",  # 首帧取证（供规划器读初始画面）
            "computer_click", "computer_screenshot",  # 步 1 动作 + 步后帧
            "computer_type", "computer_screenshot",  # 步 2 动作 + 步后帧
            "computer_screenshot",  # 终态取证
        ], "首帧 → 步骤动作按序（每步带步后帧）→ 终态取证"
        assert evidence["first_frame"] is not None, "首帧证据必须挂 episode 证据面"
        assert evidence["planned_steps"] == 2
        assert evidence["executed_steps"] == 2
        assert evidence["replan_count"] == 0
        assert evidence["replanned"] is False
        assert calls[0].get("failed_step") is None, "首轮规划不带失败步"

    def test_stepVerifyPassNoReplan(self):
        def planner(task, context):
            return [PlannedStep(description="s1",
                                actions=[{"tool": "computer_click", "params": {}}],
                                verify=lambda ev: (True, 1.0, {}))]

        evidence = _run(PlannerExecutorEpisodeAdapter(_executorStub(), planner)(_task()))
        assert evidence["steps_detail"][0]["verify"] == "pass"
        assert evidence["replan_count"] == 0

    def test_verifyFailTriggersBoundedReplan(self):
        attempts = []

        def planner(task, context):
            attempts.append(context.get("failed_step"))
            if context.get("failed_step"):
                # 重规划：换一条可过的路
                return [PlannedStep(description="s1-fix",
                                    actions=[{"tool": "computer_key", "params": {"key": "esc"}}],
                                    verify=lambda ev: (True, 1.0, {}))]
            return [PlannedStep(description="s1",
                                actions=[{"tool": "computer_click", "params": {}}],
                                verify=lambda ev: (False, 0.0, {}))]

        evidence = _run(PlannerExecutorEpisodeAdapter(_executorStub(), planner)(_task()))
        assert attempts == [None, "s1"], "重规划必须携带失败步描述"
        assert evidence["replan_count"] == 1
        assert evidence["replanned"] is True
        assert evidence["steps_detail"][-1]["description"] == "s1-fix"

    def test_replanIsBounded(self):
        def planner(task, context):
            # 永远失败：验证有界（默认 maxReplans=1，不会无限循环）
            return [PlannedStep(description="always-fail",
                                actions=[{"tool": "computer_click", "params": {}}],
                                verify=lambda ev: (False, 0.0, {}))]

        evidence = _run(PlannerExecutorEpisodeAdapter(
            _executorStub(), planner, maxReplans=1)(_task()))
        assert evidence["replan_count"] == 1, "重规划超界即停，不无限循环"

    def test_unverifiedStepRecordedHonestly(self):
        def planner(task, context):
            return [PlannedStep(description="s1",
                                actions=[{"tool": "computer_click", "params": {}}])]

        evidence = _run(PlannerExecutorEpisodeAdapter(_executorStub(), planner)(_task()))
        assert evidence["steps_detail"][0]["verify"] == "unverified", \
            "没量到 ≠ 通过"

    def test_allInvalidStepFailsAndTriggersReplan(self):
        replans = []

        def planner(task, context):
            replans.append(context.get("failed_step"))
            if context.get("failed_step"):
                return [PlannedStep(description="legal-step",
                                    actions=[{"tool": "computer_click", "params": {}}])]
            return [PlannedStep(description="macro-step",
                                actions=[{"tool": "basic_macro", "params": {"code": "Sub"}}],
                                verify=lambda ev: (True, 1.0, {}))]

        evidence = _run(PlannerExecutorEpisodeAdapter(_executorStub(), planner)(_task()))
        assert replans == [None, "macro-step"], "步内全 invalid＝步失败→重规划"
        assert evidence["action_invalid"] == 1, "invalid 计数口径保持"

    def test_blockedActionStillInfraNoReplan(self):
        executor = MagicMock()

        async def _execute(tool_name, params):
            return {"error": "被车道拒绝"}

        executor.execute.side_effect = _execute

        def planner(task, context):
            return [PlannedStep(description="s1",
                                actions=[{"tool": "computer_click", "params": {}}])]

        with pytest.raises(CuaInfraError):
            _run(PlannerExecutorEpisodeAdapter(executor, planner)(_task()))

    def test_asyncPlannerSupported(self):
        async def planner(task, context):
            return [PlannedStep(description="s1",
                                actions=[{"tool": "computer_click", "params": {}}])]

        evidence = _run(PlannerExecutorEpisodeAdapter(_executorStub(), planner)(_task()))
        assert evidence["executed_steps"] == 1

    def test_runCuaTasksIntegrationKeepsAggregates(self):
        def planner(task, context):
            if context.get("failed_step"):
                return [PlannedStep(description="fix",
                                    actions=[{"tool": "computer_click", "params": {}}])]
            return [PlannedStep(description="bad",
                                actions=[{"tool": "python_code", "params": {"code": "x"}}],
                                verify=lambda ev: (False, 0.0, {}))]

        report = runCuaTasks([_task()], PlannerExecutorEpisodeAdapter(
            _executorStub(), planner))
        row = report["per_task"][0]
        assert report["tasks_infra_failed"] == 0, "重规划不改变 judged 口径"
        assert report["action_invalid_total"] == 1
        assert row["replanned"] is True, "行级事实保留重规划标记"