"""本体感知查询扩展（A-3，升级计划 §3.1 L-A）：语义桥核心。

检索词经过四级归一/扩展后追加进 searchQuery——让"高风险订单"能命中
HighRiskOrder 实例、"order"能命中 Order、"状态"能命中 has_status。
四级级联：精确 term_id → 别名 → 子类实例展开 → 关系邻域。
未命中返回空扩展（不猜不造）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MAX_EXPANSION_TERMS = 8


@dataclass
class ExpandResult:
    originalQuery: str
    expandedTerms: List[str] = field(default_factory=list)
    matchedTermId: str = ""
    matchedKind: str = ""


def expandQuery(registry: Any, query: str, agentId: str = "default",
                tenantId: str = "default") -> ExpandResult:
    """四级级联查询扩展。`expandedTerms` 是追加进 searchQuery 的额外词集。"""
    text = str(query or "").strip()
    if not text:
        return ExpandResult(originalQuery=query)

    terms: List[str] = []
    matchedTermId = ""
    matchedKind = ""

    # ① 精确 term_id
    term = registry.term(text, tenantId=tenantId)
    if term is not None:
        matchedTermId = str(term["term_id"])
        matchedKind = str(term.get("kind") or "")
        terms.append(matchedTermId)
        label = str(term.get("label") or "")
        if label and label != matchedTermId:
            terms.append(label)

    # ② 别名归一（concept + relation）
    if not matchedTermId:
        resolved = _resolveAnyAlias(registry, text, tenantId=tenantId)
        if resolved:
            matchedTermId = resolved["term_id"]
            matchedKind = resolved["kind"]
            terms.append(matchedTermId)
            label = str(resolved.get("label") or "")
            if label and label != matchedTermId:
                terms.append(label)

    # ③ 子类实例展开（concept）：沿 parent 链向下收集挂该类型的主体规范名
    if matchedKind == "concept" and matchedTermId:
        try:
            childTerms = [matchedTermId] + [
                str(t["term_id"]) for t in registry.terms(tenantId=tenantId)
                if t.get("parent_term_id") == matchedTermId
            ]
            store = getattr(registry, "_store", None)
            if store is None:
                from ..foundation.knowledge_facts import get_knowledge_fact_store
                store = get_knowledge_fact_store()
            placeholders = ",".join("?" * len(childTerms))
            rows = store._conn.execute(
                "SELECT DISTINCT s.canonical_label AS label"
                " FROM knowledge_subjects s"
                " WHERE s.type_term_id IN (%s) AND s.agent_id = ?"
                " ORDER BY s.canonical_label LIMIT ?"
                % placeholders, childTerms + [agentId, MAX_EXPANSION_TERMS]).fetchall()
            for row in rows:
                label = str(row["label"] or "")
                if label and label not in terms:
                    terms.append(label)
        except Exception:
            pass

    # ④ 关系邻域：relation 术语 → 该谓词下的 top 事实客体词进扩展
    if matchedKind == "relation":
        try:
            store = getattr(registry, "_store", None)
            if store is None:
                from ..foundation.knowledge_facts import get_knowledge_fact_store
                store = get_knowledge_fact_store()
            rows = store._conn.execute(
                "SELECT DISTINCT object_term FROM knowledge_facts"
                " WHERE predicate_term_id = ? AND agent_id = ?"
                " AND tenant_id = ? AND status = 'active'"
                " AND record_kind = 'triple' LIMIT ?",
                (matchedTermId, agentId, tenantId, MAX_EXPANSION_TERMS)
            ).fetchall()
            for row in rows:
                obj = str(row["object_term"])
                if obj and obj not in terms:
                    terms.append(obj)
        except Exception:
            pass

    # 去重保序，截断
    seen: set = set()
    deduped = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)
    return ExpandResult(originalQuery=query,
                        expandedTerms=deduped[:MAX_EXPANSION_TERMS],
                        matchedTermId=matchedTermId, matchedKind=matchedKind)


def _resolveAnyAlias(registry: Any, text: str,
                     tenantId: str = "default") -> Optional[Dict[str, Any]]:
    """跨 kind 别名归一（concept + relation）：精确别名→规范化 surface→规范 label。"""
    for kind in ("concept", "relation"):
        for term in registry.terms(kind, tenantId=tenantId):
            aliases = [str(a) for a in (term.get("aliases") or [])]
            if text in aliases:
                return {"term_id": str(term["term_id"]), "kind": kind,
                        "label": str(term.get("label") or "")}
    return None
