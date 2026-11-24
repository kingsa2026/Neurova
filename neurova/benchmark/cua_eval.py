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
    "ToolExecutorEpisodeAdapter",
    "runCuaTasks",
]

CheckFn = Callable[[Dict[str, Any]], Tuple[bool, float, dict]]
EpisodeFn = Callable[[Any], Dict[str, Any]]
_SCORE_DIGITS = 6


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
        results: List[Dict[str, Any]] = []
        for step in script:
            tool = str(step.get("tool") or "")
            params = dict(step.get("params") or {})
            result = await self._executor.execute(tool, params)
            results.append({"tool": tool, "result": result})
            if _looksBlocked(result):
                raise CuaInfraError(f"动作 {tool} 被环境拒绝/失败: {_firstError(result)}")
        terminal = await self._executor.execute(self._terminalTool, {})
        if _looksBlocked(terminal):
            raise CuaInfraError(
                f"终态取证 {self._terminalTool} 失败: {_firstError(terminal)}"
            )
        return {
            "task_id": task.task_id,
            "instruction": task.instruction,
            "action_results": results,
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

        perTask.append(
            {
                "task_id": task.task_id,
                "passed": bool(passed) and error is None,
                "score": round(float(score), _SCORE_DIGITS),
                "failure_class": failureClass,
                "error": error,
                "details": details,
                "latency_ms": round(elapsedMs, 2),
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
        "score": round(sum(scores) / len(scores), _SCORE_DIGITS) if scores else None,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "per_task": perTask,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }
    if costNote is not None:
        report["cost_note"] = dict(costNote)
    return report
