"""OWL 2 RL 公理导出（B12 L7）：互操作声明，不是运行时承诺（§12 语义边界）。

从术语表物化声明行：Declaration/Class、Declaration/ObjectProperty、
rdfs:subClassOf（概念父类）、rdfs:subPropertyOf（关系父属性）、
owl:inverseOf、owl:SymmetricProperty、owl:TransitiveProperty、
owl:FunctionalProperty（cardinality=1）。Turtle 语法，逐字节确定。
"""

from __future__ import annotations

from typing import Any

from ..term_registry import versionedIri


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
        "@prefix kbg: <https://neurova.local/knowledge/> .",
    ]
    if version:
        lines.append("kbg: ontology:versionInfo \"%s\" ; owl:versionIRI <%s> ."
                     % (version, versionedIri("ontology", version)))
    termsById = {str(r["term_id"]): r for r in termRows}

    def _iri(termId: str) -> str:
        row = termsById.get(str(termId))
        if row and "external_iris_json" in row.keys():
            import json as _json
            match = str((_json.loads(row["external_iris_json"] or "{}") or {})
                        .get("skos_exactMatch") or "")
            if match:
                return "<%s>" % match
        return "kbg:%s" % termId

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

    return "\n".join(lines) + "\n"
