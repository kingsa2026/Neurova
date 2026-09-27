"""置信度聚合（工单 009，G11、设计文档 §5 段5）。

定义式必须写清它**不是**什么：本数回答"该事实被多少独立来源、以何种异构程度支持"，
**不等于真值度量**——它不看内容对不对，只看支持结构。
因此：无断言即 None（配 `unevidenced`），永不给 1.0，被矛盾即扣分。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_SOURCE_BASE = {0: None, 1: 0.45, 2: 0.60, 3: 0.70}
_MULTI_SOURCE_BASE = 0.80
_HETEROGENEOUS_BONUS = 0.10
_CONTRADICTION_PENALTY = 0.25
_CEILING = 0.95
_FLOOR = 0.05

_DEFINITION = (
    "confidence = 独立来源数基线（1→0.45 / 2→0.60 / 3→0.70 / ≥4→0.80）"
    " + 异构来源种类 ≥2 加 0.10"
    " - 被标记矛盾扣 0.25，上下界 [%.2f, %.2f]；无断言则为 NULL。"
    "该数不等于真值度量，只描述支持结构。" % (_FLOOR, _CEILING)
)


class ConfidenceAggregator:
    """把断言集合折算成一个可读、可重放、可追责的置信数。"""

    def __init__(self, store: Any = None) -> None:
        self._store = store

    @staticmethod
    def definition() -> str:
        return _DEFINITION

    def aggregate(self, fact: Dict[str, Any], assertions: List[Dict[str, Any]]) -> Dict[str, Any]:
        sources = {(str(a.get("actor_type")), str(a.get("actor_id"))) for a in assertions}
        if not sources:
            return {"confidence": None, "evidence_state": "unevidenced",
                    "basis": "无任何断言，置信度无依据可依（NULL，不是低分）"}

        confidence = _SOURCE_BASE.get(len(sources), _MULTI_SOURCE_BASE)
        basis = ["独立来源 %d 个" % len(sources)]

        kinds = {str(a.get("actor_type")) for a in assertions}
        if len(kinds) >= 2:
            confidence += _HETEROGENEOUS_BONUS
            basis.append("来源种类 %d 种异构(+%.2f)" % (len(kinds), _HETEROGENEOUS_BONUS))

        # 曾有一项"有现场可回放 +0.05"，判据是 `source_turn_id` 非空。该列由咽喉
        # 兜底成 `entry:<kid>`（条目身份，见 `admission.py` 的叙述记录分支），
        # 于是任何写法都拿这 0.05、任何缺证都扣不到它 —— 一个不携带信息的恒真加分。
        # 它比没有加分更坏：下游按分档映射注入优先级时会被整体抬高一档。
        # 换真实来源语义要另立项（该列另有三处读者），故先摘掉，不在此处补判据。

        contradicted = fact.get("contradicted_by") or []
        if contradicted:
            confidence -= _CONTRADICTION_PENALTY
            basis.append("被标记矛盾 %d 处(-%.2f)" % (len(contradicted), _CONTRADICTION_PENALTY))

        confidence = round(max(_FLOOR, min(_CEILING, confidence)), 4)
        return {"confidence": confidence, "evidence_state": "evidenced",
                "basis": "；".join(basis) + "；上限 %.2f，本数不等于真值度量" % _CEILING}

    def apply(self, factId: str) -> Dict[str, Any]:
        """读实况回写——置信度不靠增量维护，避免多写路径把它跑偏。"""
        if self._store is None:
            raise RuntimeError("apply() 需要注入 store；纯计算请改用 aggregate()")
        fact = self._store.fact(factId)
        if fact is None:
            raise LookupError("事实不存在: %s" % factId)
        verdict = self.aggregate(fact, self._store.assertions(factId))
        self._store.setConfidence(factId, verdict["confidence"], verdict["evidence_state"])
        return verdict
