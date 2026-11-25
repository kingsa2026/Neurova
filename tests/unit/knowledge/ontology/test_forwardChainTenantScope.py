# -*- coding: utf-8 -*-
"""KNOW-02：前向链生产/消费/SQL 全链强制租户。

审计定位（全仓逐文件审计报告 2026-11-25 §6 KNOW-02）：
  - foundation/admission._derive 里前向链 fireFor 不传 tenantId；
  - rule_engine._fireRule 的单原子/两原子/接力链 SQL 与 _negatedHolds 不带 tenant。
影响：可跨租户组合前提，再写入目标租户结论与血缘。
判据咬合真实链路：真实 SQLite store + 生产准入闸 + 真实 ForwardChainingEngine
（含 rete_network 求值档），前提落在他租户、规则与本租户点火，跨租户前提
不得产出本租户结论。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


def _assertion(text: str) -> list:
    return [{"actorType": "pipeline", "actorId": "unit",
             "mediumRef": "unit:test", "statementText": text}]


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


@pytest.fixture
def engine(store):
    return ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
        st, toolVersion="unit"))


def _admit(store, subject, predicate, obj, tenantId):
    gate = productionAdmissionGate(store)
    content = "%s %s %s" % (subject, predicate, obj)
    gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content, tenantId=tenantId,
        assertions=_assertion(content)), allowPendingSegments=True)


def _tenantFactCount(store, tenantId, predicate):
    row = store._conn.execute(
        "SELECT COUNT(*) AS c FROM knowledge_facts"
        " WHERE tenant_id = ? AND predicate_term_id = ?",
        (tenantId, predicate)).fetchone()
    return int(row["c"])


class TestForwardChainTenantScope:
    def test_relayPremiseStaysInRequestTenant(self, store, engine):
        """单原子 relay：他租户前提不得推出本租户结论。"""
        registry = OntologyTermRegistry(store)
        registry.register("linked", "relation")
        registry.register("reachable", "relation")
        engine.registerRule(
            "reach_acme", "reachable",
            [{"atom": "linked", "subject": "S", "object": "O"}],
            headSubjectVar="S", materialization="enforce", tenantId="acme")
        _admit(store, "设备A", "linked", "设备B", tenantId="other")

        produced = engine.fireFor("default", "linked", tenantId="acme")

        assert produced == [], "acme 规则不得用 other 租户前提点火"
        assert _tenantFactCount(store, "acme", "reachable") == 0, \
            "跨租户前提不得在 acme 落结论"

    def test_twoAtomChainStaysInRequestTenant(self, store, engine):
        """两原子接力 JOIN：他租户前提链不得推出本租户结论。"""
        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation")
        engine.registerRule(
            "part_trans_acme", "part_of",
            [{"atom": "part_of", "subject": "X", "object": "Y"},
             {"atom": "part_of", "subject": "Y", "object": "Z"}],
            headSubjectVar="X", materialization="enforce", tenantId="acme")
        _admit(store, "甲", "part_of", "乙", tenantId="other")
        _admit(store, "乙", "part_of", "丙", tenantId="other")

        produced = engine.fireFor("default", "part_of", tenantId="acme")

        assert produced == [], "acme 传递规则不得用 other 租户前提链"
        assert _tenantFactCount(store, "acme", "part_of") == 0

    def test_negatedPremiseStaysInRequestTenant(self, store, engine):
        """带否定原子的规则：他租户前提（本租户无否定）不得在 acme 落结论。"""
        registry = OntologyTermRegistry(store)
        registry.register("linked", "relation")
        registry.register("excluded", "relation")
        registry.register("flagged", "relation")
        engine.registerRule(
            "flag_acme", "flagged",
            [{"atom": "linked", "subject": "X", "object": "Y"},
             {"not": "excluded", "subject": "X", "object": "Y"}],
            headSubjectVar="X", materialization="enforce", tenantId="acme")
        _admit(store, "设备A", "linked", "设备C", tenantId="other")

        produced = engine.fireFor("default", "linked", tenantId="acme")

        assert produced == [], "acme 否定规则不得用 other 租户前提"
        assert _tenantFactCount(store, "acme", "flagged") == 0

    def test_reteNetworkStrategyStaysInRequestTenant(self, store, engine):
        """rete_network 档同样不得跨租户组合前提（与 SQL 档同判据）。"""
        registry = OntologyTermRegistry(store)
        registry.register("linked", "relation")
        registry.register("reachable", "relation")
        engine.registerRule(
            "reach_acme", "reachable",
            [{"atom": "linked", "subject": "S", "object": "O"}],
            headSubjectVar="S", materialization="enforce", tenantId="acme")
        engine.setEvaluationStrategy("rete_network")
        _admit(store, "设备A", "linked", "设备B", tenantId="other")

        report = engine.fireAll(agentId="default", tenantId="acme")

        assert report["derived"] == [], "rete_network 档不得用 other 租户前提"
        assert _tenantFactCount(store, "acme", "reachable") == 0

    def test_admissionFiresForwardChainForRequestTenant(self, store):
        """admission._derive 必须按请求租户点火前向链（admission.py fireFor 传 tenant）。"""
        gate = productionAdmissionGate(store)
        wired = gate._collaborators["forward_chaining"]
        assert wired is not None, "生产门必须已接前向链引擎"
        registry = OntologyTermRegistry(store)
        registry.register("linked", "relation")
        registry.register("reachable", "relation")
        wired.registerRule(
            "reach_acme", "reachable",
            [{"atom": "linked", "subject": "S", "object": "O"}],
            headSubjectVar="S", materialization="enforce", tenantId="acme")

        content = "设备A linked 设备B"
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="设备A", predicateTermId="linked",
            objectTerm="设备B", content=content, tenantId="acme",
            assertions=_assertion(content)))

        assert _tenantFactCount(store, "acme", "reachable") >= 1, \
            "acme 的 admit 必须按 acme 租户点火前向链并落 acme 结论"
        assert _tenantFactCount(store, "default", "reachable") == 0, \
            "acme 的推导不得落进 default 租户"
