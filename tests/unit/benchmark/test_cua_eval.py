# -*- coding: utf-8 -*-
"""T3 公共 CUA 基准评测器（reference_af 拆解卡）红灯测试。

契约（拆解评测 §5 卡 T3，与 suite_eval P0-② 口径对齐）：
- 任务 = 指令 + 判据 check(终态证据)；执行器只产事实，判据注入；
- episode 异常（桌面不可用/驱动崩溃/权限拒绝）＝**评测器械故障**
  （failure_class="infra"），行级记 0 分与 error 事实、不进任务失败集合、
  不进均分母；判据异常同理（infra_checker）；
- score 只对量出来的任务求均值；全量器械故障 ⇒ score=None；
- 脚本化适配器：把固定 computer_* 动作序列经 ToolExecutor.execute 真管线跑完，
  拒绝/错误结果＝环境跑不动 → CuaInfraError（记 infra），不冒充任务失败。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.benchmark.cua_eval import (
    CuaInfraError,
    CuaTask,
    ToolExecutorEpisodeAdapter,
    runCuaTasks,
)


def _task(taskId: str, *, passed: bool):
    def _check(evidence):
        return passed, (1.0 if passed else 0.0), {"evidence_keys": sorted(evidence)}

    return CuaTask(task_id=taskId, instruction=f"任务 {taskId}", check=_check,
                   description="样例")


def _taskCheckerRaises(taskId: str):
    def _check(evidence):
        raise ValueError("checker bug")
    return CuaTask(task_id=taskId, instruction="任务", check=_check, description="样例")


def _executorStub():
    """桩执行器：computer_screenshot 返回真截图证据，其余动作回声成功。"""
    executor = MagicMock()
    executor.execute = MagicMock()

    async def _execute(tool_name, params):
        if tool_name == "computer_screenshot":
            return {"success": True, "format": "png", "size_bytes": 100,
                    "frame_id": "f1"}
        return {"success": True, "tool_name": tool_name}

    executor.execute.side_effect = _execute
    return executor


class TestRunCuaTasks:
    def test_judged_scoring_over_measured_only(self):
        tasks = [_task("t1", passed=True), _task("t2", passed=False)]

        def episode(task):
            return {"evidence": {"done": True}, "actions": 2}

        report = runCuaTasks(tasks, episode)
        assert report["status"] == "completed"
        assert report["tasks_total"] == 2
        assert report["tasks_judged"] == 2
        assert report["tasks_correct"] == 1
        assert report["tasks_failed"] == 1
        assert report["tasks_infra_failed"] == 0
        assert report["score"] == pytest.approx(0.5)
        assert all(row["failure_class"] == "" for row in report["per_task"])

    def test_episode_exception_is_infra_not_task_failure(self):
        tasks = [_task("t1", passed=True), _task("t2", passed=True)]

        def episode(task):
            if task.task_id == "t2":
                raise RuntimeError("桌面后端不可用")
            return {"evidence": {"done": True}}

        report = runCuaTasks(tasks, episode)
        assert report["tasks_total"] == 2
        assert report["tasks_judged"] == 1
        assert report["tasks_infra_failed"] == 1
        assert report["tasks_correct"] == 1
        assert report["score"] == pytest.approx(1.0), "器械故障不得拖低均分"
        bad = report["per_task"][1]
        assert bad["failure_class"] == "infra"
        assert bad["passed"] is False and bad["score"] == 0.0
        assert "桌面后端不可用" in bad["error"]

    def test_checker_exception_is_infra_checker(self):
        tasks = [_taskCheckerRaises("t1")]

        def episode(task):
            return {"evidence": {"done": True}}

        report = runCuaTasks(tasks, episode)
        row = report["per_task"][0]
        assert row["failure_class"] == "infra_checker"
        assert report["tasks_judged"] == 0
        assert report["tasks_infra_failed"] == 1
        assert report["score"] is None

    def test_all_infra_failures_score_none(self):
        tasks = [_task("t1", passed=True), _task("t2", passed=True)]

        def episode(task):
            raise CuaInfraError("无桌面权限")

        report = runCuaTasks(tasks, episode)
        assert report["tasks_judged"] == 0
        assert report["tasks_infra_failed"] == 2
        assert report["score"] is None
        assert all("无桌面权限" in row["error"] for row in report["per_task"])

    def test_empty_tasks_honest_none(self):
        report = runCuaTasks([], lambda task: {"evidence": {}})
        assert report["tasks_total"] == 0
        assert report["score"] is None
        assert report["status"] == "completed"

    def test_cost_note_passthrough(self):
        report = runCuaTasks([_task("t1", passed=True)],
                             lambda task: {"evidence": {}},
                             costNote={"run_by": "manual", "est_tokens": 100})
        assert report["cost_note"] == {"run_by": "manual", "est_tokens": 100}


class TestToolExecutorEpisodeAdapter:
    def _executor(self):
        return _executorStub()

    def test_adapter_runs_scripted_actions_through_executor(self):
        executor = self._executor()
        actions = {
            "t1": [
                {"tool": "computer_click", "params": {"x": 10, "y": 20}},
                {"tool": "computer_type", "params": {"text": "hello"}},
            ]
        }
        adapter = ToolExecutorEpisodeAdapter(executor, actions)

        async def _run():
            return await adapter(_task("t1", passed=True))

        import asyncio
        evidence = asyncio.run(_run())
        assert [c.args[0] for c in executor.execute.call_args_list] == [
            "computer_click", "computer_type", "computer_screenshot",
        ], "动作跑完必须补一次终态截图取证"
        assert evidence["task_id"] == "t1"
        assert len(evidence["action_results"]) == 2
        assert evidence["terminal"]["success"] is True

    def test_adapter_refusal_raises_infra(self):
        executor = MagicMock()
        refused = {"error": "被车道拒绝", "guardrail": {"code": "lane_busy"}}

        async def _execute(tool_name, params):
            return refused

        executor.execute.side_effect = _execute
        adapter = ToolExecutorEpisodeAdapter(executor, {
            "t1": [{"tool": "computer_click", "params": {"x": 1, "y": 1}}]})

        import asyncio
        with pytest.raises(CuaInfraError):
            asyncio.run(adapter(_task("t1", passed=True)))

    def test_adapter_no_actions_still_takes_terminal_screenshot(self):
        executor = self._executor()
        adapter = ToolExecutorEpisodeAdapter(executor, {"t1": []})

        import asyncio
        evidence = asyncio.run(adapter(_task("t1", passed=True)))
        executor.execute.assert_called_once_with("computer_screenshot", {})
        assert evidence["terminal"]["success"] is True


class TestActionDiscipline:
    """C1 动作空间纪律（OSWorld 失败驱动改进卡）：非白名单动作显式记
    invalid_action 且不执行——M1 教训（宏/裸代码被静默 no-op 冒充已执行）。

    - 白名单单源：computer_use 前台注入族 + 观察面取证工具（判据钉住对账）；
    - 非法步不产生 CuaInfraError（它是脚本错误，不是器械故障）；
    - 行级 action_invalid 计数 + 聚合 action_invalid_total。
    """

    def test_actionWhitelistCoversForegroundRosterAndObservation(self):
        from neurova.benchmark.cua_eval import cuaActionWhitelist
        from neurova.computer_use import FOREGROUND_DESKTOP_TOOLS

        whitelist = cuaActionWhitelist()
        assert FOREGROUND_DESKTOP_TOOLS <= whitelist, "白名单必须覆盖前台注入族（单源对账）"
        assert "computer_screenshot" in whitelist, "终态取证工具必须在白名单"
        assert all(name.startswith("computer_") for name in whitelist), \
            "白名单只收 computer_* 工具，宏/裸代码形态一律非法"

    def test_nonWhitelistedToolMarkedInvalidNotExecuted(self):
        executor = _executorStub()
        actions = {
            "t1": [
                {"tool": "computer_click", "params": {"x": 10, "y": 20}},
                {"tool": "basic_macro", "params": {"code": "Sub x End Sub"}},
                {"tool": "bash", "params": {"command": "code --add /x"}},
                {"tool": "", "params": {}},
            ]
        }
        adapter = ToolExecutorEpisodeAdapter(executor, actions)

        import asyncio
        evidence = asyncio.run(adapter(_task("t1", passed=True)))
        executedTools = [c.args[0] for c in executor.execute.call_args_list]
        assert "basic_macro" not in executedTools, "非法动作不得送执行管线"
        assert "bash" not in executedTools, "非法动作不得送执行管线"
        assert executedTools == ["computer_click", "computer_screenshot"], \
            "合法步照常执行 + 终态取证"
        assert evidence["action_invalid"] == 3, "行级 invalid 计数=非法步数"
        invalidRows = [r for r in evidence["action_results"] if r.get("invalid")]
        assert len(invalidRows) == 3
        assert all(r.get("reason") for r in invalidRows), "每条非法步带原因"

    def test_invalidActionIsNotInfraFailure(self):
        executor = _executorStub()
        actions = {"t1": [{"tool": "python_code", "params": {"code": "import os"}}]}
        adapter = ToolExecutorEpisodeAdapter(executor, actions)

        import asyncio
        evidence = asyncio.run(adapter(_task("t1", passed=False)))
        assert evidence["action_invalid"] == 1, "脚本错误≠器械故障，不得抛 CuaInfraError"

    def test_runCuaTasksAggregatesInvalidActionCounts(self):
        executor = _executorStub()
        actions = {
            "t_ok": [{"tool": "computer_click", "params": {"x": 1, "y": 2}}],
            "t_bad": [
                {"tool": "basic_macro", "params": {"code": "Sub x"}},
                {"tool": "computer_click", "params": {"x": 3, "y": 4}},
                {"tool": "python_code", "params": {"code": "print(1)"}},
            ],
        }
        adapter = ToolExecutorEpisodeAdapter(executor, actions)
        tasks = [_task("t_ok", passed=True), _task("t_bad", passed=False)]

        report = runCuaTasks(tasks, adapter)
        assert report["tasks_judged"] == 2, "非法动作不改变 judged 口径"
        assert report["tasks_infra_failed"] == 0, "脚本错误不得记成器械故障"
        assert report["action_invalid_total"] == 2, "聚合 invalid 计数"
        byId = {row["task_id"]: row for row in report["per_task"]}
        assert byId["t_ok"]["action_invalid"] == 0
        assert byId["t_bad"]["action_invalid"] == 2

    def test_injectedEpisodeWithoutInvalidFieldDefaultsZero(self):
        report = runCuaTasks([_task("t1", passed=True)],
                             lambda task: {"evidence": {}})
        assert report["action_invalid_total"] == 0
        assert report["per_task"][0]["action_invalid"] == 0


class TestRepeatedRuns:
    """C2 多 run 聚合（OSWorld M5 教训：同任务同配置跨 run 翻转
    ——冒烟轮 1.0/子集轮 0.0）。同任务集 N 轮评测 → 均值±std、逐任务
    翻转标记；repeats=1 时与单轮 runCuaTasks 口径一致（零破坏）。"""

    def _flipFlopTasks(self):
        def _check(evidence):
            done = bool(evidence.get("done"))
            return done, (1.0 if done else 0.0), {}

        return [CuaTask(task_id="t_flip", instruction="任务", check=_check,
                        description="样例")]

    def test_flippedTaskMarkedWithMeanAndScores(self):
        from neurova.benchmark.cua_eval import runCuaTasksRepeated

        state = {"call": 0}

        def episode(task):
            state["call"] += 1
            return {"done": state["call"] % 2 == 1}  # 轮1过、轮2不过

        report = runCuaTasksRepeated(self._flipFlopTasks(), episode, repeats=2)
        assert report["runs"] == 2
        row = report["per_task"][0]
        assert row["task_id"] == "t_flip"
        assert row["scores"] == [1.0, 0.0]
        assert row["mean_score"] == pytest.approx(0.5)
        assert row["flipped"] is True, "轮次间 0/非0 分歧必须标翻转"
        assert report["flipped_tasks"] == 1
        assert report["mean_score"] == pytest.approx(0.5)

    def test_stableTaskNotFlipped(self):
        from neurova.benchmark.cua_eval import runCuaTasksRepeated

        report = runCuaTasksRepeated(
            [_task("t_stable", passed=True)], lambda task: {"done": True}, repeats=3)
        row = report["per_task"][0]
        assert row["flipped"] is False
        assert row["scores"] == [1.0, 1.0, 1.0]
        assert row["mean_score"] == pytest.approx(1.0)
        assert report["flipped_tasks"] == 0
        assert report["mean_score"] == pytest.approx(1.0)

    def test_repeatsOneKeepsSingleRunContract(self):
        from neurova.benchmark.cua_eval import runCuaTasksRepeated

        single = runCuaTasks([_task("t1", passed=True)], lambda t: {"evidence": {}})
        repeated = runCuaTasksRepeated([_task("t1", passed=True)],
                                       lambda t: {"evidence": {}}, repeats=1)
        assert repeated["runs"] == 1
        assert repeated["score"] == single["score"]
        assert repeated["tasks_total"] == single["tasks_total"]
        assert repeated["per_task"][0]["flipped"] is False

    def test_repeatedRunKeepsInfraAndInvalidFacts(self):
        from neurova.benchmark.cua_eval import runCuaTasksRepeated

        def episode(task):
            if task.task_id == "t_infra":
                raise RuntimeError("桌面不可用")
            return {"done": True, "action_invalid": 2}

        tasks = [
            _task("t_ok", passed=True),
            CuaTask(task_id="t_infra", instruction="任务",
                    check=lambda e: (True, 1.0, {}), description="样例"),
        ]
        report = runCuaTasksRepeated(tasks, episode, repeats=2)
        assert report["action_invalid_total"] == 4, "跨轮 invalid 累计"
        byId = {row["task_id"]: row for row in report["per_task"]}
        assert byId["t_infra"]["runs_infra"] == 2, "每轮器械故障计数保留"
        assert byId["t_infra"]["flipped"] is False, "全量 infra 不算翻转（没量到≠翻转）"
        assert byId["t_ok"]["mean_score"] == pytest.approx(1.0)

    def test_costNoteOnTopLevelReport(self):
        from neurova.benchmark.cua_eval import runCuaTasksRepeated

        report = runCuaTasksRepeated([_task("t1", passed=True)],
                                     lambda t: {"evidence": {}}, repeats=2,
                                     costNote={"run_by": "manual"})
        assert report["cost_note"] == {"run_by": "manual"}


class TestDoneWithoutVerify:
    """C3-1 行级信号（OSWorld M2 教训：DONE 声明假完成率 30%）：任务声明
    完成（claimed_done）但最后一步不是观察面核验动作（截图/窗口枚举）
    → 行级 done_without_verify=True，聚合 done_without_verify_tasks 计数。
    无声明不标；last_action_tool 缺失不臆造。"""

    def test_claimedDoneWithoutCheckActionFlagged(self):
        def episode(task):
            return {"claimed_done": True, "last_action_tool": "computer_click"}

        report = runCuaTasks([_task("t1", passed=False)], episode)
        row = report["per_task"][0]
        assert row["done_without_verify"] is True
        assert report["done_without_verify_tasks"] == 1

    def test_claimedDoneAfterScreenshotNotFlagged(self):
        def episode(task):
            return {"claimed_done": True, "last_action_tool": "computer_screenshot"}

        report = runCuaTasks([_task("t1", passed=True)], episode)
        assert report["per_task"][0]["done_without_verify"] is False
        assert report["done_without_verify_tasks"] == 0

    def test_noClaimNotFlagged(self):
        report = runCuaTasks([_task("t1", passed=False)],
                             lambda t: {"last_action_tool": "computer_click"})
        assert report["per_task"][0]["done_without_verify"] is False
        assert report["done_without_verify_tasks"] == 0

    def test_missingLastActionToolNotFabricated(self):
        def episode(task):
            return {"claimed_done": True}

        report = runCuaTasks([_task("t1", passed=False)], episode)
        assert report["per_task"][0]["done_without_verify"] is False, \
            "无最后动作信息时不臆造判定"

    def test_adapterEpisodeDefaultsNoClaim(self):
        adapter = ToolExecutorEpisodeAdapter(_executorStub(), {
            "t1": [{"tool": "computer_click", "params": {"x": 1, "y": 2}}]})

        import asyncio
        evidence = asyncio.run(adapter(_task("t1", passed=True)))
        assert "claimed_done" not in evidence, "脚本化形态无完成声明概念"
        assert evidence["last_action_tool"] == "computer_click"
        report = runCuaTasks([_task("t1", passed=True)], lambda t: evidence)
        assert report["done_without_verify_tasks"] == 0

    def test_repeatedRunAccumulatesDoneWithoutVerify(self):
        from neurova.benchmark.cua_eval import runCuaTasksRepeated

        def episode(task):
            return {"claimed_done": True, "last_action_tool": "computer_type"}

        report = runCuaTasksRepeated([_task("t1", passed=False)], episode, repeats=2)
        assert report["done_without_verify_tasks"] == 2, "跨轮累计"
        assert report["per_task"][0]["done_without_verify"] is True
