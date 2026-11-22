# -*- coding: utf-8 -*-
"""冲突消解只读建议面（U6 本体域升级卡）。

与写面裁决器 `foundation/conflict_judge.py` 的分工（教义第 7 条对比结论）：
- `KnowledgeConflictJudge` 是**写面权威**：把分歧成账 `knowledge_conflicts`、按证据态
  门控自动取代（supersede）败方——有副作用，其阶梯（源钟→断言数→置信）服务于
  "入库时谁活下来"；且它要求成员 evidence_state='evidenced' 才肯自动裁决。
- 本模块是**只读建议面**：同 (subject_key, predicate_term_id) 出现 ≥2 个不同 object
  值时，给出 {strategy, suggestedValue, reason, evidence, candidates}。不写任何表、
  不调 admit、不取代任何事实——读数一律走 `store.queryReadOnly`（仅放行 SELECT）。
  供上层（MCP/REST/人工审核台）在"要不要裁、怎么裁"之前先拿到可解释的建议；
  真正落裁决仍归 conflict_judge / 人工处置面，二者不是同一功能的第二份实现。

策略闭集与自动选择规则（缺省 strategy=None 时按内置优先级）：
1. 候选置信度存在差异（可量化）→ `highest_confidence`；
2. 否则同值票数差明显（ top 值票数 > 次值且 ≥2 票）→ `majority_vote`；
3. 否则 → `manual_review`（分歧不可量化或证据不足，显式转人工）。
显式传入策略时按该策略裁决；策略内部无区分依据（并列/缺置信）时如实升级为
manual_review，不静默挑边。

source_credibility 一期口径：按来源（agent_id）候选事实的**平均 confidence** 代理
"来源历史一致率"加权——真实一致率读数回填后替换此代理（reason 中如实注明）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.tenant_scope import tenant_sql_where

ADVICE_STRATEGIES = ("latest", "highest_confidence", "majority_vote",
                     "source_credibility", "manual_review")

_CANDIDATE_SQL = (
    "SELECT fact_id, agent_id, object_term, confidence, recorded_at"
    " FROM knowledge_facts WHERE {tenant} subject_key = ? AND predicate_term_id = ?"
    " AND status = 'active' AND record_kind = 'triple'"
    " ORDER BY recorded_at, fact_id"
)


def adviseConflict(store: Any, tenantId: str, subjectKey: str, predicateTermId: str,
                   *, strategy: Optional[str] = None) -> Dict[str, Any]:
    """对同一 (主体, 谓词) 的多源取值分歧给出**只读**消解建议。

    返回：
    - strategy: 实际生效策略（缺省时为自动选定；显式策略无区分依据时升级为
      manual_review）；单值/无事实时为 "none"；
    - suggestedValue: 建议采信的 object 值（manual_review/无事实时为 None）；
    - reason: 可读裁决依据；
    - evidence: 支撑该建议的 fact_id 列表；
    - candidates: 全部候选 [{value, factId, confidence, recordedAt}]（按 recorded_at,
      fact_id 稳定排序）。
    """
    if strategy is not None and strategy not in ADVICE_STRATEGIES:
        raise ValueError("未知策略 %r（有效值: %s）" % (strategy, " / ".join(ADVICE_STRATEGIES)))
    facts = _readCandidateFacts(store, tenantId, subjectKey, predicateTermId)
    candidates = [{
        "value": str(f["object_term"]),
        "factId": str(f["fact_id"]),
        "confidence": None if f["confidence"] is None else float(f["confidence"]),
        "recordedAt": str(f["recorded_at"] or ""),
    } for f in facts]
    distinctValues = {c["value"] for c in candidates}
    if len(distinctValues) <= 1:
        # 单值/无事实：诚实回"无冲突"，不造分歧。
        return {
            "strategy": "none",
            "suggestedValue": distinctValues.pop() if distinctValues else None,
            "reason": ("该主体-谓词下没有可读的 active 事实" if not candidates
                       else "同主体同谓词只有一个取值，无冲突"),
            "evidence": [c["factId"] for c in candidates],
            "candidates": candidates,
        }
    effective = strategy or _autoStrategy(facts)
    return _applyStrategy(effective, facts, candidates)


def _readCandidateFacts(store: Any, tenantId: str, subjectKey: str,
                        predicateTermId: str) -> List[Dict[str, Any]]:
    """只读取候选事实：queryReadOnly 仅放行 SELECT，本模块全程无写路径。"""
    tenantClause, tenantParams = tenant_sql_where(str(tenantId or "default"))
    sql = _CANDIDATE_SQL.format(tenant=(tenantClause + " AND ") if tenantClause else "")
    return store.queryReadOnly(sql, (*tenantParams, subjectKey, predicateTermId))


def _autoStrategy(facts: List[Dict[str, Any]]) -> str:
    confidences = [float(f["confidence"]) for f in facts if f["confidence"] is not None]
    if len(set(confidences)) > 1:
        return "highest_confidence"
    counts: Dict[str, int] = {}
    for fact in facts:
        counts[str(fact["object_term"])] = counts.get(str(fact["object_term"]), 0) + 1
    ordered = sorted(counts.values(), reverse=True)
    if len(ordered) >= 2 and ordered[0] > ordered[1] and ordered[0] >= 2:
        return "majority_vote"
    return "manual_review"


def _applyStrategy(strategy: str, facts: List[Dict[str, Any]],
                   candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    if strategy == "manual_review":
        return _manualReview(candidates, "分歧过大或证据不足，显式转人工裁决")
    if strategy == "latest":
        winner = max(facts, key=lambda f: (str(f["recorded_at"] or ""), str(f["fact_id"])))
        return _suggestion(
            "latest", winner, [str(winner["fact_id"])], candidates,
            "取 recorded_at 最新：%s（%s）晚于其余候选"
            % (winner["fact_id"], winner["recorded_at"]))
    if strategy == "highest_confidence":
        scored = [f for f in facts if f["confidence"] is not None]
        values = {float(f["confidence"]) for f in scored}
        if not scored or len(values) == 1:
            return _manualReview(candidates, "候选置信度并列或缺失，highest_confidence 无区分依据")
        winner = max(scored, key=lambda f: (float(f["confidence"]), str(f["fact_id"])))
        return _suggestion(
            "highest_confidence", winner, [str(winner["fact_id"])], candidates,
            "按置信裁决：%s（confidence=%s）高于其余候选"
            % (winner["fact_id"], winner["confidence"]))
    if strategy == "majority_vote":
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for fact in facts:
            groups.setdefault(str(fact["object_term"]), []).append(fact)
        ordered = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        topValue, topMembers = ordered[0]
        if len(topMembers) < 2:
            return _manualReview(candidates, "无任何取值获得 ≥2 票，majority_vote 无区分依据")
        if len(ordered) >= 2 and len(topMembers) == len(ordered[1][1]):
            return _manualReview(candidates, "票数并列（%d:%d），majority_vote 无区分依据"
                                 % (len(topMembers), len(ordered[1][1])))
        evidence = [str(f["fact_id"]) for f in sorted(
            topMembers, key=lambda f: (str(f["recorded_at"] or ""), str(f["fact_id"])))]
        return _suggestion(
            "majority_vote", topMembers[0], evidence, candidates,
            "同值计数：%r 获 %d 票，多于其余取值" % (topValue, len(topMembers)))
    if strategy == "source_credibility":
        scored = [f for f in facts if f["confidence"] is not None]
        if not scored:
            return _manualReview(candidates, "候选均无 confidence，来源可信度无代理依据")
        bySource: Dict[str, List[Dict[str, Any]]] = {}
        for fact in scored:
            bySource.setdefault(str(fact["agent_id"]), []).append(fact)
        sourceScore = {agent: sum(float(f["confidence"]) for f in members) / len(members)
                       for agent, members in bySource.items()}
        winner = max(scored, key=lambda f: (sourceScore[str(f["agent_id"])],
                                            float(f["confidence"]), str(f["fact_id"])))
        agent = str(winner["agent_id"])
        return _suggestion(
            "source_credibility", winner, [str(winner["fact_id"])], candidates,
            "按来源可信度加权（一期以来源 agent=%s 候选的平均 confidence=%s 代理"
            "历史一致率）：%s 胜出"
            % (agent, round(sourceScore[agent], 4), winner["fact_id"]))
    # 上面闭集已穷尽；到这里说明调用方绕过了校验，按契约显式拒绝而不是猜。
    raise ValueError("未知策略 %r（有效值: %s）" % (strategy, " / ".join(ADVICE_STRATEGIES)))


def _suggestion(strategy: str, winnerFact: Dict[str, Any], evidence: List[str],
                candidates: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    return {
        "strategy": strategy,
        "suggestedValue": str(winnerFact["object_term"]),
        "reason": reason,
        "evidence": evidence,
        "candidates": candidates,
    }


def _manualReview(candidates: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    return {
        "strategy": "manual_review",
        "suggestedValue": None,
        "reason": reason,
        "evidence": [c["factId"] for c in candidates],
        "candidates": candidates,
    }
