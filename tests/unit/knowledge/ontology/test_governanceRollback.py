# -*- coding: utf-8 -*-
"""B12 L8 治理层（升级计划 §12.9）：基线回滚/变更审计/语义版本。

回滚逐字恢复 terms/rules/shapes 且追加变更日志（不物理删除历史）；
规则回退后旧推导经账本精确撤销；审计只追加；语义版本规则判定。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.pipeline import OntologyPipeline
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.semver import bumpVersion, compareVersions, isSemver
from neurova.knowledge.ontology.shapes import ShapeRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def pipeline(store):
    registry = OntologyTermRegistry(store)
    engine = ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(st))
    return OntologyPipeline(store, registry=registry, engine=engine), registry, engine


def _latestBaseline(store):
    with store._lock:
        row = store._conn.execute(
            "SELECT baseline_id FROM knowledge_baselines"
            " WHERE scope = 'ontology_pipeline'"
            " ORDER BY created_at DESC, baseline_id DESC LIMIT 1").fetchone()
    return row["baseline_id"]


def _facts(store, predicate):
    return [f for f in store.searchableFacts(agentId="default")
            if f["predicate_term_id"] == predicate]


class TestSemver:
    def test_isSemverAndLegacy(self):
        assert isSemver("1.2.3")
        assert not isSemver("v3"), "vN 是存量形状不是 semver"
        assert not isSemver("第3版")

    def test_compareAndBump(self):
        assert compareVersions("1.2.3", "1.2.10") < 0
        assert bumpVersion("1.2.3", "patch") == "1.2.4"
        assert bumpVersion("1.2.3", "minor") == "1.3.0"
        assert bumpVersion("1.2.3", "major") == "2.0.0"


class TestGovernanceRollback:
    def test_rollbackRestoresTermsRulesShapes(self, store, pipeline):
        """回滚逐字恢复：基线后改掉的术语/规则/形状，回滚后与快照逐字一致。"""
        pipelineObj, registry, engine = pipeline
        registry.register("keep_me", "concept")
        result = pipelineObj.run(agentId="default", tenantId="default",
                                 termUpserts=[], ruleRegistrations=[],
                                 factCandidates=[], reason="基线")
        baselineId = result["baselineId"]

        registry.dropTerm("keep_me")
        engine.registerRule("rogue_rule", "rogue_pred",
                            [{"atom": "rogue_pred", "subject": "X", "object": "Y"}])
        ShapeRegistry(store).register(tenantId="default", shapeId="rogue_shape",
                                      targetKind="relation", targetTermId="rogue_pred",
                                      pathJson={"predicate": "rogue_pred"},
                                      constraintKind="in",
                                      constraintJson={"values": ["x"]},
                                      severity="warning", message="rogue")

        pipelineObj.rollback(toBaselineId=baselineId, tenantId="default", actor="unit")

        assert registry.term("keep_me") is not None, "被删术语恢复"
        assert engine.rule("rogue_rule") is None, "基线外规则退场"
        assert all(s["shape_id"] != "rogue_shape"
                   for s in ShapeRegistry(store).list(tenantId="default")), \
            "基线外形状退场"

    def test_rollbackAppendsChangeAudit(self, store, pipeline):
        """回滚追加变更日志（只追加账，不物理删除历史行）。"""
        pipelineObj, registry, _engine = pipeline
        result = pipelineObj.run(agentId="default", tenantId="default",
                                 termUpserts=[], ruleRegistrations=[],
                                 factCandidates=[], reason="基线")
        baselineId = result["baselineId"]
        registry.register("extra_term", "concept")

        pipelineObj.rollback(toBaselineId=baselineId, tenantId="default", actor="auditor")

        from neurova.knowledge.ontology.change_log import ChangeLog
        entries = ChangeLog(store).list(tenantId="default")
        assert entries, "回滚必须留审计账"
        assert all(e["change_id"] for e in entries), "审计行带 id"

    def test_rollbackRetractsDerivationsOfRetiredRules(self, store, pipeline):
        """规则回退后旧结论残留 = 拿死规则对外检索——回滚必须撤销受影响推导。

        knows 在基线前登记（无传递声明），基线后翻转 transitive → 推导 →
        回滚恢复术语行（transitive=0）→ ensureAutoRules 退场 auto 规则 →
        账本精确撤销推导；原始事实不陪葬。
        """
        pipelineObj, registry, engine = pipeline
        registry.register("knows", "relation")          # 基线前：无传递声明
        pipelineObj.run(agentId="default", tenantId="default",
                        termUpserts=[], ruleRegistrations=[], factCandidates=[],
                        reason="基线")

        gate = productionAdmissionGate(store)

        def _admit(subject, obj):
            content = "%s knows %s" % (subject, obj)
            gate.admit(AdmissionRequest(
                agentId="default", subjectLabel=subject, predicateTermId="knows",
                objectTerm=obj, content=content,
                assertions=[{"actorType": "pipeline", "actorId": "unit",
                             "mediumRef": "unit:test", "statementText": content}]))

        _admit("甲", "乙")
        _admit("乙", "Super")

        registry.register("knows", "relation", transitive=True)
        engine.ensureAutoRules()
        engine.fireAll(agentId="default")
        assert any(f["object_term"] == "Super"
                   for f in store.searchableFacts(agentId="default")), "推导先在"

        pipelineObj.rollback(toBaselineId=_latestBaseline(store),
                             tenantId="default", actor="unit")

        assert registry.term("knows")["transitive"] is False, "术语行恢复到基线形状"
        derived = [f for f in store.searchableFacts(agentId="default")
                   if f["predicate_term_id"] == "knows" and f["object_term"] == "Super"
                   and f["canonical_label"] == "甲"]
        assert derived == [], "规则回退后旧推导经账本精确撤销（甲 knows Super 退场）"
        assert len(_facts(store, "knows")) == 2, "原始事实不陪葬"
