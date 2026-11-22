# -*- coding: utf-8 -*-
"""数据驱动的本体缺口审计（对照研究 P1-2，2026-11-19）。

对方 Audit 的本仓等价物：对 schema 目录与候选队列做**零模型调用**的
缺口/漂移挖矿，五类信号（本仓适配）：

- uncovered：目录表无术语链接（coverage gap）——建议器的输入面；
- broken_reference：目录声明外键指向目录中不存在的表（源漂移/残缺）；
- clash：同一术语被链接到同源多张表（映射歧义）；
- stale：pending 候选/建议超过 staleDays 未审（治理积压）；
- ambiguity：同源两表 humanize 后同名（建议器将产出冲突术语 slug）。

每条 finding 带跨轮稳定的 `fingerprint`（sha256(kind|target) 截断）与
`proposal`（建议动作，供审批流/人工消费）。**纯只读**：不落新表、不改
任何状态——发现是即时读数，留痕由调用方（端点/审批流）决定。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from neurova.core.time_utils import nowIso as _now
from neurova.core.tenant_scope import tenant_sql_where

_TOKEN_SPLIT = re.compile(r"[\W_]+", re.UNICODE)


def _fingerprint(kind: str, target: str) -> str:
    """跨轮稳定指纹：同 (kind, target) 两次审计必相同（对齐对方审计语义）。"""
    raw = "%s|%s" % (kind, target)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _humanize(name: str) -> str:
    parts = [p for p in _TOKEN_SPLIT.split(str(name or "")) if p]
    return " ".join(p[:1].upper() + p[1:] for p in parts)


def auditOntologyCoverage(store: Any, tenantId: str, sourceId: str = "",
                          staleDays: int = 7) -> Dict[str, Any]:
    """目录/候选队列缺口审计（只读）。sourceId 缺省扫全租户目录。"""
    from .schema_suggester import humanizeTableName

    tenant = str(tenantId or "default")
    source = str(sourceId or "")
    findings: List[Dict[str, Any]] = []

    catalog = _catalogOf(store)
    tables = catalog.listTables(tenant, sourceId=source or "", limit=10000)
    byTerm: Dict[str, List[str]] = {}
    byHumanName: Dict[str, List[str]] = {}
    knownTables: set = set()
    for table in tables:
        tableName = str(table["table_name"])
        knownTables.add(tableName)
        termId = str(table.get("term_id") or "")
        if termId:
            byTerm.setdefault(termId, []).append(tableName)
        else:
            findings.append(_finding(
                "uncovered", "table:%s:%s" % (table["source_id"], tableName),
                "表 %s 尚未链接本体术语（覆盖缺口）",
                {"action": "suggest_terms", "source_id": table["source_id"],
                 "table": tableName}))
        human = _humanize(tableName)
        byHumanName.setdefault(human.lower(), []).append(tableName)

    for termId, tableNames in sorted(byTerm.items()):
        if len(tableNames) > 1:
            findings.append(_finding(
                "clash", "term:%s" % termId,
                "术语 %s 被链接到 %d 张表：%s",
                {"action": "review_links", "term_id": termId,
                 "tables": tableNames}, termId, len(tableNames),
                ", ".join(sorted(tableNames))))

    for nameLower, tableNames in sorted(byHumanName.items()):
        if len(tableNames) > 1:
            findings.append(_finding(
                "ambiguity", "name:%s" % nameLower,
                "同源 %d 张表业务名同形（%s）——建议器将产出冲突术语",
                {"action": "review_names", "name": nameLower,
                 "tables": sorted(tableNames)},
                len(tableNames), humanizeTableName(tableNames[0])))

    for edge in catalog.foreignKeyEdges(tenant, sourceId=source or ""):
        targetTable = str(edge.get("target_table") or "")
        if targetTable and targetTable not in knownTables:
            findings.append(_finding(
                "broken_reference",
                "fk:%s:%s:%s" % (edge.get("source_table"),
                                 edge.get("source_column"), targetTable),
                "外键 %s.%s 指向目录中不存在的表 %s（源漂移/目录残缺）",
                {"action": "refresh_catalog", "source_id": edge.get("source_id")},
                edge.get("source_table"), edge.get("source_column"), targetTable))

    if staleDays > 0:
        horizon = (datetime.utcnow() - timedelta(days=int(staleDays))).isoformat()
        with store._lock:
            staleClause, staleParams = tenant_sql_where(tenant)
            staleCandidates = store._conn.execute(
                "SELECT surface, created_at FROM ontology_relation_candidates"
                " WHERE %s AND status = 'pending' AND created_at < ?"
                " ORDER BY created_at LIMIT 50" % staleClause,
                (*staleParams, horizon)).fetchall()
            staleSuggestions = store._conn.execute(
                "SELECT target, created_at FROM ontology_schema_suggestions"
                " WHERE %s AND status = 'pending' AND created_at < ?"
                " ORDER BY created_at LIMIT 50" % staleClause,
                (*staleParams, horizon)).fetchall()
        for row in staleCandidates:
            findings.append(_finding(
                "stale", "candidate:%s" % row["surface"],
                "关系候选「%s」自 %s 起 pending 超 %d 天未审",
                {"action": "review_pending", "queue": "relation_candidates"},
                row["surface"], row["created_at"], staleDays))
        for row in staleSuggestions:
            findings.append(_finding(
                "stale", "suggestion:%s" % row["target"],
                "术语建议 %s 自 %s 起 pending 超 %d 天未审",
                {"action": "review_pending", "queue": "schema_suggestions"},
                row["target"], row["created_at"], staleDays))

    counts: Dict[str, int] = {}
    for finding in findings:
        counts[finding["kind"]] = counts.get(finding["kind"], 0) + 1
    return {"tenant_id": tenant, "source_id": source,
            "scanned_at": _now(), "stale_days": int(staleDays),
            "tables_scanned": len(tables), "findings": findings,
            "counts": counts}


def _catalogOf(store: Any):
    from ..enterprise.schema_catalog import SchemaCatalogStore

    return SchemaCatalogStore(store)


def _finding(kind: str, target: str, messageFmt: str, proposal: Dict[str, Any],
             *args: Any) -> Dict[str, Any]:
    return {"kind": kind, "target": target,
            "message": messageFmt % args if args else messageFmt,
            "fingerprint": _fingerprint(kind, target),
            "severity": _severityOf(kind), "proposal": proposal}


def _severityOf(kind: str) -> str:
    return {"broken_reference": "warning", "clash": "warning",
            "ambiguity": "warning", "stale": "info",
            "uncovered": "info"}.get(kind, "info")
