# -*- coding: utf-8 -*-
"""同构表副本聚族（term families，对照研究 P3-2，2026-11-15）。

数仓迁移常留双份：`OLD_ROOMS` 旁边 `NEW_ROOMS`。前缀是族名，剥前缀后
同名的表是孪生。本模块在 schema 目录上做**确定性**聚族（对方
term_families 的简化批：孪生判定用列名集合 Jaccard，历史表 `*_HIST`
不参与），产物是 pending 的 `family` 建议——走 P1-2 建议审批流，人工
批准后可指导语义外键不跨副本误连（消费方属后续批）。

只产候选不改目录；显式端点触发（无自动跑批）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

#: 孪生列名集合 Jaccard 下限
MIN_TWIN_JACCARD = 0.8
#: 历史表后缀（不与现役表互认孪生）
_HISTORY_SUFFIX = re.compile(r"(_HIST|_HISTORY)$", re.IGNORECASE)


def _splitPrefix(tableName: str) -> tuple:
    """`OLD_ROOMS` → ("OLD", "ROOMS")；无下划线 → ("", 原名)。"""
    parts = str(tableName or "").split("_", 1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0].upper(), parts[1]
    return "", str(tableName or "")


def _columnNames(detail: Dict[str, Any]) -> set:
    return {str(c.get("column_name") or "").lower()
            for c in (detail or {}).get("columns") or [] if c.get("column_name")}


def detectTermFamilies(catalog: Any, tenantId: str, sourceId: str,
                       minJaccard: float = MIN_TWIN_JACCARD) -> List[Dict[str, Any]]:
    """一个源内的同构副本聚族。返回 [{prefix, base_name, members, jaccard}]。"""
    tenant = str(tenantId or "default")
    tables = catalog.listTables(tenant, sourceId=str(sourceId or ""),
                                limit=10000)
    details: Dict[str, set] = {}
    for table in tables:
        name = str(table["table_name"])
        if _HISTORY_SUFFIX.search(name):
            continue
        detail = catalog.tableDetail(tenant, str(table["catalog_table_id"])) or {}
        columns = _columnNames(detail)
        if columns:
            details[name] = columns

    # 按 (前缀, 剥前缀名) 分桶，同 base 跨前缀两两算 Jaccard
    byBase: Dict[str, Dict[str, set]] = {}
    for name, columns in details.items():
        prefix, base = _splitPrefix(name)
        byBase.setdefault(base.upper(), {})[name] = columns

    families: List[Dict[str, Any]] = []
    for base, members in sorted(byBase.items()):
        if len(members) < 2:
            continue
        names = sorted(members)
        merged: List[str] = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = members[names[i]], members[names[j]]
                union = a | b
                jaccard = (len(a & b) / len(union)) if union else 0.0
                if jaccard >= minJaccard:
                    for name in (names[i], names[j]):
                        if name not in merged:
                            merged.append(name)
        if len(merged) >= 2:
            prefixes = sorted({_splitPrefix(m)[0] for m in merged})
            families.append({"base_name": base.title(), "prefixes": prefixes,
                             "members": sorted(merged)})
    return families


def suggestFamilies(suggester: Any, catalog: Any, tenantId: str,
                    sourceId: str) -> Dict[str, Any]:
    """聚族结果 → pending family 建议（同目标幂等；拒绝后不再重生）。"""
    families = detectTermFamilies(catalog, tenantId, sourceId)
    created = 0
    for family in families:
        target = "family:%s:%s:%s" % (sourceId, "-".join(family["prefixes"]),
                                      family["base_name"])
        if suggester._hasActiveSuggestion(str(tenantId or "default"),
                                          str(sourceId or ""), "family", target):
            continue
        suggester._recordSuggestion(
            str(tenantId or "default"), str(sourceId or ""), "family", target,
            {"base_name": family["base_name"], "prefixes": family["prefixes"],
             "members": family["members"]},
            basis="rule", confidence=0.6)
        created += 1
    return {"families": families, "suggestions_created": created}
