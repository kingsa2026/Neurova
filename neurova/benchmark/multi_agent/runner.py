# -*- coding: utf-8 -*-
"""评测执行器：同一任务集以 solo / swarm 两模式跑，swarm 走真 SwarmManager 链路（不绕治理闸）。

- agent 解析单源复用 `neurova.api.endpoints.get_agent_instance`（与蜂群生产链路同一注册表）；
- 逐任务故障隔离：单任务异常/治理拒绝计为该任务失败事实，不中断整个 run；
- token 读数 best-effort：结果携带 usage/tokens 则记录，缺失记 None（不伪造成本数据）。
"""
from __future__ import annotations

import time
from typing import List, Optional, Sequence

from neurova.benchmark.multi_agent.tasks import BenchmarkTask, TaskOutcome, getTask
from neurova.core.logger import get_logger

logger = get_logger(__name__)

MODES = ("solo", "swarm")


def _extractText(result) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("report", "text", "content", "reply"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return str(result)


def _extractTokens(result) -> Optional[int]:
    if not isinstance(result, dict):
        return None
    usage = result.get("usage")
    if isinstance(usage, dict):
        for key in ("total_tokens", "totalTokens"):
            if isinstance(usage.get(key), (int, float)):
                return int(usage[key])
    for key in ("tokens", "total_tokens"):
        if isinstance(result.get(key), (int, float)):
            return int(result[key])
    return None


def _extractError(result) -> Optional[str]:
    if not isinstance(result, dict):
        return None
    if result.get("error"):
        return str(result["error"])
    rejection = result.get("rejection")
    if isinstance(rejection, dict):
        return f"swarm_rejection:{rejection.get('code', 'unknown')}:{rejection.get('message', '')}"
    return None


class BenchRunner:
    """逐任务双模式执行器。"""

    def __init__(self, agent_id: Optional[str] = None, workspace: str = ""):
        self.agent_id = agent_id
        self.workspace = workspace

    def _resolveAgent(self):
        from neurova.api.endpoints import get_agent_instance

        return get_agent_instance(self.agent_id)

    async def runTask(self, task: BenchmarkTask, mode: str) -> dict:
        started = time.time()
        report, error, tokens, subagent_id = "", None, None, ""
        rejected, rejection_code = False, ""
        try:
            if mode == "solo":
                agent = self._resolveAgent()
                if agent is None:
                    raise RuntimeError(f"评测 agent 不可用: {self.agent_id}")
                result = agent.chat(task.prompt)
                if hasattr(result, "__await__"):
                    result = await result
                report, tokens = _extractText(result), _extractTokens(result)
                error = _extractError(result)
            elif mode == "swarm":
                from neurova.agent.swarm import get_swarm_manager

                result = await get_swarm_manager().spawn(
                    task=task.prompt, agent_id=self.agent_id, origin="benchmark"
                )
                report = _extractText(result)
                tokens = _extractTokens(result)
                error = _extractError(result)
                rejected = bool(result.get("rejected"))
                rejection_code = str((result.get("rejection") or {}).get("code", ""))
                subagent_id = str(result.get("subagent_id", ""))
            else:
                raise ValueError(f"未知评测模式: {mode}")
        except Exception as exc:  # noqa: BLE001 - 单任务故障隔离，事实进 error
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("[bench] 任务执行异常 task=%s mode=%s: %s", task.task_id, mode, exc)

        elapsed = round(time.time() - started, 3)
        outcome = TaskOutcome(
            task_id=task.task_id,
            mode=mode,
            report=report,
            error=error,
            rejected=rejected,
            rejection_code=rejection_code,
            subagent_id=subagent_id,
            workspace=self.workspace,
        )
        try:
            passed, score, details = task.check(outcome)
        except Exception as exc:  # noqa: BLE001 - 判据故障不掩盖执行事实
            passed, score, details = False, 0.0, {"checker_error": str(exc)}

        return {
            "task_id": task.task_id,
            "suite": task.suite,
            "mode": mode,
            "unsolvable": task.unsolvable,
            "passed": bool(passed) and not rejected and not error,
            "score": float(score),
            "details": details,
            "error": error,
            "rejected": rejected,
            "rejection_code": rejection_code,
            "subagent_id": subagent_id,
            "elapsed_seconds": elapsed,
            "tokens": tokens,
            "report_snippet": report[:400],
        }

    async def runTasks(self, task_ids: Sequence[str], modes: Sequence[str] = MODES) -> List[dict]:
        results: List[dict] = []
        for task_id in task_ids:
            task = getTask(task_id)
            if task is None:
                results.append({"task_id": task_id, "mode": "unknown", "passed": False,
                                "score": 0.0, "error": "task_not_registered", "details": {},
                                "unsolvable": False, "rejected": False, "rejection_code": "",
                                "subagent_id": "", "elapsed_seconds": 0.0, "tokens": None,
                                "report_snippet": "", "suite": ""})
                continue
            for mode in modes:
                results.append(await self.runTask(task, mode=mode))
        return results

    async def runAll(self, modes: Sequence[str] = MODES) -> List[dict]:
        from neurova.benchmark.multi_agent.tasks import listTasks

        return await self.runTasks([t.task_id for t in listTasks()], modes=modes)
