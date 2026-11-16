# -*- coding: utf-8 -*-
"""评测任务注册表：任务 = 提示词 + 切面判据（check），判定器随任务注入，harness 不伪造分数。"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

_LOCK = threading.RLock()
_TASKS: Dict[str, "BenchmarkTask"] = {}

CheckFn = Callable[["TaskOutcome"], Tuple[bool, float, dict]]


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
