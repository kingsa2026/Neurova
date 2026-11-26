# -*- coding: utf-8 -*-
"""CUA 桌面基准评测器（T3，reference_af 拆解卡）。

把 computer_use 动作面接进与 :mod:`neurova.benchmark.suite_eval` 同构的判据
注入式评测：任务 = 指令 + 判据 ``check(终态证据)``；执行器只产事实，不伪造
分数。与 suite_eval 同一套 P0-② 纪律：

- episode 异常（桌面不可用/权限拒绝/驱动崩溃）＝**评测器械故障**
  （``failure_class="infra"``）：行级记 0 分与 error 事实、计入 tasks_total，
  但不进任务失败集合、不进均分母；
- 判据异常同理（``failure_class="infra_checker"``）；
- ``score`` 只对量出来的任务（judged）求均值；全量器械故障 ⇒ ``score=None``
  （没量到 ≠ 量出为零）；空任务库如实 None；
- 失败分类计数外露：tasks_judged / tasks_failed / tasks_infra_failed。

执行形态：任务跑法经 ``episodeFn`` 注入（同步返回终态证据 dict）。脚本化
适配器 :class:`ToolExecutorEpisodeAdapter` 把固定 computer_* 动作序列经
``ToolExecutor.execute`` 真管线跑完并补终态截图取证；判定"环境跑不动"的
拒绝/错误 → :class:`CuaInfraError`（记 infra）。评测默认**手动跑+成本标注**
（D-H 纪律），CI 不接真桌面跑。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "CuaInfraError",
    "CuaTask",
    "PlannedStep",
    "PlannerExecutorEpisodeAdapter",
    "ToolExecutorEpisodeAdapter",
    "cuaActionWhitelist",
    "runCuaTasks",
    "runCuaTasksRepeated",
]

CheckFn = Callable[[Dict[str, Any]], Tuple[bool, float, dict]]
EpisodeFn = Callable[[Any], Dict[str, Any]]
_SCORE_DIGITS = 6

# 观察面取证工具（只读，不注入输入）：动作脚本里允许出现，但它们不是"操作"。
_CUA_OBSERVATION_TOOLS = frozenset({"computer_screenshot", "computer_list_windows"})
_actionWhitelistCache: Optional[frozenset] = None


def cuaActionWhitelist() -> frozenset:
    """CUA 动作步骤合法工具名单（C1 动作空间纪律）。

    单一事实源（R6）：前台注入族直接取 :data:`neurova.computer_use.FOREGROUND_DESKTOP_TOOLS`
    名册，另加观察面取证工具（只读，不注入输入）。名单外的动作形态（LibreOffice
    Basic 宏 / 裸 python / bash 等——OSWorld M1 失败模式）在脚本化 episode 里
    一律记 ``invalid`` 且不送执行管线，不冒充已执行。
    """
    global _actionWhitelistCache
    if _actionWhitelistCache is None:
        # 惰性 import：computer_use 顶层可能携带可选重依赖（仓规：可选依赖惰性加载）
        from neurova.computer_use import FOREGROUND_DESKTOP_TOOLS

        _actionWhitelistCache = (
            frozenset(FOREGROUND_DESKTOP_TOOLS) | _CUA_OBSERVATION_TOOLS
        )
    return _actionWhitelistCache


class CuaInfraError(RuntimeError):
    """评测器械故障：桌面/执行环境跑不动本任务（区别于"任务没做对"）。"""


@dataclass
class CuaTask:
    """一道桌面评测题：指令 + 判据。判据吃终态证据，输出 (passed, score, details)。"""

    task_id: str
    instruction: str
    check: CheckFn
    description: str = ""


def _looksBlocked(result: Any) -> bool:
    """动作结果是否为"环境跑不动"（结构化拒绝/错误）——脚本化 episode 里
    任何一步被拒/报错都说明桌面侧无法完成本任务，按器械故障记。"""
    return isinstance(result, dict) and bool(result.get("error") or result.get("guardrail"))


def _firstError(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result)[:200]
    return str(result.get("error") or result.get("guardrail") or "未知拒绝")[:200]


async def _runActionSteps(
    executor: Any,
    taskId: str,
    script: List[Dict[str, Any]],
    whitelist: frozenset,
) -> Tuple[List[Dict[str, Any]], int, List[str]]:
    """动作步执行原语（C1 口径，两代 adapter 共享——R6 不复制执行逻辑）。

    白名单校验、非法步跳过计数、blocked → CuaInfraError。
    Returns:
        (results, invalidCount, executedTools)
    """
    results: List[Dict[str, Any]] = []
    invalidCount = 0
    for step in script:
        tool = str(step.get("tool") or "")
        params = dict(step.get("params") or {})
        if tool not in whitelist:
            # C1 动作空间纪律：名单外动作（宏/裸代码）显式记 invalid 且不执行——
            # 脚本错误≠器械故障（不抛 CuaInfraError），计数进行级与聚合。
            invalidCount += 1
            results.append(
                {
                    "tool": tool,
                    "invalid": True,
                    "reason": "not_in_action_whitelist",
                }
            )
            logger.warning(
                "[cua_eval] 非法动作步已跳过 tool=%r task=%s", tool, taskId
            )
            continue
        result = await executor.execute(tool, params)
        results.append({"tool": tool, "result": result})
        if _looksBlocked(result):
            raise CuaInfraError(f"动作 {tool} 被环境拒绝/失败: {_firstError(result)}")
    executedTools = [entry["tool"] for entry in results if not entry.get("invalid")]
    return results, invalidCount, executedTools


async def _takeFrame(executor: Any, terminalTool: str, purpose: str) -> Dict[str, Any]:
    """取证帧（终态/步后帧共用；blocked → CuaInfraError）。"""
    frame = await executor.execute(terminalTool, {})
    if _looksBlocked(frame):
        raise CuaInfraError(f"{purpose} {terminalTool} 失败: {_firstError(frame)}")
    return frame


class ToolExecutorEpisodeAdapter:
    """把固定 computer_* 动作脚本经 ``ToolExecutor.execute`` 真管线跑成 episode。

    - 逐动作过统一执行管线（护栏/审计/归一化/重试闸照旧，无旁路）；
    - 动作跑完自动补一次终态截图取证（``terminalTool``，缺省
      computer_screenshot）；
    - 任一动作被拒/报错 → :class:`CuaInfraError`（环境跑不动，记 infra）。
      脚本化形态下动作是评测基建的一部分，它失败≠任务答错。
    """

    def __init__(
        self,
        toolExecutor: Any,
        actionsByTaskId: Dict[str, List[Dict[str, Any]]],
        terminalTool: str = "computer_screenshot",
    ):
        self._executor = toolExecutor
        self._actions = actionsByTaskId
        self._terminalTool = terminalTool

    async def __call__(self, task: Any) -> Dict[str, Any]:
        script = list(self._actions.get(task.task_id) or [])
        whitelist = cuaActionWhitelist()
        results, invalidCount, executedTools = await _runActionSteps(
            self._executor, task.task_id, script, whitelist
        )
        terminal = await _takeFrame(self._executor, self._terminalTool, "终态取证")
        return {
            "task_id": task.task_id,
            "instruction": task.instruction,
            "action_results": results,
            "action_invalid": invalidCount,
            "last_action_tool": executedTools[-1] if executedTools else self._terminalTool,
            "terminal": terminal,
        }


@dataclass
class PlannedStep:
    """规划器产出的一个带验收条件的执行步骤（C6 两阶段形态）。"""

    description: str
    actions: List[Dict[str, Any]]
    #: 步验收（吃步后证据 dict：action_results/action_invalid/step_frame）；
    #: 缺省 None＝无验收（episode 里如实记 unverified，没量到≠通过）。
    verify: Optional[CheckFn] = None


class PlannerExecutorEpisodeAdapter:
    """两阶段 episode（C6）：规划器拆步 → 执行器逐步驱动 → 步失败重规划（有界）。

    - ``plannerFn(task, context) -> List[PlannedStep]``（同步/异步兼容）；
      ``context``：``{"first_frame": 终态取证证据, "failed_step": 失败步描述|
      None, "attempt": 重规划轮次}``；
    - 步验收：带 ``verify`` 的步判 pass/fail，fail → 重规划（``maxReplans``
      有界，缺省 1）；无 ``verify`` 如实记 unverified；步内全 invalid（C1
      口径）＝步失败 → 重规划；
    - 步内动作被环境拒（blocked）→ :class:`CuaInfraError`：器械故障口径
      不变，不重规划；
    - 判据不变：终态证据仍由 ``task.check`` 判（本 adapter 只换 episode
      生成方式，判据/failure_class 与单阶段完全一致）。
    """

    def __init__(
        self,
        toolExecutor: Any,
        plannerFn: Callable[[Any, Dict[str, Any]], Any],
        terminalTool: str = "computer_screenshot",
        maxReplans: int = 1,
    ):
        self._executor = toolExecutor
        self._plannerFn = plannerFn
        self._terminalTool = terminalTool
        self._maxReplans = max(0, int(maxReplans))

    async def _callPlanner(
        self, task: Any, context: Dict[str, Any]
    ) -> List[PlannedStep]:
        outcome = self._plannerFn(task, context)
        if hasattr(outcome, "__await__"):
            outcome = await outcome
        return list(outcome or [])

    async def _executeStep(
        self, taskId: str, step: PlannedStep, whitelist: frozenset
    ) -> Tuple[Dict[str, Any], int]:
        """执行一个规划步：动作 → 步后帧 → 验收。返回 (步事实, 步内 invalid 数)。"""
        results, invalidCount, executedTools = await _runActionSteps(
            self._executor, taskId, step.actions, whitelist
        )
        frame = await _takeFrame(self._executor, self._terminalTool, "步后取证")
        stepEvidence = {
            "description": step.description,
            "action_results": results,
            "action_invalid": invalidCount,
            "last_action_tool": executedTools[-1] if executedTools else self._terminalTool,
            "step_frame": frame,
        }
        if step.verify is None:
            stepEvidence["verify"] = "unverified"
            return stepEvidence, invalidCount
        try:
            passed, _score, details = step.verify(stepEvidence)
        except Exception as exc:  # noqa: BLE001 - 验收器故障不掩盖执行事实
            stepEvidence["verify"] = "error"
            stepEvidence["details"] = {"verify_error": str(exc)}
            return stepEvidence, invalidCount
        stepEvidence["verify"] = "pass" if passed else "fail"
        if details:
            stepEvidence["details"] = details
        return stepEvidence, invalidCount

    async def __call__(self, task: Any) -> Dict[str, Any]:
        whitelist = cuaActionWhitelist()
        firstFrame = await _takeFrame(
            self._executor, self._terminalTool, "首帧取证"
        )
        steps = await self._callPlanner(
            task,
            {"first_frame": firstFrame, "failed_step": None, "attempt": 0},
        )
        actionResults: List[Dict[str, Any]] = []
        invalidTotal = 0
        stepsDetail: List[Dict[str, Any]] = []
        replanCount = 0
        executedSteps = 0
        lastExecuted: Optional[str] = None
        index = 0
        while index < len(steps):
            step = steps[index]
            stepEvidence, invalidCount = await self._executeStep(
                task.task_id, step, whitelist
            )
            actionResults.extend(stepEvidence.get("action_results") or [])
            invalidTotal += invalidCount
            executedSteps += 1
            lastExecuted = stepEvidence.get("last_action_tool") or lastExecuted
            stepsDetail.append(
                {
                    "description": step.description,
                    "action_count": len(step.actions),
                    "action_invalid": invalidCount,
                    "verify": stepEvidence.get("verify"),
                    "from_replan": replanCount > 0,
                    "details": stepEvidence.get("details") or {},
                }
            )
            index += 1
            stepFailed = stepEvidence.get("verify") == "fail" or (
                len(step.actions) > 0 and invalidCount == len(step.actions)
            )
            if stepFailed and replanCount < self._maxReplans:
                replanCount += 1
                newSteps = await self._callPlanner(
                    task,
                    {
                        "first_frame": firstFrame,
                        "failed_step": step.description,
                        "attempt": replanCount,
                    },
                )
                steps = steps[:index] + newSteps
                index += 0  # 新清单从当前位置接续（失败步事实已记，不重跑）

        terminal = await _takeFrame(self._executor, self._terminalTool, "终态取证")
        executedTools = [entry["tool"] for entry in actionResults if not entry.get("invalid")]
        return {
            "task_id": task.task_id,
            "instruction": task.instruction,
            "first_frame": firstFrame,
            "planned_steps": len(stepsDetail),
            "executed_steps": executedSteps,
            "steps_detail": stepsDetail,
            "replan_count": replanCount,
            "replanned": replanCount > 0,
            "action_results": actionResults,
            "action_invalid": invalidTotal,
            "last_action_tool": lastExecuted or self._terminalTool,
            "terminal": terminal,
        }


def runCuaTasks(
    tasks: List[CuaTask],
    episodeFn: EpisodeFn,
    clockFn: Callable[[], float] = time.perf_counter,
    costNote: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """逐任务执行桌面 episode → 判据给分，产出真实聚合指标（P0-② 口径）。

    - episodeFn(task) 同步返回终态证据 dict；异常＝器械故障（infra）；
    - 行级事实保留（0 分 + error 原文、不剔除、不中断），聚合只吃量出来的任务；
    - 空任务库/全量器械故障 ⇒ score=None。
    """
    selected = list(tasks)
    perTask: List[Dict[str, Any]] = []
    for task in selected:
        started = clockFn()
        error: Optional[str] = None
        evidence: Dict[str, Any] = {}
        try:
            outcome = episodeFn(task)
            if hasattr(outcome, "__await__"):
                # 兼容 async episode（真桌面驱动是 async 管线）；同步注入走直返
                import asyncio

                outcome = asyncio.run(outcome)
            evidence = dict(outcome or {})
        except Exception as exc:  # noqa: BLE001 - 故障隔离：事实进 error
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("[cua_eval] 任务执行异常 task=%s: %s", task.task_id, exc)
        finally:
            elapsedMs = (clockFn() - started) * 1000.0

        failureClass = "infra" if error is not None else ""
        passed, score, details = False, 0.0, {}
        if error is None:
            try:
                passed, score, details = task.check(evidence)
            except Exception as exc:  # noqa: BLE001 - 判据故障不掩盖执行事实
                details = {"checker_error": str(exc)}
                failureClass = "infra_checker"
                logger.warning("[cua_eval] 判据异常 task=%s: %s", task.task_id, exc)

        # C3-1 假完成信号（M2 教训）：声明完成但最后一步不是观察面核验动作。
        # 无声明不标；last_action_tool 缺失不臆造判定。
        lastTool = str(evidence.get("last_action_tool") or "")
        doneWithoutVerify = bool(evidence.get("claimed_done")) and (
            lastTool != "" and lastTool not in _CUA_OBSERVATION_TOOLS
        )

        perTask.append(
            {
                "task_id": task.task_id,
                "passed": bool(passed) and error is None,
                "score": round(float(score), _SCORE_DIGITS),
                "failure_class": failureClass,
                "error": error,
                "details": details,
                "latency_ms": round(elapsedMs, 2),
                "action_invalid": int(evidence.get("action_invalid") or 0),
                "replanned": bool(evidence.get("replanned")),
                "done_without_verify": doneWithoutVerify,
            }
        )

    tasksTotal = len(perTask)
    judgedRows = [row for row in perTask if row["failure_class"] == ""]
    scores = [row["score"] for row in judgedRows]
    latencies = [row["latency_ms"] for row in perTask]
    report = {
        "status": "completed",
        "tasks_total": tasksTotal,
        "tasks_judged": len(judgedRows),
        "tasks_correct": sum(1 for row in judgedRows if row["passed"]),
        "tasks_failed": sum(1 for row in judgedRows if not row["passed"]),
        "tasks_infra_failed": tasksTotal - len(judgedRows),
        "action_invalid_total": sum(row["action_invalid"] for row in perTask),
        "done_without_verify_tasks": sum(
            1 for row in perTask if row["done_without_verify"]
        ),
        "score": round(sum(scores) / len(scores), _SCORE_DIGITS) if scores else None,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "per_task": perTask,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
    if costNote is not None:
        report["cost_note"] = dict(costNote)
    return report


def runCuaTasksRepeated(
    tasks: List[CuaTask],
    episodeFn: EpisodeFn,
    repeats: int = 1,
    clockFn: Callable[[], float] = time.perf_counter,
    costNote: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """同任务集 N 轮评测 → 多 run 聚合（C2，OSWorld M5 教训：同任务同配置
    跨 run 翻转，单轮读数把上游非确定采样当确定结论）。

    - 逐轮跑 :func:`runCuaTasks`（口径不变），按 task_id 对齐轮次；
    - 逐任务：每轮得分列表、均值、翻转标记（judged 轮次间通过与否分歧；
      全量 infra＝没量到，不算翻转）、跨轮 invalid/infra 累计；
    - 总览：mean_score、score_std、pass_rate 区间（逐轮通过率 min/max）、
      action_invalid_total；每轮完整报告保留在 ``runs_reports``；
    - ``repeats=1`` 时 ``score``/``tasks_total`` 与单轮 :func:`runCuaTasks`
      同值（零破坏）。
    """
    repeats = max(1, int(repeats))
    runs = [
        runCuaTasks(tasks, episodeFn, clockFn=clockFn,
                    costNote=costNote if i == repeats - 1 else None)
        for i in range(repeats)
    ]

    byTask: Dict[str, List[Dict[str, Any]]] = {}
    for run in runs:
        for row in run["per_task"]:
            byTask.setdefault(row["task_id"], []).append(row)

    perTask: List[Dict[str, Any]] = []
    for taskId, rows in byTask.items():
        scores = [row["score"] for row in rows]
        judgedRows = [row for row in rows if row["failure_class"] == ""]
        flipped = len({row["passed"] for row in judgedRows}) > 1
        perTask.append(
            {
                "task_id": taskId,
                "scores": scores,
                "mean_score": round(sum(scores) / len(scores), _SCORE_DIGITS),
                "flipped": flipped,
                "runs_infra": len(rows) - len(judgedRows),
                "action_invalid": sum(row["action_invalid"] for row in rows),
                "done_without_verify": any(
                    row["done_without_verify"] for row in rows
                ),
                "rows": rows,
            }
        )

    means = [row["mean_score"] for row in perTask]
    meanScore = round(sum(means) / len(means), _SCORE_DIGITS) if means else None
    scoreStd: Optional[float] = None
    if means and repeats > 1:
        mu = sum(means) / len(means)
        scoreStd = round(
            (sum((m - mu) ** 2 for m in means) / len(means)) ** 0.5, _SCORE_DIGITS
        )
    passRates = [
        round(run["tasks_correct"] / run["tasks_judged"], _SCORE_DIGITS)
        for run in runs if run["tasks_judged"] > 0
    ]

    report = {
        "status": "completed",
        "runs": repeats,
        "tasks_total": len(perTask),
        "flipped_tasks": sum(1 for row in perTask if row["flipped"]),
        "score": meanScore,
        "mean_score": meanScore,
        "score_std": scoreStd,
        "pass_rate_min": min(passRates) if passRates else None,
        "pass_rate_max": max(passRates) if passRates else None,
        "action_invalid_total": sum(row["action_invalid"] for row in perTask),
        "done_without_verify_tasks": sum(
            1 for row in perTask for sub in row["rows"] if sub["done_without_verify"]
        ),
        "per_task": perTask,
        "runs_reports": runs,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
    if costNote is not None:
        report["cost_note"] = dict(costNote)
    return report
