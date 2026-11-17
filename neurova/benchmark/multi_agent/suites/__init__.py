# -*- coding: utf-8 -*-
"""评测任务集套件：seed_tasks（harness 自证 + 基线打样）+ apex_tasks（P3-3 财务/分析量规族）。

登记统一走 `registerBuiltinSuites()`（幂等：已登记的 task_id 跳过，重复调用不翻倍）。
"""
from __future__ import annotations

from neurova.benchmark.multi_agent.suites.apex_tasks import APEX_TASKS
from neurova.benchmark.multi_agent.suites.seed_tasks import SEED_TASKS
from neurova.benchmark.multi_agent.tasks import getTask, registerTask


def registerBuiltinSuites() -> None:
    """登记全部内置任务集（幂等）。评测入口（BenchRunner.runAll）统一调用。"""
    for task in (*SEED_TASKS, *APEX_TASKS):
        if getTask(task.task_id) is None:
            registerTask(task)


__all__ = ["registerBuiltinSuites"]
