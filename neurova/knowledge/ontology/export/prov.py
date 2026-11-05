"""PROV-O 导出（B12 L7）：断言/活动/推导 → prov: 词汇，互操作声明。

对齐 §12.12"溯源与时间是一等公民"：activities 是 prov:Activity、
assertions 挂活动、derivation 边是 prov:Derivation。排序固定，逐字节确定。
"""

from __future__ import annotations

from typing import Any


def exportProv(store: Any, tenantId: str = "default") -> str:
    tenant = str(tenantId or "default")
    with store._lock:
        activityRows = store._conn.execute(
            "SELECT activity_id, activity_kind, started_at FROM knowledge_activities"
            " WHERE tenant_id = ? ORDER BY activity_id LIMIT 5000",
            (tenant,)).fetchall()
        derivationRows = store._conn.execute(
            "SELECT e.derived_fact_id, e.premise_fact_id, e.rule_id"
            " FROM knowledge_derivation_edges e"
            " JOIN knowledge_facts f ON f.fact_id = e.derived_fact_id"
            " WHERE f.tenant_id = ? ORDER BY e.derived_fact_id, e.premise_fact_id"
            " LIMIT 5000", (tenant,)).fetchall()

    lines = [
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "@prefix kbg: <https://neurova.local/knowledge/> .",
    ]
    for row in activityRows:
        lines.append("kbg:activity_%s rdf:type prov:Activity ;"
                     % str(row["activity_id"]).replace("-", "_"))
        lines.append("  prov:startedAtTime \"%s\" ."
                     % (row["started_at"] or ""))
    for row in derivationRows:
        lines.append("kbg:fact_%s prov:wasDerivedFrom kbg:fact_%s ;"
                     % (str(row["derived_fact_id"]).replace("-", "_"),
                        str(row["premise_fact_id"]).replace("-", "_")))
        lines.append("  prov:wasGeneratedBy kbg:rule_%s ."
                     % str(row["rule_id"]).replace("-", "_"))
    return "\n".join(lines) + "\n"
