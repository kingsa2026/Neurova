# -*- coding: utf-8 -*-
"""B12 L7：五格式互操作导出（升级计划 §12.8）——Turtle/JSON-LD/OWL 公理/SHACL/PROV-O。

全部逐字节确定（排序固定）；RDF 1.1 基线；零第三方依赖。
"""

from __future__ import annotations

import json

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    registry = OntologyTermRegistry(s)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单"},
        {"termId": "HighRiskOrder", "kind": "concept", "parentTermId": "Order"},
        {"termId": "hasRiskLevel", "kind": "relation", "domain": ["Order"]},
    ])
    gate = productionAdmissionGate(s)
    content = "订单D01 is_a HighRiskOrder"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="订单D01", predicateTermId=IS_A_PREDICATE,
        objectTerm="HighRiskOrder", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}]))
    yield s
    s.close()


class TestInteropExports:
    def test_jsonldExportDeterministicWithGraph(self, store):
        from neurova.knowledge.ontology.export.jsonld import exportJsonLd

        first = exportJsonLd(store, tenantId="default")
        second = exportJsonLd(store, tenantId="default")

        assert first == second, "JSON-LD 逐字节确定"
        doc = json.loads(first)
        assert doc["@context"]["kbg"] == "https://neurova.local/knowledge/"
        graph = doc["@graph"]
        assert any(g.get("rdf_type") or g.get("@type") for g in graph), "is_a 进图"

    def test_owlAxiomsExport(self, store):
        from neurova.knowledge.ontology.export.owl import exportOwlAxioms

        doc = exportOwlAxioms(store, tenantId="default")

        assert "rdfs:subClassOf" in doc, "概念父类出子类公理"
        assert "Declaration" in doc or "Class" in doc

    def test_shaclShapesExport(self, store):
        from neurova.knowledge.ontology.shapes import ShapeRegistry
        from neurova.knowledge.ontology.export.shacl import exportShaclShapes

        ShapeRegistry(store).register(
            tenantId="default", shapeId="risk_enum", targetKind="relation",
            targetTermId="hasRiskLevel", pathJson={"predicate": "hasRiskLevel"},
            constraintKind="in", constraintJson={"values": ["High", "Low"]},
            severity="violation", message="风险等级取值越界")

        doc = exportShaclShapes(store, tenantId="default")

        assert "sh:NodeShape" in doc or "NodeShape" in doc
        assert "hasRiskLevel" in doc

    def test_provExportFromLineage(self, store):
        from neurova.knowledge.ontology.export.prov import exportProv

        doc = exportProv(store, tenantId="default")

        assert "entity" in doc or "activity" in doc, "PROV-O 形状含实体/活动段"

    def test_allFormatsDeterministic(self, store):
        from neurova.knowledge.ontology.export.jsonld import exportJsonLd
        from neurova.knowledge.ontology.export.owl import exportOwlAxioms
        from neurova.knowledge.ontology.export.prov import exportProv
        from neurova.knowledge.ontology.export.shacl import exportShaclShapes

        for export in (exportJsonLd, exportOwlAxioms, exportProv, exportShaclShapes):
            assert export(store, tenantId="default") == export(store, tenantId="default")
