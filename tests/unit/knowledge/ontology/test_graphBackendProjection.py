"""Oxigraph 导出投影必须跟随 SQLite 当前事实窗口。"""

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.export.graph_exchange import exportGraphML
from neurova.knowledge.ontology.graph_backend import GRAPH_BACKEND_ENV


def testOxigraphExportRebuildsFromAuthoritativeStore(tmp_path, monkeypatch):
    pytest.importorskip("pyoxigraph", reason="Oxigraph 可选依赖未安装")
    import neurova.knowledge.ontology.graph_backend as graphBackend

    store = KnowledgeFactStore(str(tmp_path / "projection.db"))
    monkeypatch.setattr(graphBackend, "_oxigraph_singleton", None)
    monkeypatch.setenv(GRAPH_BACKEND_ENV, "oxigraph")
    try:
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        OntologyTermRegistry(store).register("orders", "concept", label="订单")
        gate = productionAdmissionGate(store)
        statement = "订单X is_a orders"
        gate.admit(AdmissionRequest(
            agentId="a1", subjectLabel="订单X", predicateTermId="is_a",
            objectTerm="orders", content=statement,
            assertions=[{
                "actorType": "pipeline", "actorId": "projection-test",
                "mediumRef": "test:projection", "statementText": statement,
            }],
        ))

        text = exportGraphML(store, tenantId="default", agentId="a1")
        assert "订单X" in text
        assert 'id="orders"' in text

        replacement = "订单X is_a archived_orders"
        gate.admit(AdmissionRequest(
            agentId="a1", subjectLabel="订单X", predicateTermId="is_a",
            objectTerm="archived_orders", content=replacement,
            assertions=[{
                "actorType": "pipeline", "actorId": "projection-test",
                "mediumRef": "test:projection", "statementText": replacement,
            }],
        ))
        updated = exportGraphML(store, tenantId="default", agentId="a1")
        assert "archived_orders" in updated
        assert 'target="orders"' not in updated
    finally:
        store.close()
        monkeypatch.setattr(graphBackend, "_oxigraph_singleton", None)
