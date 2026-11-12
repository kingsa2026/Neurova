# -*- coding: utf-8 -*-
"""GraphML/GEXF/Cypher/CSV 四格式导出（specs/2026-11-12 §12 W11）。

与既有五格式同族（ontology/export/ 下一体量块）：节点＝ontology_terms 概念行
＋knowledge_subjects 主体行；边＝knowledge_facts active triple。确定性序列化
（固定 ORDER BY ⇒ 同库内容两次导出逐字一致）——与 turtle _canonicalJson 先例
同口径。全部 stdlib，零第三方依赖。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from xml.sax.saxutils import escape as _xmlEscape

_KB_NS = "https://neurova.local/knowledge/"


def _readGraph(store: Any, tenantId: str = "default",
               agentId: str = "") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """读 (nodes, edges)：nodes = 概念术语＋主体（去重），edges = active triple。"""
    with store._lock:
        termRows = store._conn.execute(
            "SELECT term_id, kind, label FROM ontology_terms"
            " WHERE tenant_id = ? AND kind = 'concept' ORDER BY term_id",
            (tenantId,)).fetchall()
        factSql = ("SELECT f.subject_key, s.canonical_label AS src,"
                   " f.predicate_term_id, f.object_term"
                   " FROM knowledge_facts f JOIN knowledge_subjects s"
                   " ON s.subject_key = f.subject_key"
                   " WHERE f.tenant_id = ? AND f.status = 'active'"
                   " AND f.record_kind = 'triple'")
        params: list = [tenantId]
        if agentId:
            factSql += " AND f.agent_id = ?"
            params.append(agentId)
        factSql += " ORDER BY s.canonical_label, f.predicate_term_id, f.object_term"
        factRows = store._conn.execute(factSql, params).fetchall()
    nodes: List[Dict[str, Any]] = []
    seen: set = set()
    for row in termRows:
        tid = str(row["term_id"])
        if tid not in seen:
            seen.add(tid)
            nodes.append({"id": tid, "label": str(row["label"] or tid),
                          "type": "term"})
    for row in factRows:
        src = str(row["src"])
        if src not in seen:
            seen.add(src)
            nodes.append({"id": src, "label": src, "type": "subject"})
        dst = str(row["object_term"])
        if dst not in seen:
            seen.add(dst)
            nodes.append({"id": dst, "label": dst, "type": "object"})
    edges = [{"source": str(r["src"]), "target": str(r["object_term"]),
              "predicate": str(r["predicate_term_id"])} for r in factRows]
    return nodes, edges


def exportGraphML(store: Any, tenantId: str = "default", agentId: str = "") -> str:
    nodes, edges = _readGraph(store, tenantId, agentId)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">'
           '<key id="label" for="node" attr.name="label" attr.type="string"/>',
           '<key id="predicate" for="edge" attr.name="predicate" attr.type="string"/>',
           '<graph edgedefault="directed">']
    for node in nodes:
        out.append('  <node id="%s"><data key="label">%s</data></node>'
                   % (_xmlEscape(node["id"]), _xmlEscape(node["label"])))
    for edge in edges:
        out.append('  <edge source="%s" target="%s">'
                   '<data key="predicate">%s</data></edge>'
                   % (_xmlEscape(edge["source"]), _xmlEscape(edge["target"]),
                      _xmlEscape(edge["predicate"])))
    out.append("</graph>\n</graphml>")
    return "\n".join(out)


def exportGexf(store: Any, tenantId: str = "default", agentId: str = "") -> str:
    nodes, edges = _readGraph(store, tenantId, agentId)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gexf xmlns="http://gexf.net/1.3" version="1.3">',
           '<graph defaultedgetype="directed"><nodes>']
    for node in nodes:
        out.append('  <node id="%s" label="%s"/>' % (_xmlEscape(node["id"]),
                                                     _xmlEscape(node["label"])))
    out.append("</nodes><edges>")
    for i, edge in enumerate(edges):
        out.append('  <edge id="e%d" source="%s" target="%s" label="%s"/>'
                   % (i, _xmlEscape(edge["source"]), _xmlEscape(edge["target"]),
                      _xmlEscape(edge["predicate"])))
    out.append("</edges></graph>\n</gexf>")
    return "\n".join(out)


def exportCypher(store: Any, tenantId: str = "default", agentId: str = "") -> str:
    """Cypher dump（CREATE 语句文本——外部图库自行导入）。"""
    nodes, edges = _readGraph(store, tenantId, agentId)
    out: List[str] = []
    for node in nodes:
        safe_label = node["label"].replace("'", "\\'")
        out.append("CREATE (%s:Entity {id: '%s', label: '%s', type: '%s'});"
                   % (_safeIdent(node["id"]), node["id"].replace("'", "\\'"),
                      safe_label, node["type"]))
    for edge in edges:
        out.append("MATCH (a:Entity {id: '%s'}), (b:Entity {id: '%s'})"
                   " CREATE (a)-[:%s]->(b);"
                   % (edge["source"].replace("'", "\\'"),
                      edge["target"].replace("'", "\\'"),
                      _safeRel(edge["predicate"])))
    return "\n".join(out)


def _safeIdent(raw: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_\u4e00-\u9fff]", "_", raw) or "n"


def _safeRel(raw: str) -> str:
    return _safeIdent(raw).upper() or "RELATED"


def exportCsv(store: Any, tenantId: str = "default", agentId: str = "") -> str:
    """CSV 节点/边双文件合一输出（用 `=== nodes ===` / `=== edges ===` 分段）。"""
    import csv
    import io

    nodes, edges = _readGraph(store, tenantId, agentId)
    buf = io.StringIO()
    buf.write("=== nodes ===\n")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["id", "label", "type"])
    for node in nodes:
        writer.writerow([node["id"], node["label"], node["type"]])
    buf.write("=== edges ===\n")
    writer.writerow(["source", "target", "predicate"])
    for edge in edges:
        writer.writerow([edge["source"], edge["target"], edge["predicate"]])
    return buf.getvalue()
