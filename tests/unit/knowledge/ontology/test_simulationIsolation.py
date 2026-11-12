# -*- coding: utf-8 -*-
"""W5 Simulation 隔离红判（specs/2026-11-12 §7）：simulate 前后生产 fact 行数
与 user_version 逐字不变（副本只读生产、零生产写）；TTL 哨兵（临时副本即用即删）。
"""

from __future__ import annotations

import asyncio

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.simulation import runSimulation


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = None
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(s)
    registry.register("is_a", "relation")
    registry.register("risk_flag", "relation")
    gate = productionAdmissionGate(s)
    registry.register("device", "concept")
    for i in range(3):
        content = "设备%d is_a device" % i
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="设备%d" % i, predicateTermId="is_a",
            objectTerm="device", content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
        registry.assignSubjectType(s.resolveSubjectKey("default", "设备%d" % i), "device")
    yield s, registry, gate
    s.close()


def _snapshot(store):
    with store._lock:
        rows = store._conn.execute(
            "SELECT fact_id, subject_key, predicate_term_id, object_term, status"
            " FROM knowledge_facts ORDER BY fact_id").fetchall()
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
    return (version, [tuple(r) for r in rows])


class TestIsolation:
    def test_productionZeroWrite(self, kb):
        """隔离红判：simulate 前后生产 fact 行数与 user_version 逐字不变。"""
        s, _registry, _gate = kb
        before = _snapshot(s)
        report = runSimulation(
            s, scope={"agentId": "default", "tenantId": "default"},
            hypotheses={"facts": [{"subjectLabel": "设备0", "predicateTermId": "risk_flag",
                                   "objectTerm": "high"}]})
        assert report["diff"]["added"], "副本推演应产出新增结论"
        assert _snapshot(s) == before, "生产库逐字不变（零生产写）"

    def test_tempCopyCleanedUp(self, kb, tmp_path):
        """TTL 哨兵：副本临时文件在 run 结束后即删（不残留）。"""
        s, _registry, _gate = kb
        import glob
        import os

        runSimulation(
            s, scope={"agentId": "default", "tenantId": "default"},
            hypotheses={"facts": [{"subjectLabel": "设备0",
                                   "predicateTermId": "risk_flag",
                                   "objectTerm": "high"}]},
            workDir=str(tmp_path))
        leftovers = glob.glob(str(tmp_path / "kb.db-sim-*"))
        assert leftovers == [], "副本临时文件应即用即删"
