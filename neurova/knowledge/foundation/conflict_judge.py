"""冲突判定器（工单 007，设计文档 §5 段4、G03/G04）。

分歧是一等对象而不是静默覆盖：分类、定严重度、给策略、**并留下可读的依据**。
没有依据就不自动裁决——自动错一次的代价比留一条待审高。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

CONFLICT_KINDS: tuple = ("value", "qualifier", "type", "temporal", "cardinality")
RESOLUTION_POLICIES: tuple = (
    "most_recent", "highest_confidence", "credibility_weighted", "keep_both", "manual",
)

_BASE_SEVERITY: Dict[str, float] = {
    "value": 0.60, "qualifier": 0.50, "type": 0.55, "temporal": 0.35, "cardinality": 0.55,
}


class KnowledgeConflictJudge:
    """在同一 (主体, 谓词) 上聚合新旧事实，判三值中的 `contradicts` 分支。"""

    def __init__(self, store: Any, termRegistry: Any = None) -> None:
        self._store = store
        self._registry = termRegistry

    # ── 分类 ──────────────────────────────────────────────────

    def detect(self, subjectLabel: str, predicateTermId: str) -> List[Dict[str, Any]]:
        facts = self._store.candidateFactsForConflict(subjectLabel, predicateTermId)
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for fact in facts:
            groups.setdefault(_qualifierKey(fact), []).append(fact)

        conflicts: List[Dict[str, Any]] = []
        for members in groups.values():
            distinct = {str(m.get("object_term", "")) for m in members}
            if len(distinct) < 2:
                continue
            kind = self._classify(members, qualifierScoped=bool(members[0].get("qualifier")))
            conflicts.append({
                "kind": kind,
                "subject_key": members[0]["subject_key"],
                "predicate_term_id": predicateTermId,
                "member_fact_ids": [m["fact_id"] for m in members],
                "severity": self._severity(kind, members),
                "cross_agent": len({m.get("agent_id") for m in members}) > 1,
            })
        return sorted(conflicts, key=lambda c: (-c["severity"], c["member_fact_ids"][0]))

    def _classify(self, members: List[Dict[str, Any]], qualifierScoped: bool) -> str:
        if any(_hasClosedWindow(m) for m in members) and self._windowsDisjoint(members):
            return "temporal"
        if self._registry is not None:
            cardinality = self._registry.maxCardinality(members[0]["predicate_term_id"])
            if cardinality == 1 and len(members) > 1:
                return "cardinality"
        return "qualifier" if qualifierScoped else "value"

    @staticmethod
    def _windowsDisjoint(members: List[Dict[str, Any]]) -> bool:
        ordered = sorted(members, key=lambda m: (str(m.get("valid_until") or ""), m["fact_id"]))
        for earlier in ordered:
            if not earlier.get("valid_until"):
                continue
            for later in ordered:
                if later is earlier:
                    continue
                boundary = str(later.get("valid_from") or later.get("recorded_at") or "")
                if boundary and str(earlier["valid_until"]) <= boundary:
                    return True
        return False

    @staticmethod
    def _severity(kind: str, members: List[Dict[str, Any]]) -> float:
        score = _BASE_SEVERITY.get(kind, 0.5)
        if all(m.get("evidence_state") == "evidenced" for m in members):
            score += 0.20
        if len({m.get("agent_id") for m in members}) > 1:
            score += 0.10
        return round(min(score, 1.0), 4)

    # ── 策略与依据 ────────────────────────────────────────────

    def decide(self, members: List[Dict[str, Any]]) -> Dict[str, Any]:
        """返回 (policy, basis, winner)。basis 为空即不得自动裁决。"""
        blind = [m for m in members if m.get("evidence_state") != "evidenced"]
        if blind:
            names = ", ".join(
                "%s(evidence_state=%s)" % (m["fact_id"], m.get("evidence_state")) for m in blind
            )
            return {"policy": "manual", "winner": None,
                    "basis": "成员无据可依，不得按通过处理: %s" % names}

        ordered = sorted(members, key=lambda m: (str(m.get("recorded_at") or ""), m["fact_id"]))
        if len({str(m.get("recorded_at") or "") for m in ordered}) > 1:
            winner = ordered[-1]
            return {"policy": "most_recent", "winner": winner["fact_id"],
                    "basis": "按新近裁决：%s（recorded_at=%s）晚于其余成员"
                             % (winner["fact_id"], winner.get("recorded_at"))}

        confidences = {m.get("confidence") for m in members}
        if None not in confidences and len(confidences) > 1:
            winner = max(members, key=lambda m: (float(m["confidence"]), m["fact_id"]))
            return {"policy": "highest_confidence", "winner": winner["fact_id"],
                    "basis": "按置信裁决：%s（confidence=%s）高于其余成员"
                             % (winner["fact_id"], winner.get("confidence"))}

        supports = {int(m.get("assertion_count") or 0) for m in members}
        if len(supports) > 1:
            winner = max(members, key=lambda m: (int(m.get("assertion_count") or 0), m["fact_id"]))
            detail = ", ".join("%s=%s" % (m["fact_id"], m.get("assertion_count")) for m in members)
            return {"policy": "credibility_weighted", "winner": winner["fact_id"],
                    "basis": "断言支持数分胜负（assertion_count %s）" % detail}

        return {"policy": "manual", "winner": None,
                "basis": "新近、置信、断言支持三项均无差异，无区分依据可依"}

    def record(self, subjectLabel: str, predicateTermId: str) -> List[Dict[str, Any]]:
        """检测并成账；可自动裁决的顺手取代败方。重复检测同一组成员不再开新账。"""
        recorded: List[Dict[str, Any]] = []
        for conflict in self.detect(subjectLabel, predicateTermId):
            members = self._store.factsByIds(conflict["member_fact_ids"])
            decision = self.decide(members)
            status = "auto_resolved" if decision["winner"] else "pending"
            conflictId = self._store.insertConflict(
                kind=conflict["kind"],
                subjectKey=conflict["subject_key"],
                predicateTermId=conflict["predicate_term_id"],
                memberFactIds=conflict["member_fact_ids"],
                severity=conflict["severity"],
                recommendedPolicy=decision["policy"],
                policyBasis=decision["basis"],
                status=status,
                winnerFactId=decision["winner"],
            )
            if conflictId is None:
                continue
            if decision["winner"]:
                self._applySupersede(conflict["member_fact_ids"], decision["winner"])
            conflict.update({
                "conflict_id": conflictId, "status": status,
                "recommended_policy": decision["policy"], "policy_basis": decision["basis"],
            })
            recorded.append(conflict)
        return recorded

    def _applySupersede(self, memberFactIds: List[str], winnerId: str) -> None:
        for loser in memberFactIds:
            if loser == winnerId:
                continue
            row = self._store.fact(loser)
            if row and row.get("status") == "active":
                self._store.supersede(winnerId, loser, reason="conflict auto_resolved")


def _qualifierKey(fact: Dict[str, Any]) -> str:
    return json.dumps(fact.get("qualifier") or {}, ensure_ascii=False, sort_keys=True)


def _hasClosedWindow(fact: Dict[str, Any]) -> bool:
    return bool(fact.get("valid_until"))
