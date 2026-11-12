# -*- coding: utf-8 -*-
"""W9 SPARQL 只读端点与溯因（specs/2026-11-12 §10）：
SELECT/ASK 命中投影事实／写形拒／未装 rdflib 显式 501／超限拒；
溯因解释树含规则与事实引用＋缺失前提清单＋深度上限。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.abduction import explainGoal
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("device", "concept")
    registry.register("is_a", "relation")
    registry.register("linked", "relation")
    registry.register("reachable", "relation")
    gate = productionAdmissionGate(s)
    engine = ForwardChainingEngine(s, gateFactory=lambda st: productionAdmissionGate(st))
    engine.registerRule(
        "reach_base", "reachable",
        body=[{"atom": "linked", "subject": "S", "object": "O"}],
        headSubjectVar="S", materialization="enforce", tenantId="default")
    content = "设备A is_a device"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="设备A", predicateTermId="is_a",
        objectTerm="device", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))
    content2 = "设备A linked 设备B"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="设备A", predicateTermId="linked",
        objectTerm="设备B", content=content2,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content2}]))
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="设备A", predicateTermId="reachable",
        objectTerm="设备B", content="设备A reachable 设备B",
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test",
                     "statementText": "设备A reachable 设备B"}]))
    yield s, registry, gate, engine
    s.close()


class TestSparql:
    def test_rdflibUnavailableExplicit501(self, kb, monkeypatch):
        """未装 rdflib：显式 501 not_supported（不静默降级）。"""
        s, _registry, _gate, _engine = kb
        from neurova.knowledge.ontology import sparql_query

        monkeypatch.setattr(sparql_query, "_rdflibAvailable", lambda: False)
        with pytest.raises(sparql_query.SparqlNotSupported):
            sparql_query.runSparqlQuery(s, "SELECT ?s WHERE { ?s ?p ?o } LIMIT 10",
                                        agentId="default", tenantId="default")

    def test_writeFormRejected(self, kb, monkeypatch):
        """UPDATE/CONSTRUCT 写形不支持（投影只读）。"""
        s, _registry, _gate, _engine = kb
        from neurova.knowledge.ontology import sparql_query

        monkeypatch.setattr(sparql_query, "_rdflibAvailable", lambda: True)
        with pytest.raises(ValueError, match="只读"):
            sparql_query.runSparqlQuery(
                s, "INSERT DATA { <a> <b> <c> }",
                agentId="default", tenantId="default")

    def test_selectHitsProjection(self, kb, monkeypatch):
        rdflib = pytest.importorskip("rdflib")
        s, _registry, _gate, _engine = kb
        from neurova.knowledge.ontology import sparql_query

        monkeypatch.setattr(sparql_query, "_rdflibAvailable", lambda: True)
        result = sparql_query.runSparqlQuery(
            s, "PREFIX kbg: <https://neurova.local/knowledge/>"
               " SELECT ?s ?o WHERE { ?s kbg:linked ?o } LIMIT 10",
            agentId="default", tenantId="default")
        assert result["rows"], "SELECT 命中投影事实"
        assert result["row_count"] <= sparql_query.MAX_SPARQL_ROWS


class TestAbduction:
    def test_explanationTreeWithRuleAndFacts(self, kb):
        """目标→解释树：规则引用＋事实引用＋缺失前提清单。"""
        s, _registry, _gate, _engine = kb
        result = explainGoal(
            s, subjectLabel="设备A", predicate="linked", objectTerm="设备B",
            agentId="default", tenantId="default")
        assert result["satisfied"] is True
        assert result["steps"], "解释树有步骤"
        assert any(step["fact_id"] for step in result["steps"]), "事实引用"

    def test_missingPremiseListed(self, kb):
        """前提缺失：satisfied=False＋缺失前提清单（候选不是断言，零写）。"""
        s, _registry, _gate, _engine = kb
        result = explainGoal(
            s, subjectLabel="设备A", predicate="linked", objectTerm="设备Z",
            agentId="default", tenantId="default")
        assert result["satisfied"] is False
        assert result["missing"], "缺失前提清单"

    def test_depthCap(self, kb):
        from neurova.knowledge.ontology.abduction import MAX_ABDUCTION_DEPTH

        assert MAX_ABDUCTION_DEPTH >= 1
        s, _registry, _gate, _engine = kb
        result = explainGoal(
            s, subjectLabel="设备A", predicate="linked", objectTerm="设备B",
            agentId="default", tenantId="default", maxDepth=0)
        assert result["satisfied"] is False, "深度 0＝无解释"

    def test_zeroFactWrite(self, kb):
        s, _registry, _gate, _engine = kb
        before = len(s.factsForSubject(s.resolveSubjectKey("default", "设备A")))
        explainGoal(s, subjectLabel="设备A", predicate="reachable",
                    objectTerm="设备C", agentId="default", tenantId="default")
        assert len(s.factsForSubject(s.resolveSubjectKey("default", "设备A"))) == before, \
            "溯因只读零写（解释是候选不是断言）"
