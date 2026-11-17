# -*- coding: utf-8 -*-
"""评测任务注册表：任务 = 提示词 + 切面判据（check），判定器随任务注入，harness 不伪造分数。"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

_LOCK = threading.RLock()
_TASKS: Dict[str, "BenchmarkTask"] = {}

CheckFn = Callable[["TaskOutcome"], Tuple[bool, float, dict]]


#: usage 字段的规范键集（S1-1A）。camelCase 与报告/前端列名对齐；
#: mock 桩填 0，真模型从 loop 回传（usage_accounting 增量）与轨迹 span 聚合取真值。
USAGE_KEYS = (
    "promptTokens",
    "completionTokens",
    "totalTokens",
    "elapsedSeconds",
    "steps",
    "toolCalls",
)


@dataclass
class TaskOutcome:
    """判据的输入：一次任务执行的事实（harness 只提供事实，判据自行裁定）。"""

    task_id: str
    mode: str  # solo | swarm
    report: str = ""
    error: Optional[str] = None
    rejected: bool = False  # swarm 治理闸结构化拒绝
    rejection_code: str = ""
    subagent_id: str = ""
    workspace: str = ""
    metadata: dict = field(default_factory=dict)
    # S1-1A：token/耗时/步数/工具数事实。键集见 USAGE_KEYS；缺失维度由
    # 判据按 0 处理（mock 桩），不伪造成本数据。
    usage: dict = field(default_factory=dict)
    # S1-1B：轨迹事实（toolsUsed 工具序列等）。数据源优先复用 P3-2 的
    # span trace 与 agent_runs 台账计数，不往 H-4 事件账本新增工具级事件。
    trajectory: dict = field(default_factory=dict)


@dataclass
class BenchmarkTask:
    task_id: str
    suite: str  # t1_sim | t2_repo | t3_rubric
    prompt: str
    check: CheckFn
    unsolvable: bool = False  # 不可解题：正确声明不可行才得分（防"永远尝试"刷分）
    description: str = ""


def registerTask(task: BenchmarkTask) -> None:
    with _LOCK:
        if task.task_id in _TASKS:
            raise ValueError(f"评测任务已注册: {task.task_id}")
        if not callable(task.check):
            raise ValueError(f"评测任务缺少判据: {task.task_id}")
        _TASKS[task.task_id] = task


def getTask(task_id: str) -> Optional[BenchmarkTask]:
    with _LOCK:
        return _TASKS.get(task_id)


def listTasks(suite: Optional[str] = None) -> List[BenchmarkTask]:
    with _LOCK:
        tasks = list(_TASKS.values())
    if suite:
        tasks = [t for t in tasks if t.suite == suite]
    return sorted(tasks, key=lambda t: t.task_id)


def clearTasks() -> None:
    with _LOCK:
        _TASKS.clear()


def expect_trajectory(
    maxSteps: Optional[int] = None,
    maxToolCalls: Optional[int] = None,
    allowedTools: Optional[Sequence[str]] = None,
    base: Optional[CheckFn] = None,
) -> CheckFn:
    """S1-1B 轨迹效率判据（DA 评测 I-1）：在切面判据之上叠加轨迹预算约束。

    - maxSteps：LLM 调用步数上限（usage.steps，loop 回传 calls 增量）；
    - maxToolCalls：工具调用次数上限（usage.toolCalls）；
    - allowedTools：工具白名单（trajectory.toolsUsed 的每一项都必须在册）；
    - base：被包裹的基础切面判据（如 markerChecker）。合成语义＝基础判据
      与轨迹约束**都**通过才通过；轨迹违例一票否决（分数归 0），details 带
      `trajectory` 子项写明违反了哪条。base 缺省时退化为纯轨迹判据。

    数据源是 TaskOutcome.usage / trajectory 事实（harness 回传），判据不做任何
    执行期插桩——禁止往 H-4 事件账本新增工具级事件。
    """

    def _check(outcome: TaskOutcome) -> Tuple[bool, float, dict]:
        usage = outcome.usage or {}
        trajectory = outcome.trajectory or {}
        steps = usage.get("steps") or 0
        toolCalls = usage.get("toolCalls") or 0
        toolsUsed = list(trajectory.get("toolsUsed") or [])

        violations: List[str] = []
        if maxSteps is not None and steps > maxSteps:
            violations.append(f"steps {steps} 超过预算 maxSteps {maxSteps}")
        if maxToolCalls is not None and toolCalls > maxToolCalls:
            violations.append(f"toolCalls {toolCalls} 超过预算 maxToolCalls {maxToolCalls}")
        if allowedTools is not None:
            allowed = set(allowedTools)
            disallowed = sorted({t for t in toolsUsed if t not in allowed})
            if disallowed:
                violations.append(f"使用白名单外工具: {disallowed}")

        trajectoryOk = not violations
        trajectoryDetails = {
            "violations": violations,
            "maxSteps": maxSteps,
            "maxToolCalls": maxToolCalls,
            "allowedTools": list(allowedTools) if allowedTools is not None else None,
            "steps": steps,
            "toolCalls": toolCalls,
            "toolsUsed": toolsUsed,
        }

        if base is None:
            return trajectoryOk, (100.0 if trajectoryOk else 0.0), trajectoryDetails

        baseOk, baseScore, baseDetails = base(outcome)
        passed = bool(baseOk) and trajectoryOk
        score = float(baseScore) if trajectoryOk else 0.0
        details = dict(baseDetails or {})
        details["trajectory"] = trajectoryDetails
        return passed, score, details

    return _check
