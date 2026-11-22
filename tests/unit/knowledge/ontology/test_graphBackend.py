# -*- coding: utf-8 -*-
"""U8 图存储门面（specs/2026-11-22 参照系 ae 计划 D-U4/U8）。

三组判据：
1. **契约对拍**——同一组用例参数化跑 SQLiteBackend（既有 KnowledgeFactStore
   包装）与 OxigraphBackend（pyoxigraph 嵌入式 RDF，可选依赖缺席 skip 并注明）；
2. **注册表解析**——默认 sqlite／未知值显式报错／pyoxigraph 缺席显式
   not_supported（不静默降级回 sqlite）；
3. **默认档行为保持**——graph_exchange 行来源接门面后，sqlite 档取行与
   既有 SQL 逐行一致，导出文本确定性不变。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.export.graph_exchange import (
    exportGraphML,
    exportGexf,
)
from neurova.knowledge.ontology.graph_backend import (
    GRAPH_BACKEND_ENV,
    GraphBackendNotSupported,
    OxigraphBackend,
    SQLiteBackend,
    resolveGraphBackend,
)


# ── 契约对拍：两实现同一组用例 ─────────────────────────────────


def _sqliteBackend(tmp_path, request):
    store = KnowledgeFactStore(str(tmp_path / "graph_backend.db"))
    request.addfinalizer(store.close)
    return SQLiteBackend(store)


def _oxigraphBackend():
    pytest.importorskip(
        "pyoxigraph",
        reason="pyoxigraph 未安装——U8 可选依赖（fail-soft），安装后本参数实跑",
    )
    return OxigraphBackend()


@pytest.fixture(params=["sqlite", "oxigraph"], ids=["sqlite", "oxigraph"])
def backend(request, tmp_path):
    if request.param == "sqlite":
        return _sqliteBackend(tmp_path, request)
    return _oxigraphBackend()


class TestBackendContract:
    def test_backendName(self, backend):
        assert backend.backendName() in ("sqlite", "oxigraph")

    def test_writeAndReadConceptTerms(self, backend):
        backend.writeConceptTerm(tenantId="default", termId="z_term", label="最后")
        backend.writeConceptTerm(tenantId="default", termId="a_term", label="最先")
        backend.writeConceptTerm(tenantId="default", termId="m_term", label="居中")
        rows = backend.conceptTerms("default")
        written = [r for r in rows if r["term_id"] in ("a_term", "m_term", "z_term")]
        assert [(r["term_id"], r["kind"], r["label"]) for r in written] == [
            ("a_term", "concept", "最先"),
            ("m_term", "concept", "居中"),
            ("z_term", "concept", "最后"),
        ]

    def test_conceptTermsOnlyConceptKind(self, backend):
        backend.writeConceptTerm(tenantId="default", termId="c1", label="概念")
        backend.writeConceptTerm(tenantId="default", termId="r1", label="关系",
                                 kind="relation")
        rows = backend.conceptTerms("default")
        ids = [r["term_id"] for r in rows]
        assert "c1" in ids and "r1" not in ids

    def test_conceptTermsTenantScoped(self, backend):
        backend.writeConceptTerm(tenantId="t1", termId="c1", label="甲租户")
        assert [r["term_id"] for r in backend.conceptTerms("t1")] == ["c1"]
        assert backend.conceptTerms("t2") == []

    def test_writeAndReadTriple(self, backend):
        handle = backend.writeTriple(
            tenantId="default", agentId="default", subjectLabel="设备A",
            predicateTermId="linked", objectTerm="设备B")
        assert handle
        rows = backend.activeTriples("default", "default")
        assert rows == [{"subject_label": "设备A", "predicate_term_id": "linked",
                         "object_term": "设备B"}]

    def test_activeTriplesOrdered(self, backend):
        for subject, predicate, obj in (
                ("设备B", "linked", "设备A"),
                ("设备A", "linked", "设备B"),
                ("设备A", "is_a", "device")):
            backend.writeTriple(tenantId="default", agentId="default",
                                subjectLabel=subject, predicateTermId=predicate,
                                objectTerm=obj)
        rows = backend.activeTriples("default", "default")
        assert [(r["subject_label"], r["predicate_term_id"], r["object_term"])
                for r in rows] == [
            ("设备A", "is_a", "device"),
            ("设备A", "linked", "设备B"),
            ("设备B", "linked", "设备A"),
        ]

    def test_activeTriplesAgentFilter(self, backend):
        for agent in ("a1", "a2"):
            backend.writeTriple(tenantId="default", agentId=agent,
                                subjectLabel="设备-%s" % agent,
                                predicateTermId="linked", objectTerm="设备X")
        a1 = backend.activeTriples("default", "a1")
        assert [r["subject_label"] for r in a1] == ["设备-a1"]
        both = backend.activeTriples("default", "")
        assert [r["subject_label"] for r in both] == ["设备-a1", "设备-a2"]

    def test_activeTriplesTenantScoped(self, backend):
        for tenant in ("t1", "t2"):
            backend.writeTriple(tenantId=tenant, agentId="default",
                                subjectLabel="设备-%s" % tenant,
                                predicateTermId="linked", objectTerm="设备X")
        assert ([r["subject_label"] for r in backend.activeTriples("t1", "default")]
                == ["设备-t1"])
        assert backend.activeTriples("t3", "default") == []

    def test_rewriteSameTripleSameHandle(self, backend):
        first = backend.writeTriple(tenantId="default", agentId="default",
                                    subjectLabel="设备A", predicateTermId="linked",
                                    objectTerm="设备B")
        second = backend.writeTriple(tenantId="default", agentId="default",
                                     subjectLabel="设备A", predicateTermId="linked",
                                     objectTerm="设备B")
        assert first == second
        assert len(backend.activeTriples("default", "default")) == 1


# ── 注册表解析 ────────────────────────────────────────────────


class TestRegistry:
    def test_defaultResolvesSqlite(self, tmp_path, monkeypatch):
        monkeypatch.delenv(GRAPH_BACKEND_ENV, raising=False)
        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            resolved = resolveGraphBackend(store)
        finally:
            store.close()
        assert isinstance(resolved, SQLiteBackend)
        assert resolved.backendName() == "sqlite"

    def test_explicitSqliteValue(self, tmp_path, monkeypatch):
        monkeypatch.setenv(GRAPH_BACKEND_ENV, "sqlite")
        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            assert isinstance(resolveGraphBackend(store), SQLiteBackend)
        finally:
            store.close()

    def test_envValueNormalized(self, tmp_path, monkeypatch):
        monkeypatch.setenv(GRAPH_BACKEND_ENV, "  SQLite ")
        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            assert isinstance(resolveGraphBackend(store), SQLiteBackend)
        finally:
            store.close()

    def test_unknownValueExplicitError(self, tmp_path, monkeypatch):
        monkeypatch.setenv(GRAPH_BACKEND_ENV, "neo4j")
        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            with pytest.raises(ValueError, match="neo4j"):
                resolveGraphBackend(store)
        finally:
            store.close()

    def test_oxigraphMissingNotSupported(self, monkeypatch):
        import sys

        import neurova.knowledge.ontology.graph_backend as gb

        monkeypatch.setenv(GRAPH_BACKEND_ENV, "oxigraph")
        monkeypatch.setattr(gb, "_oxigraph_singleton", None)
        # 在 import 机制层面模拟未安装：走真实的惰性 import→fail-soft 转换路径
        monkeypatch.setitem(sys.modules, "pyoxigraph", None)
        with pytest.raises(GraphBackendNotSupported):
            resolveGraphBackend()

    def test_oxigraphResolvableWhenInstalled(self, monkeypatch):
        pytest.importorskip("pyoxigraph", reason="pyoxigraph 未安装（可选依赖）")
        import neurova.knowledge.ontology.graph_backend as gb

        monkeypatch.setenv(GRAPH_BACKEND_ENV, "oxigraph")
        monkeypatch.setattr(gb, "_oxigraph_singleton", None)
        try:
            resolved = resolveGraphBackend()
            assert isinstance(resolved, OxigraphBackend)
            assert resolved.backendName() == "oxigraph"
        finally:
            monkeypatch.setattr(gb, "_oxigraph_singleton", None)


# ── 默认档行为保持：接线的真实消费链路（graph_exchange）────────


@pytest.fixture
def kb(tmp_path):
    store = KnowledgeFactStore(str(tmp_path / "kb.db"))
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(store)
    registry.register("orders", "concept", label="订单")
    registry.register("is_a", "relation")
    gate = productionAdmissionGate(store)
    content = "订单X is_a orders"
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="订单X", predicateTermId="is_a",
        objectTerm="orders", content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]))
    yield store
    store.close()


class TestWiredExportUnchanged:
    def test_backendRowsMatchStoreSql(self, kb, monkeypatch):
        """默认 sqlite 档：门面取行与既有 SQL 逐行一致（行为保持的根判据）。"""
        monkeypatch.delenv(GRAPH_BACKEND_ENV, raising=False)
        backend = resolveGraphBackend(kb)
        assert backend.conceptTerms("default") == kb.queryReadOnly(
            "SELECT term_id, kind, label FROM ontology_terms"
            " WHERE tenant_id = ? AND kind = 'concept' ORDER BY term_id",
            ("default",))
        oracleSql = ("SELECT s.canonical_label AS subject_label,"
                     " f.predicate_term_id, f.object_term"
                     " FROM knowledge_facts f JOIN knowledge_subjects s"
                     " ON s.subject_key = f.subject_key"
                     " WHERE f.tenant_id = ? AND f.status = 'active'"
                     " AND f.record_kind = 'triple'"
                     " ORDER BY s.canonical_label, f.predicate_term_id,"
                     " f.object_term")
        unfiltered = kb.queryReadOnly(oracleSql, ("default",))
        assert backend.activeTriples("default", "") == unfiltered
        byAgent = [r for r in unfiltered if r["subject_label"] == "订单X"]
        assert backend.activeTriples("default", "default") == byAgent

    def test_exportGoesThroughFacade(self, kb, monkeypatch):
        """行来源确实经门面（注册无消费者即断点）。"""
        import neurova.knowledge.ontology.graph_backend as gb

        monkeypatch.delenv(GRAPH_BACKEND_ENV, raising=False)
        calls = []
        real = gb.resolveGraphBackend

        def spy(store):
            calls.append(store)
            return real(store)

        monkeypatch.setattr(gb, "resolveGraphBackend", spy)
        text = exportGraphML(kb, tenantId="default", agentId="default")
        assert calls == [kb]
        assert '<node id="orders"' in text
        assert "订单X" in text and "is_a" in text

    def test_exportDeterministicUnderDefault(self, kb, monkeypatch):
        monkeypatch.delenv(GRAPH_BACKEND_ENV, raising=False)
        first = exportGraphML(kb, tenantId="default", agentId="default")
        second = exportGexf(kb, tenantId="default", agentId="default")
        assert first == exportGraphML(kb, tenantId="default", agentId="default")
        assert second == exportGexf(kb, tenantId="default", agentId="default")
