"""事实血缘视图（工单 024，G01 的读面）。

一跳一跳拼出"这条说法谁说的、经哪条管线、依据什么原始陈述"，推导事实再往前提走一层，
直到落在**原始陈述文本**上——血缘查看器与 Turtle 导出都吃这一份，不再各拼一套。

缺维必须显式：`missing` 列的是"这一维没依据"（没有断言 / 断言没挂活动 / 活动没记介质），
不是"查过了是空的"。两者混成一个空数组，读的人就会把"没溯源"读成"溯过源、没来源"。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_MISSING_LABELS = {
    "assertions": "assertions",
    "activity": "activity",
    "medium": "medium_ref",
    "derivation": "derivation",
}


class FactLineageView:
    """按 fact_id 展开血缘。只读，不写任何账。"""

    def __init__(self, store: Any) -> None:
        self._store = store

    def trace(self, factId: str) -> Optional[Dict[str, Any]]:
        fact = self._store.fact(factId)
        if fact is None:
            return None
        hops: List[Dict[str, Any]] = [self._assertionHop(row)
                                      for row in self._store.lineageRows(factId)]
        derivation = self._derivationOf(factId)
        if derivation:
            hops.append(derivation)
        return {
            "fact_id": factId,
            "subject_key": fact.get("subject_key"),
            "subject_label": fact.get("canonical_label") or "",
            "predicate": fact.get("predicate_term_id"),
            "object_term": fact.get("object_term"),
            "record_kind": fact.get("record_kind"),
            "status": fact.get("status"),
            "recorded_at": fact.get("recorded_at"),
            "qualifier": fact.get("qualifier") or {},
            "confidence": fact.get("confidence"),
            "hops": hops,
            "derivation": (derivation or {}).get("rule") and {
                "rule_id": derivation["rule"]["rule_id"],
                "rule_version": derivation["rule"]["version"],
                "stratum": derivation["rule"]["stratification_level"],
            } or None,
            "missing": self._missingOf(hops, derivation),
            "provenance_state": "evidenced" if hops else "unevidenced",
        }

    # ── 跳 ────────────────────────────────────────────────────

    def _assertionHop(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "kind": "assertion",
            "assertion_id": row.get("assertion_id"),
            "actor_type": row.get("actor_type"),
            "actor_id": row.get("actor_id"),
            "medium_ref": row.get("medium_ref") or "",
            "statement_text": row.get("statement_text") or "",
            "asserted_at": row.get("asserted_at"),
            "activity_id": row.get("activity_id") or "",
            "activity_kind": row.get("activity_kind") or "",
            "activity_basis": row.get("activity_basis") or "",
            "seq": int(row.get("seq") or 0),
            "digest": row.get("digest") or "",
        }

    def _derivationOf(self, factId: str) -> Optional[Dict[str, Any]]:
        """推导事实 ⇒ 规则 + 前提；每条前提再带上它自己的原始陈述文本。

        只走一层是刻意的：前提若又是推导来的，它自己的 `trace()` 会接着展开，
        查看器按需再请求——一次调用把整棵推导树拉平，读数会大到没法看。
        """
        edges = self._store._derivationLedger.premisesOf(factId)
        if not edges:
            return None
        ruleIds = sorted({e["rule_id"] for e in edges})
        premises = []
        for premiseId in sorted({e["premise_fact_id"] for e in edges}):
            premise = self._store.fact(premiseId) or {}
            premises.append({
                "fact_id": premiseId,
                "subject_label": premise.get("canonical_label") or "",
                "predicate": premise.get("predicate_term_id"),
                "object_term": premise.get("object_term"),
                "statement_texts": [str(a.get("statement_text") or "")
                                    for a in self._store.lineageRows(premiseId)],
            })
        rules = self._rulesById()
        return {
            "kind": "derivation",
            "rule": rules.get(ruleIds[0]) if ruleIds else None,
            "rule_ids": ruleIds,
            "premises": premises,
        }

    def _rulesById(self) -> Dict[str, Any]:
        try:
            from ..ontology.rule_engine import ForwardChainingEngine

            return {r["rule_id"]: r for r in ForwardChainingEngine(self._store).rules()}
        except Exception:  # noqa: BLE001 - 没装规则引擎时推导跳仍要能读前提
            return {}

    # ── 缺失维 ────────────────────────────────────────────────

    @staticmethod
    def _missingOf(hops: List[Dict[str, Any]], derivation: Optional[Dict[str, Any]]) -> List[str]:
        assertionHops = [h for h in hops if h["kind"] == "assertion"]
        missing: List[str] = []
        if not assertionHops and not derivation:
            missing.append(_MISSING_LABELS["assertions"])
        if assertionHops and any(not h["activity_id"] for h in assertionHops):
            missing.append(_MISSING_LABELS["activity"])
        if assertionHops and any(not h["medium_ref"] for h in assertionHops):
            missing.append(_MISSING_LABELS["medium"])
        if derivation and any(not p["statement_texts"] for p in derivation["premises"]):
            missing.append("premise_statements")
        return missing

    # ── 查推导结论 ────────────────────────────────────────────

    def findDerivedBy(self, store: Any, ruleId: str) -> Optional[str]:
        """按规则 id 找一条推导结论（读面与用例都靠它定位，不靠内部 id 猜）。"""
        with store._lock:
            row = store._conn.execute(
                "SELECT derived_fact_id FROM knowledge_derivation_edges"
                " WHERE rule_id = ? ORDER BY derived_fact_id LIMIT 1", (ruleId,)).fetchone()
        return row["derived_fact_id"] if row else None
