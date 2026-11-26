# -*- coding: utf-8 -*-
"""computer_use 工具描述面的 EvalCase 立案（C5，先 case 后修）。

subject：computer_type 工具描述（``builtin_tools._BUILTIN_SCHEMAS``，模型
可见文本）。M4 教训（OSWorld 子集 50：f918266a 75 步逐字符敲代码、c288e301
15 步 typewrite 长命令）——type_text 被用于长文本输入，需要把"长文本改用
computer_paste"的引导写进描述。import 即注册（与 evolution_cases 同模式）。
"""

from __future__ import annotations

from typing import List

from neurova.benchmark.suite_eval import (
    EvalCase,
    markersPresent,
    registerEvalCase,
)

#: case 归属 suite（与首批 model-visible-text-v1 同 suite）。
CASE_SUITE_ID = "model-visible-text-v1"

#: case 出处：OSWorld 失败分析 M4（事故来源）。
CASE_SOURCE = {
    "kind": "incident",
    "ref": "osworld-failure-analysis-2026-11-25 M4（逐字符敲长文本耗尽步数）",
}

#: 被守卫的模型可见文本 subject_id。
SUBJECT_COMPUTER_TYPE_DESCRIPTION = "computer_type_description"

#: computer_type 描述须含的引导标记（长文本 → computer_paste）。
_TYPE_GUIDANCE_MARKERS = ("长文本", "computer_paste")

_registered = False


def _computerTypeGuidanceCheck(answer: str):
    return markersPresent(_TYPE_GUIDANCE_MARKERS)(answer)


def computerUseCases() -> List[EvalCase]:
    return [
        EvalCase(
            case_id="computer-type-paste-guidance-v1",
            suite_id=CASE_SUITE_ID,
            prompt="computer_type 工具适合输入什么？长文本应该用什么工具？",
            check=_computerTypeGuidanceCheck,
            subject_id=SUBJECT_COMPUTER_TYPE_DESCRIPTION,
            source=dict(CASE_SOURCE),
        ),
    ]


def registerComputerUseCases() -> None:
    """注册 computer_use 描述面 case（幂等，可安全重复调用）。"""
    global _registered
    if _registered:
        return
    for case in computerUseCases():
        registerEvalCase(case)
    _registered = True
