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
        executor = MagicMock()
        executor.execute = MagicMock()

        async def _execute(tool_name, params):
            if tool_name == "computer_screenshot":
                return {"success": True, "format": "png", "size_bytes": 100,
                        "frame_id": "f1"}
            return {"success": True, "tool_name": tool_name}

        executor.execute.side_effect = _execute
        return executor

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
