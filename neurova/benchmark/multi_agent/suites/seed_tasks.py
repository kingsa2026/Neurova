# -*- coding: utf-8 -*-
"""种子任务集（T1 确定性模拟 + T3 量规打样）。

判据为最小切面断言（报告标记/结构），CI 用假 agent 验 harness 管道；
真模型跑（NEUROVA_BENCH_LIVE=1）时同判据即可产出基线报告。
扩充真实任务集时在各自 suites 模块里 registerTask，不在此堆放。
"""
from __future__ import annotations

from typing import Tuple

from neurova.benchmark.multi_agent.tasks import BenchmarkTask, TaskOutcome, registerTask


def _markerChecker(requiredMarkers: Tuple[str, ...], infeasibleMarker: str = ""):
    def _check(outcome: TaskOutcome) -> Tuple[bool, float, dict]:
        text = outcome.report or ""
        if infeasibleMarker:
            declared = infeasibleMarker in text
            return declared, (100.0 if declared else 0.0), {"infeasible_declared": declared}
        missing = [m for m in requiredMarkers if m not in text]
        score = round((len(requiredMarkers) - len(missing)) / max(len(requiredMarkers), 1) * 100, 1)
        return (not missing), score, {"missing_markers": missing}

    return _check


def registerSeedTasks() -> None:
    registerTask(BenchmarkTask(
        task_id="t1-sim-evidence-digest",
        suite="t1_sim",
        prompt="调研主题 X，输出带来源的证据文摘（至少 3 条，每条含来源与量化指标）。",
        check=_markerChecker(("来源《A 报告》", "来源《B 数据》", "来源《C 文档》")),
        description="确定性模拟：证据文摘结构切面",
    ))
    registerTask(BenchmarkTask(
        task_id="t1-sim-infeasible",
        suite="t1_sim",
        prompt="在不提供任何数据的情况下精确预测明年的销售额小数点后两位。",
        check=_markerChecker((), infeasibleMarker="不可行"),
        unsolvable=True,
        description="不可解题：正确声明不可行",
    ))
    registerTask(BenchmarkTask(
        task_id="t3-rubric-exec-summary",
        suite="t3_rubric",
        prompt="撰写一段执行摘要，须含【结论】【依据】【风险】三节。",
        check=_markerChecker(("【结论】", "【依据】", "【风险】")),
        description="量规判分打样：三节结构",
    ))
