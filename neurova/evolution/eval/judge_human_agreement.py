# -*- coding: utf-8 -*-
"""judge-人工相关性（F2，survey §10.2）——审批动作即标签，零新成本。

Meta-Rewarding 教训（survey §2.3/§7.6）：judge 增益与人工判断的相关性不在
后续轮次持续——"演员偏好增益"与"评测器稳定改善"是不同观测。本模块把
judge-人工相关性逐轮化：人工标注样本**从审批动作自然采集**（approve/reject
即标签，零新成本），滚动一致率呈报，连续塌陷告警。

判据：judge 增益 > 0 且人批 ⇒ 一致；judge 增益 > 0 且人拒 ⇒ 背离（judge 在讨好，人在把关）。pending（未决策）不计入。样本不足（< MIN_DECISIONS）
报 insufficient_data 不硬算。
"""

from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MIN_DECISIONS = 4
#: 一致率告警阈值：低于此＝judge-人工相关性塌陷（暂定值，有样本后另调）。
AGREEMENT_ALERT = 0.5


def judgeHumanAgreement(proposal_dicts: List[Dict[str, Any]], *,
                        min_decisions: int = MIN_DECISIONS,
                        positive_gain: float = 0.0) -> Dict[str, Any]:
    """从提案册读 judge-人工一致率（纯函数；提案 dict 形态＝list_proposals 出街形态）。

    judge 增益取 holdout_after − holdout_before（judge 面的增益读数，B4 两列
    的 judge 列）；人工标签＝status（applied=批准、rejected=否决）。
    """
    agreements: List[bool] = []
    _divergences: List[Dict[str, Any]] = []
    for proposal in proposal_dicts or []:
        status = str(proposal.get("status") or "")
        if status not in ("applied", "rejected"):
            continue  # pending/legacy 不计
        before = proposal.get("holdout_before")
        after = proposal.get("holdout_after")
        if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
            continue
        judge_gain = float(after) - float(before)
        approved = status == "applied"
        if judge_gain > positive_gain:
            agree = approved
        else:
            # judge 面零/负增益：人拒 = 一致（把关节拍对上）
            agree = not approved
        agreements.append(agree)
        if not agree:
            _divergences.append({
                "proposal_id": proposal.get("proposal_id"),
                "judge_gain": round(judge_gain, 4),
                "status": status,
            })
    if len(agreements) < min_decisions:
        return {
            "state": "insufficient_data",
            "score": None,
            "decisions": len(agreements),
            "detail": f"决策样本 {len(agreements)} < {min_decisions}，不硬算",
        }
    rate = sum(1 for a in agreements if a) / len(agreements)
    alert = rate < AGREEMENT_ALERT
    if alert:
        logger.warning("judge-人工一致性塌陷：一致率 %.2f（%d 次背离）",
                       rate, len(_divergences))
    return {
        "state": "measured",
        "score": round(rate, 4),
        "decisions": len(agreements),
        "divergences": _divergences[-5:],
        "alert": alert,
        "threshold": AGREEMENT_ALERT,
    }
