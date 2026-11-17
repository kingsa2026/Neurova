# -*- coding: utf-8 -*-
"""种子任务集（T1 材料归纳/不可解题 + T3 量规打样）。

T1 族不考虚构来源：证据文摘题在提示词内给真实来源材料，任务为"依据给定
材料归纳"；不可解题仍考"诚实声明不可行"。判据为最小切面断言（报告标记/
结构），CI 用假 agent 验 harness 管道；真模型跑（NEUROVA_BENCH_LIVE=1）时
同判据即可产出基线报告。
真实任务集扩充在各自 suites 模块（如 apex_tasks），登记统一走
`suites.registerBuiltinSuites()`（幂等）——本模块只暴露 SEED_TASKS 数据面。
"""
from __future__ import annotations

from typing import Tuple

from neurova.benchmark.multi_agent.tasks import BenchmarkTask, TaskOutcome


def markerChecker(requiredMarkers: Tuple[str, ...], infeasibleMarker: str = ""):
    """切面判据：报告须含全部标记（或不可解题正确声明不可行）。套件共用的单源。"""
    def _check(outcome: TaskOutcome) -> Tuple[bool, float, dict]:
        text = outcome.report or ""
        if infeasibleMarker:
            declared = infeasibleMarker in text
            return declared, (100.0 if declared else 0.0), {"infeasible_declared": declared}
        missing = [m for m in requiredMarkers if m not in text]
        score = round((len(requiredMarkers) - len(missing)) / max(len(requiredMarkers), 1) * 100, 1)
        return (not missing), score, {"missing_markers": missing}

    return _check


SEED_TASKS = (
    # S1-1D T1 重设计：原题让真模型凭空"调研主题 X"再标来源，等于考虚构来源
    # （H-7 真基线实测：真模型要么拒答要么编造）。改为提示词内给真实来源材料，
    # 任务改为"依据给定材料归纳"——考归纳与引用纪律，不考编造。
    BenchmarkTask(
        task_id="t1-sim-evidence-digest",
        suite="t1_sim",
        prompt=(
            "以下是关于主题 X 的三份已核实材料：\n"
            "1. 《A 报告》（2026-11）：指标 X=48，环比 +6；\n"
            "2. 《B 数据》（2026-10）：指标 Y=3.2，覆盖率 87%；\n"
            "3. 《C 文档》（2026-09）：指标 Z=12%，样本量 4200。\n"
            "任务：只依据上述给定材料归纳证据文摘（至少 3 条，每条含来源与量化指标），"
            "不得引用材料之外的任何来源。"
        ),
        check=markerChecker(("来源《A 报告》", "来源《B 数据》", "来源《C 文档》")),
        description="依据给定材料归纳：证据文摘结构切面（不考虚构来源）",
    ),
    BenchmarkTask(
        task_id="t1-sim-infeasible",
        suite="t1_sim",
        prompt="在不提供任何数据的情况下精确预测明年的销售额小数点后两位。",
        check=markerChecker((), infeasibleMarker="不可行"),
        unsolvable=True,
        description="不可解题：正确声明不可行",
    ),
    BenchmarkTask(
        task_id="t3-rubric-exec-summary",
        suite="t3_rubric",
        prompt="撰写一段执行摘要，须含【结论】【依据】【风险】三节。",
        check=markerChecker(("【结论】", "【依据】", "【风险】")),
        description="量规判分打样：三节结构",
    ),
)
