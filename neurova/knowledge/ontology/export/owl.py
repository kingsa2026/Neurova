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

from ..term_registry import versionedIri

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
        "@prefix kbg: <https://neurova.local/knowledge/> .",
    ]
    if version:
        lines.append("kbg: ontology:versionInfo \"%s\" ; owl:versionIRI <%s> ."
                     % (version, versionedIri("ontology", version)))
    termsById = {str(r["term_id"]): r for r in termRows}

    # G3：本体 IRI 恒为 kbg:——外部名只出现在附加断言的宾语位。
    def _iri(termId: str) -> str:
        return "kbg:%s" % termId

    def _mappings(row: Any) -> list:
        if "external_iris_json" not in row.keys():
            return []
        raw = json.loads(row["external_iris_json"] or "[]")
        return raw if isinstance(raw, list) else []

    for row in termRows:
        termId = str(row["term_id"])
        kind = row["kind"]
        if kind == "concept":
            lines.append("%s rdf:type owl:Class ." % _iri(termId))
        elif kind == "relation":
            lines.append("%s rdf:type owl:ObjectProperty ." % _iri(termId))
            if row["cardinality"] is not None and int(row["cardinality"]) == 1:
                lines.append("%s rdf:type owl:FunctionalProperty ." % _iri(termId))
            symmetric = bool(row["symmetric"]) if "symmetric" in row.keys() else False
            if symmetric:
                lines.append("%s rdf:type owl:SymmetricProperty ." % _iri(termId))
            transitive = bool(row["transitive"]) if "transitive" in row.keys() else False
            if transitive:
                lines.append("%s rdf:type owl:TransitiveProperty ." % _iri(termId))
        parent = str(row["parent_term_id"] or "")
        if parent and parent in termsById:
            slot = ("rdfs:subClassOf" if kind == "concept"
                    else "rdfs:subPropertyOf")
            lines.append("%s %s %s ." % (_iri(termId), slot, _iri(parent)))
        inverse = str(row["inverse_of"]) if "inverse_of" in row.keys() else ""
        if inverse and inverse in termsById:
            lines.append("%s owl:inverseOf %s ." % (_iri(termId), _iri(inverse)))
        # G3 附加断言：等价/对齐独立成行，谓词按映射 kind 与本体侧 kind 选形
        for entry in _mappings(row):
            predicate = _KIND_PREDICATES.get(str(entry.get("kind") or ""))
            iri = str(entry.get("iri") or "")
            if not predicate or not iri:
                continue
            slot = predicate[0] if kind == "concept" else predicate[1]
            lines.append("%s %s <%s> ." % (_iri(termId), slot, iri))

    return "\n".join(lines) + "\n"
