# -*- coding: utf-8 -*-
"""I_t 升级派生（A5，survey §10.2）——改进器吃自己的失败史。

pruner 的被拒史（failed_candidates_history，含每条 realized_cost）已在记，
今天没人用它调策略。本模块把它读成**步进档位的淘汰画像**：某档被拒严格占多数
（count > 其余各档最大值 且 count ≥ 3）⇒ 该档从 I_{t+1} 的步进选择里剔除——
同题再提议的步进选择因此确实改变（判据钉住）。淘汰分散/并列 ⇒ 无升级候选
（不硬造变更）；派生来源必须是已注册版本；换版走提案 gate（人工批准），
换版后配对探针重跑、Γ 随条目入账（无证据不许入账）。
"""

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.evolution.rsi.candidate_policy import CandidatePolicy
from neurova.evolution.rsi.recursive_ratchet_pruner import Candidate

logger = get_logger(__name__)

#: 淘汰档认定的最小被拒数（低于此不构成画像）。
MIN_ELIMINATIONS_FOR_TIER = 3


def _ratioOf(candidate: Candidate) -> Optional[float]:
    ratio = (candidate.parameters or {}).get("adjustment_ratio")
    return float(ratio) if isinstance(ratio, (int, float)) else None


def deriveImproverUpgrade(base: CandidatePolicy,
                          failed_history: List[Candidate]) -> Optional[CandidatePolicy]:
    """从被拒史派生 I_{t+1} 候选策略（步进档位剔除形）。

    画像：按 adjustment_ratio 统计被拒次数；某档**严格占多数**
    （count > 其余各档最大值 且 count ≥ MIN_ELIMINATIONS_FOR_TIER）⇒ 剔除。
    空史/分散/并列 ⇒ None（无升级候选——升级必须有画像依据，不硬造变更）。
    """
    counts: Dict[float, int] = {}
    for entry in failed_history or []:
        ratio = _ratioOf(entry)
        if ratio is None:
            continue
        counts[ratio] = counts.get(ratio, 0) + 1
    if not counts:
        return None
    dominant = None
    dominant_count = 0
    for ratio, count in counts.items():
        others_max = max((c for r, c in counts.items() if r != ratio), default=0)
        if count >= MIN_ELIMINATIONS_FOR_TIER and count > others_max:
            if dominant is None or count > dominant_count:
                dominant, dominant_count = ratio, count
    if dominant is None:
        logger.info("被拒史淘汰分散（%s），无占多数档——不派生升级", counts)
        return None
    excluded = sorted(base.STEP_RATIOS)
    excluded = [r for r in excluded if abs(r - dominant) < 1e-9]
    if not excluded:
        return None
    return CandidatePolicy.derived(
        base=base, excluded_ratios=excluded,
        failure_counts={str(k): v for k, v in counts.items()})
