"""JSON-LD 导出（B12 L7，升级计划 §12.8）：@context + @graph，逐字节确定。

零第三方依赖：@context 只声明 kbg 前缀与 rdf:type 映射；@graph 逐术语/逐事实行，
排序全部固定 ORDER BY。RDF 1.1 基线。
"""

from __future__ import annotations

import json
from typing import Any

from ..term_registry import NAMESPACE_REGISTRY

NAMESPACE = "https://neurova.local/knowledge/"


def exportJsonLd(store: Any, tenantId: str = "default", agentId: str = "") -> str:
    tenant = str(tenantId or "default")
    with store._lock:
        termRows = store._conn.execute(
            "SELECT term_id, kind, label, parent_term_id, definition, namespace FROM ontology_terms"
            " WHERE tenant_id = ? ORDER BY term_id", (tenant,)).fetchall()
        factSql = ("SELECT subject_key, predicate_term_id, object_term"
                   " FROM knowledge_facts WHERE tenant_id = ?"
                   " AND status = 'active' AND record_kind = 'triple'")
        params: list = [tenant]
        if agentId:
            factSql += " AND agent_id = ?"
            params.append(str(agentId))
        factSql += " ORDER BY subject_key, predicate_term_id, object_term"
        factRows = store._conn.execute(factSql, params).fetchall()

    graph = []
    for row in termRows:
        # G4：namespace 非空的术语用自身前缀（空 = 缺省 kbg:）
        ns = str(row["namespace"] or "") if "namespace" in row.keys() else ""
        termIri = ("%s:%s" % (ns, row["term_id"])) if ns else ("kbg:%s" % row["term_id"])
        node: dict = {"@id": termIri, "@type": "kbg:Term",
                      "term_id": row["term_id"], "kind": row["kind"],
                      "label": row["label"] or row["term_id"]}
        # G1：定义描述项——非空才出（空值零漂移）
        if str(row["definition"] or "").strip() if "definition" in row.keys() else False:
            node["definition"] = str(row["definition"])
        if row["parent_term_id"]:
            node["parent_term_id"] = "kbg:%s" % row["parent_term_id"]
        graph.append(node)
    for row in factRows:
        graph.append({"@id": "kbg:%s" % row["subject_key"],
                      "kbg:%s" % row["predicate_term_id"]: row["object_term"]})

    doc = {"@context": {"kbg": NAMESPACE, "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                   "so": NAMESPACE_REGISTRY["so"]},
           "@graph": graph}
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1)
