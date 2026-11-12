# -*- coding: utf-8 -*-
"""W5 diff 与规模边界（specs/2026-11-12 §7）：
假设注入→规则/函数结论 delta＋状态变化＋受影响主体集；scope 事实行数超限
显式拒"scope 过大"（不静默截断）；台账只追加（v46）。
"""

from __future__ import annotations

import asyncio

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.simulation import (
    SCOPE_FACT_CAP,
    ScopeTooLargeError,
    runSimulation,
)
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("device", "concept")
    registry.register("is_a", "relation")
    registry.register("risk_flag", "relation")
    registry.register("needs_maintenance", "relation")
    gate = productionAdmissionGate(s)
    engine = ForwardChainingEngine(s)
    # enforce 规则：risk_flag(D, high) ⇒ needs_maintenance(D, yes)
    engine.registerRule(
        "sim_risk_maint", "needs_maintenance",
        body=[{"atom": "risk_flag", "subject": "S", "object": "H"}],
        headSubjectVar="S",
        materialization="enforce", tenantId="default")
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


class TestDiff:
    def test_hypothesisTriggersRuleConclusionInCopy(self, kb):
        s, _registry, _gate = kb
        report = runSimulation(
            s, scope={"agentId": "default", "tenantId": "default"},
            hypotheses={"facts": [{"subjectLabel": "设备0",
                                   "predicateTermId": "risk_flag",
                                   "objectTerm": "high"}]})
        added = report["diff"]["added"]
        assert any(f["predicate_term_id"] == "needs_maintenance" and
                   f["object_term"] == "high" for f in added), \
            "假设注入→规则在副本推演出 needs_maintenance 结论"
        affected = report["diff"]["affected_subjects"]
        assert "设备0" in affected, "受影响主体集"
        assert report["diff"]["removed"] == [], "无撤销假设时 removed 空"

    def test_ledgerAppendOnly(self, kb):
        s, _registry, _gate = kb
        runSimulation(
            s, scope={"agentId": "default", "tenantId": "default"},
            hypotheses={"facts": [{"subjectLabel": "设备0",
                                   "predicateTermId": "risk_flag",
                                   "objectTerm": "high"}]})
        with s._lock:
            rows = s._conn.execute(
                "SELECT simulation_id, scope_json, hypothesis_json, diff_summary_json"
                " FROM ontology_simulations ORDER BY created_at").fetchall()
        assert len(rows) == 1, "台账只追加一行"
        diff = rows[0]["diff_summary_json"]
        assert "added" in diff
        # 台账不因重跑吞行（只追加语义）
        runSimulation(
            s, scope={"agentId": "default", "tenantId": "default"},
            hypotheses={"facts": [{"subjectLabel": "设备1",
                                   "predicateTermId": "risk_flag",
                                   "objectTerm": "high"}]})
        with s._lock:
            n = s._conn.execute("SELECT COUNT(*) AS n FROM ontology_simulations").fetchone()["n"]
        assert n == 2

    def test_scopeCapExplicitReject(self, kb):
        """scope 事实行数超上限：显式拒 ScopeTooLargeError（不静默截断）。"""
        s, _registry, _gate = kb
        import neurova.knowledge.ontology.simulation as sim_mod

        original = sim_mod.SCOPE_FACT_CAP
        try:
            sim_mod.SCOPE_FACT_CAP = 2
            with pytest.raises(ScopeTooLargeError, match="scope"):
                runSimulation(
                    s, scope={"agentId": "default", "tenantId": "default"},
                    hypotheses={"facts": []})
        finally:
            sim_mod.SCOPE_FACT_CAP = original
        assert SCOPE_FACT_CAP >= 1
