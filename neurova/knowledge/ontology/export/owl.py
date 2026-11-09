"""OWL 2 RL 公理导出（B12 L7）：互操作声明，不是运行时承诺（§12 语义边界）。

从术语表物化声明行：Declaration/Class、Declaration/ObjectProperty、
rdfs:subClassOf（概念父类）、rdfs:subPropertyOf（关系父属性）、
owl:inverseOf、owl:SymmetricProperty、owl:TransitiveProperty、
owl:FunctionalProperty（cardinality=1）。Turtle 语法，逐字节确定。

G3（GB/T 48000.3 评估档拍板 2026-11-10）：外部映射「替换」改「附加断言」——
本体 IRI 恒为 kbg:（此前 skos_exactMatch 槽会把主体 IRI 换成外部名，丢失本体
自身标识），等价/对齐以独立三元组输出：equivalentClass→owl:equivalentClass
（类）/ owl:equivalentProperty（属性），skos_*→skos:exactMatch 等同形谓词。
"""

from __future__ import annotations

import json
from typing import Any

from ..term_registry import NAMESPACE_REGISTRY, versionedIri


def _literal(text: str) -> str:
    """Turtle 字面量：反斜杠/引号/换行转义（与 turtle.py `_escape` 同形）。"""
    return '"%s"' % (str(text or "")
                     .replace("\\", "\\\\")
                     .replace('"', '\\"')
                     .replace("\n", "\\n")
                     .replace("\r", "\\r")
                     .replace("\t", "\\t"))

#: 外部映射 kind → 断言谓词（类与属性分形：equivalentClass/equivalentProperty）。
_KIND_PREDICATES = {
    "skos_exactMatch": ("skos:exactMatch", "skos:exactMatch"),
    "skos_closeMatch": ("skos:closeMatch", "skos:closeMatch"),
    "skos_relatedMatch": ("skos:relatedMatch", "skos:relatedMatch"),
    # 类级键在属性上回退等价属性谓词（表 1 Equivalent Class 的属性侧对偶）
    "equivalentClass": ("owl:equivalentClass", "owl:equivalentProperty"),
}


def exportOwlAxioms(store: Any, tenantId: str = "default",
                    version: str = "") -> str:
    tenant = str(tenantId or "default")
    with store._lock:
        termRows = store._conn.execute(
            "SELECT * FROM ontology_terms WHERE tenant_id = ? ORDER BY term_id",
            (tenant,)).fetchall()

    lines = [
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix kbg: <https://neurova.local/knowledge/> .",
    ]
    # G4：术语 namespace 非空的多前缀声明（第 9 章 a)——前缀/基座来自注册表闭集
    usedNamespaces = sorted({str(r["namespace"]) for r in termRows
                             if "namespace" in r.keys() and str(r["namespace"] or "")})
    for ns in usedNamespaces:
        lines.append("@prefix %s: <%s> ." % (ns, NAMESPACE_REGISTRY[ns]))
    if version:
        lines.append("kbg: ontology:versionInfo \"%s\" ; owl:versionIRI <%s> ."
                     % (version, versionedIri("ontology", version)))
    termsById = {str(r["term_id"]): r for r in termRows}

    # G3：本体 IRI 恒为本体侧前缀（kbg: 或术语自身 namespace）——外部名只在
    # 附加断言的宾语位。G4：namespace 非空的术语用自身前缀。
    def _iri(termId: str, namespace: str = "") -> str:
        return ("%s:%s" % (namespace, termId)) if namespace else ("kbg:%s" % termId)

    def _mappings(row: Any) -> list:
        if "external_iris_json" not in row.keys():
            return []
        raw = json.loads(row["external_iris_json"] or "[]")
        return raw if isinstance(raw, list) else []

    for row in termRows:
        termId = str(row["term_id"])
        kind = row["kind"]
        ns = str(row["namespace"] or "") if "namespace" in row.keys() else ""
        if kind == "concept":
            lines.append("%s rdf:type owl:Class ." % _iri(termId, ns))
        elif kind == "property":
            # G2/G6：数据属性声明——此前声明循环缺 property 分支，property 术语
            # 在 export.owl 不可见；datatype 非空出 rdfs:range xsd:*。
            lines.append("%s rdf:type owl:DatatypeProperty ." % _iri(termId, ns))
            xsd = {"boolean": "xsd:boolean", "date": "xsd:date",
                   "number": "xsd:decimal", "text": "xsd:string",
                   "url": "xsd:anyURI"}.get(str(row["datatype"] or ""))
            if xsd:
                lines.append("%s rdfs:range %s ." % (_iri(termId, ns), xsd))
        elif kind == "relation":
            lines.append("%s rdf:type owl:ObjectProperty ." % _iri(termId, ns))
            if row["cardinality"] is not None and int(row["cardinality"]) == 1:
                lines.append("%s rdf:type owl:FunctionalProperty ." % _iri(termId, ns))
            symmetric = bool(row["symmetric"]) if "symmetric" in row.keys() else False
            if symmetric:
                lines.append("%s rdf:type owl:SymmetricProperty ." % _iri(termId, ns))
            transitive = bool(row["transitive"]) if "transitive" in row.keys() else False
            if transitive:
                lines.append("%s rdf:type owl:TransitiveProperty ." % _iri(termId, ns))
        parent = str(row["parent_term_id"] or "")
        if parent and parent in termsById:
            slot = ("rdfs:subClassOf" if kind == "concept"
                    else "rdfs:subPropertyOf")
            lines.append("%s %s %s ." % (_iri(termId, ns), slot, _iri(parent)))
        inverse = str(row["inverse_of"]) if "inverse_of" in row.keys() else ""
        if inverse and inverse in termsById:
            lines.append("%s owl:inverseOf %s ." % (_iri(termId, ns), _iri(inverse)))
        # G1：定义描述项——非空才出 rdfs:comment（空值零漂移，golden 稳定）
        definition = str(row["definition"] or "") if "definition" in row.keys() else ""
        if definition.strip():
            lines.append("%s rdfs:comment %s@zh ." % (_iri(termId, ns),
                                                      _literal(definition)))
        # G3 附加断言：等价/对齐独立成行，谓词按映射 kind 与本体侧 kind 选形
        for entry in _mappings(row):
            predicate = _KIND_PREDICATES.get(str(entry.get("kind") or ""))
            iri = str(entry.get("iri") or "")
            if not predicate or not iri:
                continue
            slot = predicate[0] if kind == "concept" else predicate[1]
            lines.append("%s %s <%s> ." % (_iri(termId, ns), slot, iri))

    return "\n".join(lines) + "\n"
