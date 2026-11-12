# -*- coding: utf-8 -*-
"""事后追责审计跨账聚合（specs/2026-11-12 §13 W12）。

只读聚合器：跨五本账（change_log / derivation_ledger / agent_run_ledger /
决策台账 / digest_chain）按主体/时间窗聚合，返回统一事件行（who/when/basis/
action/outcome/approval 引用）。通则 6：不建第二审计存储——各账本写面零改动；
租户隔离与身份过滤沿用各账本既有口径（运行台账行 user_id 按 agent 属主、决策
decision_maker 按 sender——两个记账主体语义如实标注，不混算）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 单次聚合每本账的取数上限（防全表扫大账本）
_PER_LEDGER_LIMIT = 200


def accountabilityQuery(store: Any, subject: Optional[str] = None,
                        actor: Optional[str] = None,
                        timeWindowStart: Optional[str] = None,
                        timeWindowEnd: Optional[str] = None,
                        tenantId: str = "default") -> Dict[str, Any]:
    """跨五账聚合追责查询：返回统一事件行清单＋各账取数计数。"""
    tenant = str(tenantId or "default")
    events: List[Dict[str, Any]] = []
    ledgerCounts: Dict[str, int] = {}

    # ① change_log：本体术语/规则/形状变更（who/what/when）
    events += _fromChangeLog(store, tenant, subject, actor,
                             timeWindowStart, timeWindowEnd, ledgerCounts)
    # ② derivation_ledger：推导溯源（规则→结论）
    events += _fromDerivationLedger(store, tenant, subject, ledgerCounts)
    # ③ agent_run_ledger：运行态（回合/续跑/取消）
    events += _fromAgentRunLedger(store, subject, actor,
                                  timeWindowStart, timeWindowEnd, ledgerCounts)
    # ④ 决策台账：决策/链接
    events += _fromDecisionLedger(store, tenant, actor,
                                  timeWindowStart, timeWindowEnd, ledgerCounts)
    # ⑤ digest_chain：完整性校验状态
    events += _fromDigestChain(store, tenant, subject, ledgerCounts)

    events.sort(key=lambda e: e.get("when") or "")
    return {"events": events, "ledger_counts": ledgerCounts,
            "total": len(events)}


def _inWindow(stamp: str, start: Optional[str], end: Optional[str]) -> bool:
    if start and stamp < start:
        return False
    if end and stamp > end:
        return False
    return True


def _fromChangeLog(store: Any, tenant: str, subject: Optional[str],
                   actor: Optional[str], start: Optional[str],
                   end: Optional[str], counts: Dict[str, int]) -> List[Dict[str, Any]]:
    sql = ("SELECT change_id, target_type, target_id, action, actor, reason,"
           " created_at FROM ontology_change_log WHERE tenant_id = ?"
           " ORDER BY created_at DESC LIMIT ?")
    rows = store._conn.execute(sql, (tenant, _PER_LEDGER_LIMIT)).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        stamp = str(row["created_at"] or "")
        if not _inWindow(stamp, start, end):
            continue
        who = str(row["actor"] or "")
        if actor and actor not in who:
            continue
        entity = str(row["target_id"] or "")
        if subject and subject not in entity:
            continue
        counts["change_log"] = counts.get("change_log", 0) + 1
        out.append({"ledger": "change_log", "who": who, "when": stamp,
                    "basis": str(row["reason"] or ""),
                    "action": "%s %s %s" % (row["action"], row["target_type"], entity),
                    "outcome": "", "approval": ""})
    return out


def _fromDerivationLedger(store: Any, tenant: str, subject: Optional[str],
                          counts: Dict[str, int]) -> List[Dict[str, Any]]:
    try:
        from .derivation_ledger import DerivationLedger

        ledger = DerivationLedger(store)
        fires = ledger.fires()[:_PER_LEDGER_LIMIT]
    except Exception:  # noqa: BLE001 - 账本缺席如实空
        return []
    out: List[Dict[str, Any]] = []
    for fire in fires:
        subjectKey = ""
        for fid in (fire.get("derived_fact_ids") or []):
            fact = store.fact(fid) or {}
            subjectKey = str(fact.get("subject_key") or "")
            break
        label = _labelOf(store, subjectKey)
        if subject and subject not in label:
            continue
        counts["derivation_ledger"] = counts.get("derivation_ledger", 0) + 1
        out.append({"ledger": "derivation_ledger", "who": fire.get("rule_id", ""),
                    "when": fire.get("fired_at", ""),
                    "basis": "规则 %s 推导" % fire.get("rule_id"),
                    "action": "推导 %d 结论" % fire.get("live_count", 0),
                    "outcome": "live=%d" % fire.get("live_count", 0),
                    "approval": ""})
    return out


def _fromAgentRunLedger(store: Any, subject: Optional[str],
                        actor: Optional[str], start: Optional[str],
                        end: Optional[str], counts: Dict[str, int]) -> List[Dict[str, Any]]:
    try:
        from ...core.agent_run_store import get_agent_run_store

        runStore = get_agent_run_store()
        with runStore._lock:
            rows = runStore._conn.execute(
                "SELECT * FROM agent_runs ORDER BY seq DESC LIMIT ?",
                (_PER_LEDGER_LIMIT,)).fetchall()
        runRows = [dict(r) for r in rows]
    except Exception:  # noqa: BLE001 - 台账缺席如实空
        return []
    out: List[Dict[str, Any]] = []
    for row in runRows:
        stamp = str(row.get("created_at") or "")
        if not _inWindow(stamp, start, end):
            continue
        who = str(row.get("user_id") or "")
        if actor and actor not in who:
            continue
        counts["agent_run_ledger"] = counts.get("agent_run_ledger", 0) + 1
        out.append({"ledger": "agent_run_ledger",
                    "who": who, "when": stamp,
                    "basis": "回合 %s" % row.get("session_id", ""),
                    "action": "run %s" % row.get("status", ""),
                    "outcome": str(row.get("status") or ""),
                    "approval": "",
                    "_owner_semantics": "agent 属主（AGENTS.md §3）"})
    return out


def _fromDecisionLedger(store: Any, tenant: str, actor: Optional[str],
                        start: Optional[str], end: Optional[str],
                        counts: Dict[str, int]) -> List[Dict[str, Any]]:
    try:
        from .decision_ledger import DecisionLedger

        decisions = DecisionLedger(store).list(tenantId=tenant, limit=_PER_LEDGER_LIMIT)
    except Exception:  # noqa: BLE001 - 台账缺席如实空
        return []
    out: List[Dict[str, Any]] = []
    for dec in decisions:
        stamp = str(dec.get("created_at") or "")
        if not _inWindow(stamp, start, end):
            continue
        who = str(dec.get("decision_maker") or "")
        if actor and actor not in who:
            continue
        meta = dec.get("metadata") or {}
        counts["decision_ledger"] = counts.get("decision_ledger", 0) + 1
        simId = str(meta.get("simulation_id") or "")
        actId = str(meta.get("action_id") or "")
        approval = ""
        if simId:
            approval = "演过再决 sim=%s" % simId
        if actId:
            approval = (approval + " " if approval else "") + "act=%s" % actId
        out.append({"ledger": "decision_ledger", "who": who, "when": stamp,
                    "basis": dec.get("reasoning", ""),
                    "action": "%s: %s" % (dec.get("category"), dec.get("scenario")),
                    "outcome": "%s (conf=%.2f)" % (dec.get("outcome"),
                                                   dec.get("confidence", 0)),
                    "approval": approval,
                    "_owner_semantics": "decision_maker=sender（AGENTS.md §3）"})
    return out


def _fromDigestChain(store: Any, tenant: str, subject: Optional[str],
                     counts: Dict[str, int]) -> List[Dict[str, Any]]:
    try:
        from .digest_chain import ActivityDigestChain

        chain = ActivityDigestChain(store)
        result = chain.verify()
    except Exception:  # noqa: BLE001 - 链缺席如实空
        return []
    counts["digest_chain"] = 1
    brk = result.get("break")
    status = "broken" if brk else "pass"
    detail = "（断链位置=%s）" % json.dumps(brk, default=str) if brk else ""
    return [{"ledger": "digest_chain", "who": "system", "when": _nowIso(),
             "basis": "哈希链完整性校验（ok=%s, chains=%d, rows=%d）"
                       % (result.get("ok"), result.get("chains", 0),
                          result.get("rows", 0)),
             "action": "verify",
             "outcome": "%s%s" % (status, detail),
             "approval": ""}]


def _labelOf(store: Any, subjectKey: str) -> str:
    try:
        row = None
        with store._lock:
            row = store._conn.execute(
                "SELECT canonical_label FROM knowledge_subjects WHERE subject_key = ?",
                (subjectKey,)).fetchone()
        return str(row["canonical_label"]) if row is not None else subjectKey
    except Exception:
        return subjectKey


def _nowIso() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _jsonSafe(obj: Any) -> Any:
    """json.dumps 默认回调（聚合行含非可序列化值时降级成 str）。"""
    return str(obj)
