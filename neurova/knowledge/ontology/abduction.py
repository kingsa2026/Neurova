"""溯因反向搜索（specs/2026-11-12 §10 W9，D9 四职能面之一）。

目标三元组→匹配 head 的规则→body 原子递归展开为子目标→已有事实满足或
继续展开，产出解释树（规则引用＋事实引用＋缺失前提清单）。**只读不写事实**
——解释是候选不是断言（与 admission"抽取只当候选"同构）；复用规则表单源，
不建第二规则存储。深度与候选数上限具名常量，超限显式截断声明。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 溯因展开深度上限（超限显式截断声明）
MAX_ABDUCTION_DEPTH = 6

#: 解释树候选上限
MAX_ABDUCTION_BRANCHES = 50


def _factsFor(store: Any, agentId: str, predicate: str,
              subjectKey: str = "", objectTerm: str = "",
              tenantId: str = "default") -> List[Dict[str, Any]]:
    sql = ("SELECT f.fact_id, s.canonical_label AS subject_label,"
           " f.predicate_term_id, f.object_term FROM knowledge_facts f"
           " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
           " WHERE f.agent_id = ? AND f.tenant_id = ?"
           " AND f.predicate_term_id = ? AND f.status = 'active'"
           " AND f.record_kind = 'triple'")
    params: List[Any] = [agentId, tenantId, predicate]
    if subjectKey:
        sql += " AND f.subject_key = ?"
        params.append(subjectKey)
    if objectTerm:
        sql += " AND f.object_term = ?"
        params.append(objectTerm)
    sql += " LIMIT 200"
    with store._lock:
        rows = store._conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def explainGoal(store: Any, subjectLabel: str, predicate: str, objectTerm: str,
                agentId: str = "default", tenantId: str = "default",
                maxDepth: int = MAX_ABDUCTION_DEPTH,
                maxBranches: int = MAX_ABDUCTION_BRANCHES) -> Dict[str, Any]:
    """目标解释：直接事实命中（satisfied）或规则展开（树）或缺失前提清单。"""
    from .rule_engine import ForwardChainingEngine

    engine = ForwardChainingEngine(store)
    key = store.resolveSubjectKey(agentId, subjectLabel, tenantId=tenantId) \
        if hasattr(store, "resolveSubjectKey") else ""
    row = None
    with store._lock:
        row = store._conn.execute(
            "SELECT subject_key FROM knowledge_subjects"
            " WHERE agent_id = ? AND tenant_id = ? AND normalized_label = ?"
            " AND status = 'active'",
            (agentId, tenantId, str(subjectLabel or "").strip().casefold())).fetchone()
    subjectKey = str(row["subject_key"]) if row is not None else ""

    steps: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    visited: set = set()
    counters = {"branches": 0}

    def _expand(subject: str, subPredicate: str, obj: str,
                depth: int, path: List[str]) -> bool:
        """返回该子目标是否可满足（事实或规则展开）。"""
        if counters["branches"] >= maxBranches:
            missing.append({"subject": subject, "predicate": subPredicate,
                            "object": obj, "reason": "分支上限截断"})
            return False
        counters["branches"] += 1
        if depth <= 0:
            missing.append({"subject": subject, "predicate": subPredicate,
                            "object": obj, "reason": "深度上限截断"})
            return False
        subKey = ""
        row = None
        with store._lock:
            row = store._conn.execute(
                "SELECT subject_key FROM knowledge_subjects"
                " WHERE agent_id = ? AND tenant_id = ? AND canonical_label = ?"
                " AND status = 'active'",
                (agentId, tenantId, subject)).fetchone()
        subKey = str(row["subject_key"]) if row is not None else ""

        # ① 已有事实直接满足
        facts = _factsFor(store, agentId, subPredicate,
                          subjectKey=subKey, objectTerm=obj or "", tenantId=tenantId)
        if facts:
            for f in facts:
                steps.append({"kind": "fact", "fact_id": f["fact_id"],
                              "subject": f["subject_label"],
                              "predicate": f["predicate_term_id"],
                              "object": f["object_term"],
                              "depth": depth, "path": " → ".join(path + [subPredicate])})
            return True

        # ② 规则展开（head 匹配该子目标谓词）
        node = (subject, subPredicate, obj)
        if node in visited:
            missing.append({"subject": subject, "predicate": subPredicate,
                            "object": obj, "reason": "环截断"})
            return False
        visited.add(node)
        satisfiedByRule = False
        matchedAnyRule = False
        for rule in engine.rules(tenantId=tenantId):
            if str(rule.get("head_predicate")) != subPredicate:
                continue
            matchedAnyRule = True
            counters["branches"] += 1
            if counters["branches"] >= maxBranches:
                break
            bodyAtoms = rule.get("body") or []
            branch: List[Dict[str, Any]] = [{
                "kind": "rule", "rule_id": rule["rule_id"],
                "depth": depth, "path": " → ".join(path + [subPredicate])}]
            allOk = True
            subMissing: List[Dict[str, Any]] = []
            for atom in bodyAtoms:
                atomPredicate = str(atom.get("predicate") or atom.get("atom") or "")
                if not atomPredicate:
                    continue
                atomSubject = subject if atom.get("subject") == rule.get("head_subject_var", "S") \
                    else str(atom.get("subject") or "")
                atomObject = obj if atom.get("object") == rule.get("head_object_var", "O") \
                    else str(atom.get("object") or "")
                subOk = _expand(atomSubject, atomPredicate, atomObject,
                                depth - 1, path + [rule["rule_id"]])
                if not subOk:
                    allOk = False
                    subMissing.append({
                        "subject": atomSubject, "predicate": atomPredicate,
                        "object": atomObject, "rule_id": rule["rule_id"],
                        "reason": "子目标不可满足"})
                    break
                branch.extend([s for s in steps
                               if s.get("path", "").startswith(
                                   " → ".join(path + [rule["rule_id"]]))])
            if allOk:
                satisfiedByRule = True
                steps.extend(branch)
            else:
                missing.extend(subMissing)
        if not matchedAnyRule:
            missing.append({"subject": subject, "predicate": subPredicate,
                            "object": obj, "reason": "无规则可展开且无事实"})
        return satisfiedByRule

    satisfied = _expand(subjectLabel, predicate, objectTerm, maxDepth,
                        [subjectLabel])
    return {
        "goal": {"subject": subjectLabel, "predicate": predicate,
                 "object": objectTerm},
        "satisfied": satisfied or bool(steps),
        "steps": steps[:MAX_ABDUCTION_BRANCHES],
        "missing": missing[:MAX_ABDUCTION_BRANCHES],
        "max_depth": maxDepth,
        "branches_used": counters["branches"],
    }
