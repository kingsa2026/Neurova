# -*- coding: utf-8 -*-
"""W11 九格式导出（specs/2026-11-12 §12）：GraphML/GEXF/Cypher/CSV 四新格式
确定性（两次逐字一致）＋闭集外 format 显式拒＋既有五格式不动。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.export.graph_exchange import (
    exportCsv,
    exportCypher,
    exportGexf,
    exportGraphML,
)


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("orders", "concept", label="订单")
    registry.register("is_a", "relation")
    gate = productionAdmissionGate(s)
    content = "订单X is_a orders"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="订单X", predicateTermId="is_a",
        objectTerm="orders", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))
    yield s
    s.close()


FORMAT_FUNCS = [exportGraphML, exportGexf, exportCypher, exportCsv]


class TestNewFormats:
    @pytest.mark.parametrize("func", FORMAT_FUNCS, ids=lambda f: f.__name__)
    def test_deterministic(self, kb, func):
        """同库内容两次导出逐字一致（确定性判据）。"""
        first = func(kb, tenantId="default", agentId="default")
        second = func(kb, tenantId="default", agentId="default")
        assert first == second

    def test_graphMLStructure(self, kb):
        text = exportGraphML(kb, tenantId="default", agentId="default")
        assert '<graphml xmlns=' in text
        assert '<node id=' in text and '<edge source=' in text

    def test_gexfStructure(self, kb):
        text = exportGexf(kb, tenantId="default", agentId="default")
        assert '<gexf xmlns=' in text
        assert '<node id=' in text and '<edge id=' in text

    def test_cypherCreate(self, kb):
        text = exportCypher(kb, tenantId="default", agentId="default")
        assert "CREATE (" in text
        assert "MATCH (" in text and "->" in text

    def test_csvSections(self, kb):
        text = exportCsv(kb, tenantId="default", agentId="default")
        assert "=== nodes ===" in text and "=== edges ===" in text
        assert "is_a" in text
