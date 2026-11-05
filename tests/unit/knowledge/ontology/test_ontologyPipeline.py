# -*- coding: utf-8 -*-
"""B6：本体构建流水线（升级计划 §5 B6）。

判据：`OntologyPipeline.run` 单批次原子——① 候选事实先全部 dry-run（复用 B2
的校验路径，任一 violation 整批拒绝、零落盘）；② 依次应用术语 upsert 与规则
登记（只登记不触发求值）；③ 写一行 `knowledge_baselines` 快照（复用既有表，
无新表）；④ 应用中途失败回滚本批已应用变更，不留半发布态。`diff` 给两基线
（或基线↔当前实况）之间 terms/rules 差异。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.pipeline import ONTOLOGY_PIPELINE_SCOPE, OntologyPipeline

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
ALICE = {"user_id": "1", "username": "alice", "role": "user", "tenant_id": "default"}
PREFIX = "/v1/knowledge"


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s
    )
    yield s
    s.close()


@pytest.fixture
def pipeline(store):
    return OntologyPipeline(store)


def _cleanTermUpserts():
    return [
        {"termId": "device", "kind": "concept", "label": "设备"},
        {"termId": "router", "kind": "concept", "label": "路由器", "parentTermId": "device"},
    ]


def _cleanRuleRegistrations():
    return [
        {"ruleId": "router_is_device", "headPredicate": "network_device",
         "body": [{"atom": "is_a", "subject": "X", "object": "Y"}]},
    ]


class TestPipelineRun:
    def test_violationCandidate_rejectsWholeBatchWithZeroWrites(self, store, pipeline):
        """任一候选违规 → 整批拒绝：术语、规则、基线一概不落。"""
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "person", "kind": "concept"},
            {"termId": "city", "kind": "concept"},
            {"termId": "lives_in", "kind": "relation", "domain": ["person"]},
        ])
        key = store.upsertSubject("a1", "甲")
        registry.assignSubjectType(key, "city")  # lives_in 定义域 person → 违规

        result = pipeline.run(
            agentId="a1", tenantId="default",
            termUpserts=_cleanTermUpserts(),
            ruleRegistrations=_cleanRuleRegistrations(),
            factCandidates=[{"subjectLabel": "甲", "predicateTermId": "lives_in",
                             "objectTerm": "某某市"}],
        )

        assert result["accepted"] is False
        assert result["baselineId"] == ""
        rejections = result["rejections"]
        assert len(rejections) == 1 and rejections[0]["index"] == 0
        assert rejections[0]["violations"][0]["rule"] == "domain"
        assert registry.term("device") is None, "违规批的术语不许落半行"
        assert registry.term("router") is None
        assert store.listBaselines(scope=ONTOLOGY_PIPELINE_SCOPE) == [], "不许写基线"
        assert store.factCount() == 0

    def test_cleanRun_appliesTermsRules_andWritesBaselineSnapshot(self, store, pipeline):
        result = pipeline.run(
            agentId="a1", tenantId="default",
            termUpserts=_cleanTermUpserts(),
            ruleRegistrations=_cleanRuleRegistrations(),
            factCandidates=[{"subjectLabel": "机房甲", "predicateTermId": "documented_as",
                             "objectTerm": "entry-1"}],
            createdBy="9", reason="首次成版",
        )

        assert result["accepted"] is True
        baselineId = result["baselineId"]
        assert baselineId.startswith("kb_")
        assert result["applied"] == {"terms": 2, "rules": 1, "facts": 1}

        registry = pipeline._registry
        assert registry.term("router")["parent_term_id"] == "device"
        rule = pipeline._engine.rule("router_is_device")
        assert rule and rule["enabled"], "规则已登记"
        assert store.factCount() == 0, "只登记不触发求值：无推导事实、无候选落库"

        baseline = store.baseline(baselineId)
        assert baseline["scope"] == ONTOLOGY_PIPELINE_SCOPE
        assert baseline["tenant_id"] == "default"
        assert baseline["created_by"] == "9"
        snapshot = baseline["snapshot"]
        assert {t["term_id"] for t in snapshot["terms"]} >= {"device", "router"}
        assert {r["rule_id"] for r in snapshot["rules"]} >= {"router_is_device"}

    def test_applyFailure_rollsBackPartialTerms_noHalfState(self, store, pipeline):
        """应用中途失败（坏术语形状）→ 本批已应用的变更整批回滚，无基线。"""
        with pytest.raises(ValueError, match="术语类别"):
            pipeline.run(
                agentId="a1", tenantId="default",
                termUpserts=[{"termId": "device", "kind": "concept"},
                             {"termId": "bad", "kind": "verb"}],
                ruleRegistrations=[],
                factCandidates=[],
            )

        assert pipeline._registry.term("device") is None, "半态必须被回滚"
        assert store.listBaselines(scope=ONTOLOGY_PIPELINE_SCOPE) == []

    def test_missingCandidateFields_rejected(self, pipeline):
        with pytest.raises(ValueError, match="predicateTermId"):
            pipeline.run(agentId="a1", tenantId="default",
                         factCandidates=[{"subjectLabel": "甲", "predicateTermId": "",
                                          "objectTerm": "x"}])


class TestPipelineDiff:
    def test_diff_betweenTwoBaselines_showsAddedTerms(self, store, pipeline):
        first = pipeline.run(agentId="a1", tenantId="default",
                             termUpserts=[{"termId": "device", "kind": "concept"}],
                             ruleRegistrations=[], factCandidates=[])
        second = pipeline.run(agentId="a1", tenantId="default",
                              termUpserts=[{"termId": "device", "kind": "concept"},
                                           {"termId": "router", "kind": "concept",
                                            "parentTermId": "device"}],
                              ruleRegistrations=[], factCandidates=[])

        report = pipeline.diff(first["baselineId"], second["baselineId"])

        assert report["fromBaselineId"] == first["baselineId"]
        assert report["toBaselineId"] == second["baselineId"]
        assert report["terms"]["added"] == ["router"]
        assert report["terms"]["removed"] == []
        assert report["terms"]["changed"] == []
        assert report["rules"] == {"added": [], "removed": [], "changed": []}

    def test_idempotentRerun_diffIsEmpty(self, store, pipeline):
        first = pipeline.run(agentId="a1", tenantId="default",
                             termUpserts=_cleanTermUpserts(),
                             ruleRegistrations=_cleanRuleRegistrations(),
                             factCandidates=[])
        second = pipeline.run(agentId="a1", tenantId="default",
                              termUpserts=_cleanTermUpserts(),
                              ruleRegistrations=_cleanRuleRegistrations(),
                              factCandidates=[])

        report = pipeline.diff(first["baselineId"], second["baselineId"])

        assert report["terms"]["added"] == []
        assert report["terms"]["changed"] == [], "同声明重放不算变更（时间戳除外）"
        assert report["rules"]["changed"] == []

    def test_diff_withoutToBaseline_comparesAgainstLiveState(self, store, pipeline):
        first = pipeline.run(agentId="a1", tenantId="default",
                             termUpserts=[{"termId": "device", "kind": "concept"}],
                             ruleRegistrations=[], factCandidates=[])
        pipeline._registry.register("router", "concept", tenantId="default")  # 实况漂移

        report = pipeline.diff(first["baselineId"])

        assert report["toState"] == "live"
        assert report["terms"]["added"] == ["router"]

    def test_unknownBaseline_raisesLookupError(self, pipeline):
        with pytest.raises(LookupError):
            pipeline.diff("kb_missing")

    def test_factBaseline_rejectedAsPipelineBaseline(self, store, pipeline):
        created = store.createBaseline(reason="事实基线")
        with pytest.raises(ValueError, match="不是本体流水线基线"):
            pipeline.diff(created["baseline_id"])


class TestPipelineEndpoints:
    @pytest.fixture
    def client(self, store):
        from neurova.api.endpoints import knowledge_ontology

        app = FastAPI()
        app.include_router(knowledge_ontology.router, prefix=PREFIX)
        holder = {"user": dict(ADMIN)}
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = (
            lambda: holder["user"]
        )
        return TestClient(app), holder

    def test_run_isAdminGated(self, client):
        client, holder = client
        holder["user"] = dict(ALICE)
        resp = client.post(PREFIX + "/ontology/pipeline/run", json={})
        assert resp.status_code == 403, resp.text

    def test_run_rejection_mapsTo400_withRejections(self, client, store):
        client, _holder = client
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "person", "kind": "concept"},
            {"termId": "city", "kind": "concept"},
            {"termId": "lives_in", "kind": "relation", "domain": ["person"]},
        ])
        key = store.upsertSubject("a1", "甲")
        registry.assignSubjectType(key, "city")

        resp = client.post(PREFIX + "/ontology/pipeline/run", json={
            "agentId": "a1",
            "termUpserts": [{"termId": "device", "kind": "concept"}],
            "factCandidates": [{"subjectLabel": "甲", "predicateTermId": "lives_in",
                                "objectTerm": "某某市"}],
        })

        assert resp.status_code == 400, resp.text
        detail = resp.json()["detail"]
        assert detail["rejections"][0]["violations"][0]["rule"] == "domain"
        assert store.listBaselines(scope=ONTOLOGY_PIPELINE_SCOPE) == []

    def test_run_happyPath_returnsBaselineId_andDiffWorks(self, client, store):
        client, _holder = client

        runResp = client.post(PREFIX + "/ontology/pipeline/run", json={
            "agentId": "a1",
            "termUpserts": _cleanTermUpserts(),
            "ruleRegistrations": _cleanRuleRegistrations(),
            "factCandidates": [{"subjectLabel": "机房甲",
                                "predicateTermId": "documented_as",
                                "objectTerm": "entry-1"}],
            "reason": "端点成版",
        })

        assert runResp.status_code == 200, runResp.text
        payload = runResp.json()["data"]
        assert payload["accepted"] is True
        assert payload["baselineId"].startswith("kb_")
        assert payload["applied"] == {"terms": 2, "rules": 1, "facts": 1}

        diffResp = client.get(
            PREFIX + "/ontology/pipeline/diff",
            params={"fromBaseline": payload["baselineId"]},
        )
        assert diffResp.status_code == 200, diffResp.text
        report = diffResp.json()["data"]
        assert report["toState"] == "live"

    def test_diff_unknownBaseline_mapsTo404(self, client):
        client, _holder = client
        resp = client.get(PREFIX + "/ontology/pipeline/diff",
                          params={"fromBaseline": "kb_missing"})
        assert resp.status_code == 404, resp.text
