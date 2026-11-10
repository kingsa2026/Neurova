# -*- coding: utf-8 -*-
"""覆盖读数（H1，survey §10.2）——任务族×覆盖矩阵与未覆盖族告警。

"覆盖什么"的分母**先定死**（防"覆盖率分母"旧病复发）：期望族集合是
harness 决策档四族 ∪ B2 任务流三问形态的并集，单源从两张注册表取——
分母变更必须改注册表（改 readout 里的手抄集合就是第二份定义）。
告警形态：未覆盖族逐名点名（合成缺族序列 → 告警点名族名）。
"""

from typing import Any, Dict, Iterable, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def expectedFamilies() -> List[str]:
    """覆盖分母的**唯一出处**：harness 决策档族 ∪ 任务流形态。

    两张注册表（eval_harness.EVAL_CASES 的 family 列、task_stream 的
    TASK_STREAM_FORMS）经各自单源读出——本函数不手抄族名。
    """
    families: List[str] = []
    from neurova.evolution.rsi.eval_harness import splitSealedCases

    decision, _sealed = splitSealedCases()
    families.extend(sorted({family for _cid, family, _fn in decision}))
    from neurova.evolution.rsi.task_stream import TASK_STREAM_FORMS

    families.extend(sorted(TASK_STREAM_FORMS))
    # 去重保序
    seen: List[str] = []
    for family in families:
        if family not in seen:
            seen.append(family)
    return seen


def coverageReadout(recent_families: Iterable[str],
                    expected: Optional[List[str]] = None) -> Dict[str, Any]:
    """覆盖矩阵：期望族 × 近期实际覆盖（covered/uncovered 逐名点名）。

    recent_families = 近期评测活动实际触达的族（编排器从 eval outcome 的
    case family 列取）；expected 缺省走 expectedFamilies() 单源。
    """
    expected_set = list(expected) if expected is not None else expectedFamilies()
    covered_set = set(str(f) for f in (recent_families or []))
    covered = [f for f in expected_set if f in covered_set]
    uncovered = [f for f in expected_set if f not in covered_set]
    readout: Dict[str, Any] = {
        "expected": expected_set,
        "covered": covered,
        "uncovered": uncovered,
        "alert": bool(uncovered),
    }
    if uncovered:
        logger.warning("覆盖缺口：族 %s 未被近期评测触达", uncovered)
    return readout
