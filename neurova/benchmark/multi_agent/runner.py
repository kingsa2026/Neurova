# -*- coding: utf-8 -*-
"""评测执行器：同一任务集以 solo / swarm 两模式跑，swarm 走真 SwarmManager 链路（不绕治理闸）。

- agent 解析单源复用 `neurova.api.endpoints.get_agent_instance`（与蜂群生产链路同一注册表）；
- 逐任务故障隔离：单任务异常/治理拒绝计为该任务失败事实，不中断整个 run；
- token 读数 best-effort（S1-1A）：solo/swarm 都从 loop 回传（usage_accounting
  增量）取 token 与 LLM 步数；工具数 solo 取执行链 tool_messages 扁平记录、
  swarm 优先聚合 P3-2 span trace。缺失维度如实填 0，不伪造成本数据；
- S1-1C taskIsolatedMemory：solo 模式逐任务派生独立会话命名空间，防跨任务
  记忆串扰污染对照（swarm 的 member 会话本就逐 run 独立，无需另做）。
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from neurova.agent.effort_inference import resolveQueryEffort
from neurova.benchmark.multi_agent.tasks import BenchmarkTask, TaskOutcome, getTask
from neurova.core.logger import get_logger

logger = get_logger(__name__)

MODES = ("solo", "swarm")


def _extractText(result) -> str:
    """从执行结果提取报告正文（判据的**唯一输入**）。

    卫生纪律（真模型基线实测抓到的假通过根因）：dict 没有正文键时**如实返回
    空串**，不得回退 `str(result)`——那会把 reasoning/内部字段的 repr 当"报告"
    喂给判据（实测：某任务正文为空，量规标记却匹配在 reasoning 的 repr 里，
    判了假通过）。没有正文 = 判据按失败计，这才是诚实形态。
    """
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("report", "text", "content", "reply"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""
    if hasattr(result, "content"):
        return str(result.content)
    return ""


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


def _usageTotalSnapshot() -> dict:
    """usage_accounting 进程级累计（loop 回传单源：multi_model_client 入账）。

    记账面不可用时如实按零值记录——缺失读数不伪装，也不阻断评测。
    """
    try:
        from neurova.core.usage_accounting import get_usage_accounting

        total = (get_usage_accounting().snapshot() or {}).get("total") or {}
        return {
            "calls": int(total.get("calls") or 0),
            "promptTokens": int(total.get("prompt_tokens") or 0),
            "completionTokens": int(total.get("completion_tokens") or 0),
            "totalTokens": int(total.get("total_tokens") or 0),
        }
    except Exception as exc:  # noqa: BLE001 - 记账故障按零值如实记录
        logger.debug("[bench] usage 快照读取失败（按 0 记）: %s", exc)
        return {"calls": 0, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0}


def _usageDelta(before: dict, after: dict) -> dict:
    """任务执行前后的累计差 = 本任务的真实用量（含步数 = LLM 调用次数增量）。"""
    return {key: max(int(after.get(key, 0)) - int(before.get(key, 0)), 0) for key in before}


def _toolFactsFromResult(result) -> Tuple[int, List[str]]:
    """solo 工具事实源：执行链落好的 tool_messages 扁平记录。

    type=tool_call 的条目才是一次调用（tool_result 是配对结果，不计）。
    """
    if not isinstance(result, dict):
        return 0, []
    messages = result.get("tool_messages")
    if not isinstance(messages, list):
        return 0, []
    names = [
        str(m.get("tool_name") or "")
        for m in messages
        if isinstance(m, dict) and m.get("type") == "tool_call" and m.get("tool_name")
    ]
    return len(names), names


def _toolFactsFromTrace(traceId: str) -> Tuple[int, List[str]]:
    """swarm 工具事实源：优先聚合 P3-2 的 span trace（tool_call_start 事件）。

    不往 H-4 事件账本新增工具级事件（账本纪律：正文与高频细节不进账本）。
    轨迹缺失/关闭时如实返回 0 与空序列，不伪造轨迹事实。
    """
    if not traceId:
        return 0, []
    try:
        from neurova.core.trace_recorder import get_trajectory_recorder

        trace = get_trajectory_recorder().load_trace(str(traceId))
    except Exception as exc:  # noqa: BLE001 - 轨迹面故障不阻断评测
        logger.debug("[bench] 轨迹读取失败 trace=%s: %s", traceId, exc)
        return 0, []
    if trace is None:
        return 0, []
    calls, names = 0, []
    for span in trace.spans.values():
        for event in span.events:
            etype = getattr(event.event_type, "value", str(event.event_type))
            if etype != "tool_call_start":
                continue
            calls += 1
            name = str((event.data or {}).get("tool_name") or "")
            if name:
                names.append(name)
    return calls, names


class BenchRunner:
    """逐任务双模式执行器。"""

    def __init__(self, agent_id: Optional[str] = None, workspace: str = "",
                 taskIsolatedMemory: bool = True):
        self.agent_id = agent_id
        self.workspace = workspace
        # S1-1C：正式对比默认开启记忆隔离（报告会注明是否隔离）。
        self.taskIsolatedMemory = bool(taskIsolatedMemory)

    def _resolveAgent(self):
        from neurova.api.endpoints import get_agent_instance

        return get_agent_instance(self.agent_id)

    def _isolatedSessionId(self, task: BenchmarkTask) -> str:
        """逐任务独立会话命名空间：会话历史/记忆写入互不可见。"""
        return f"bench_{task.task_id}_{uuid.uuid4().hex[:8]}"

    async def runTask(self, task: BenchmarkTask, mode: str) -> dict:
        started = time.time()
        report, error, tokens, subagent_id = "", None, None, ""
        rejected, rejection_code = False, ""
        usageFacts = {"calls": 0, "promptTokens": 0, "completionTokens": 0, "totalTokens": 0}
        toolCalls, toolsUsed, trajectorySource = 0, [], ""
        try:
            if mode == "solo":
                agent = self._resolveAgent()
                if agent is None:
                    raise RuntimeError(f"评测 agent 不可用: {self.agent_id}")
                before = _usageTotalSnapshot()
                # S1-1C：隔离模式给每任务一个全新会话键——记忆/历史从干净上下文起步
                if self.taskIsolatedMemory:
                    result = agent.chat(task.prompt, session_id=self._isolatedSessionId(task))
                else:
                    result = agent.chat(task.prompt)
                if hasattr(result, "__await__"):
                    result = await result
                usageFacts = _usageDelta(before, _usageTotalSnapshot())
                toolCalls, toolsUsed = _toolFactsFromResult(result)
                trajectorySource = "tool_messages"
                report, tokens = _extractText(result), _extractTokens(result)
                error = _extractError(result)
            elif mode == "swarm":
                from neurova.agent.swarm import get_swarm_manager

                before = _usageTotalSnapshot()
                result = await get_swarm_manager().spawn(
                    task=task.prompt, agent_id=self.agent_id, origin="benchmark"
                )
                usageFacts = _usageDelta(before, _usageTotalSnapshot())
                toolCalls, toolsUsed = _toolFactsFromTrace(str((result or {}).get("trace_id") or ""))
                trajectorySource = "span_trace"
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
        # P3-3：思考档位变量（effort_inference 单源）——逐任务随事实记录，报告按档聚合
        effort, effortSource = resolveQueryEffort(task.prompt)
        outcome = TaskOutcome(
            task_id=task.task_id,
            mode=mode,
            report=report,
            error=error,
            rejected=rejected,
            rejection_code=rejection_code,
            subagent_id=subagent_id,
            workspace=self.workspace,
            usage={
                "promptTokens": usageFacts["promptTokens"],
                "completionTokens": usageFacts["completionTokens"],
                "totalTokens": usageFacts["totalTokens"],
                "elapsedSeconds": elapsed,
                "steps": usageFacts["calls"],
                "toolCalls": toolCalls,
            },
            trajectory={"toolsUsed": toolsUsed, "source": trajectorySource},
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
            "effort": effort,
            "effort_source": effortSource,
            "report_snippet": report[:400],
            "usage": dict(outcome.usage),
            "trajectory": dict(outcome.trajectory),
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
                                "report_snippet": "", "suite": "",
                                "usage": {}, "trajectory": {}})
                continue
            for mode in modes:
                results.append(await self.runTask(task, mode=mode))
        return results

    async def runAll(self, modes: Sequence[str] = MODES) -> List[dict]:
        from neurova.benchmark.multi_agent.suites import registerBuiltinSuites
        from neurova.benchmark.multi_agent.tasks import listTasks

        # P3-3：评测入口统一登记内置任务集（幂等）——修掉"种子任务零调用方"的接线断点
        registerBuiltinSuites()
        return await self.runTasks([t.task_id for t in listTasks()], modes=modes)

    async def runAllWithReport(self, modes: Sequence[str] = MODES, save: bool = True) -> dict:
        """跑全任务集并产出结构化报告（S1-1E 只读端点的数据生产点）。

        save=True 时原子落盘到数据根 `benchmark/multi_agent/`（report.saveReport），
        报告自带 report_id/report_path 与 task_isolated_memory 注记——只读端点
        直接读这份落盘，不建第二套存储。
        """
        from neurova.benchmark.multi_agent.metrics import aggregate, compare
        from neurova.benchmark.multi_agent.report import buildReport, defaultReportPath, saveReport

        results = await self.runAll(modes=modes)
        report = buildReport(
            results, aggregate(results), compare(results),
            taskIsolatedMemory=self.taskIsolatedMemory,
        )
        if save:
            path = defaultReportPath()
            report["report_id"] = Path(path).stem
            report["report_path"] = path
            saveReport(report, path)
        return report
