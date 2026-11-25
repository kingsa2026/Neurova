# -*- coding: utf-8 -*-
"""KNOW-05：本体回滚前校验快照租户与目标租户一致。

审计定位（全仓逐文件审计报告 2026-11-25 §6 KNOW-05）：pipeline.rollback 按
baseline ID 取快照后直接恢复到调用方租户，不比较 row.tenant_id——可把他租户
本体快照写入本租户。判据：跨租户回滚显式拒绝（ValueError→API 400），本租户
现有行不被他租户快照改写。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.pipeline import OntologyPipeline
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def pipeline(tmp_path):
    store = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(store)
    engine = ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(st))
    yield OntologyPipeline(store, registry=registry, engine=engine), registry, engine, store
    store.close()


class TestRollbackTenantGuard:
    def test_rollbackRejectsCrossTenantBaseline(self, pipeline):
        """他租户的基线不得恢复进本租户。"""
        pipelineObj, registry, _engine, _store = pipeline
        result = pipelineObj.run(agentId="default", tenantId="acme",
                                 termUpserts=[], ruleRegistrations=[],
                                 factCandidates=[], reason="acme 基线")
        acmeBaseline = result["baselineId"]
        assert acmeBaseline, "acme 基线已冻结"

        registry.register("local_term", "concept", tenantId="default")

        with pytest.raises(ValueError, match="跨租户"):
            pipelineObj.rollback(toBaselineId=acmeBaseline, tenantId="default",
                                 actor="unit")
        assert registry.term("local_term", tenantId="default") is not None, \
            "拒绝后本租户现有行不被他租户快照改写"

    def test_rollbackWithinSameTenantStillWorks(self, pipeline):
        """同租户回滚不受影响（回归护栏）。"""
        pipelineObj, registry, _engine, _store = pipeline
        registry.register("keep_me", "concept", tenantId="acme")
        result = pipelineObj.run(agentId="default", tenantId="acme",
                                 termUpserts=[], ruleRegistrations=[],
                                 factCandidates=[], reason="acme 基线")
        registry.dropTerm("keep_me", tenantId="acme")

        pipelineObj.rollback(toBaselineId=result["baselineId"], tenantId="acme",
                             actor="unit")

        assert registry.term("keep_me", tenantId="acme") is not None, \
            "同租户回滚照常恢复"
