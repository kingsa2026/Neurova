# -*- coding: utf-8 -*-
"""B2：`POST /v1/knowledge/ontology/validate` dry-run 出口（升级计划 §5 B2）。

判据：五条校验目前只在唯一写咽喉内强制（validation.py 经 admission 段3），
外部无法只读试算。本端点把同一份判据开成只读出口——
  * 逐条候选回 `{index, subjectKey, findings, violations, verdict}` ＋ summary；
  * violation 不抛异常，如实进 verdict（写咽喉才拒写，dry-run 只报告）；
  * 纯只读：不落事实、不建主体、不写活动。
校验路径与 B6 流水线共用一份（`ontology/pipeline.py::dryRunFactCandidates`），
不许出现第二份"构造 AdmissionRequest→findings"的平行实现。
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints.knowledge_ontology import (
    OntologyValidateRequest,
    validateOntologyCandidates,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
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
def client(store):
    from neurova.api.endpoints import knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
    return TestClient(app)


def _setupTerms(store):
    """person/city/lives_in 三件套：domain 违规与干净用例的公共底座。"""
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "person", "kind": "concept"},
        {"termId": "city", "kind": "concept"},
        {"termId": "lives_in", "kind": "relation", "domain": ["person"],
         "rangeTerms": ["city"]},
    ])
    return registry


def _post(client, triples, agentId="a1"):
    return client.post(
        PREFIX + "/ontology/validate",
        json={"agentId": agentId, "triples": triples},
    )


class TestValidateEndpoint:
    def test_domainViolation_goesIntoVerdictNotAnException(self, store, client):
        """违规不抛异常：dry-run 的职责是如实报告，写咽喉才负责拒写。"""
        registry = _setupTerms(store)
        key = store.upsertSubject("a1", "甲")
        registry.assignSubjectType(key, "city")  # lives_in 定义域是 person → 违规

        resp = _post(client, [{"subjectLabel": "甲", "predicateTermId": "lives_in",
                               "objectTerm": "city"}])

        assert resp.status_code == 200, resp.text
        results = resp.json()["data"]["results"]
        assert len(results) == 1
        row = results[0]
        assert row["index"] == 0
        assert row["subjectKey"] == key, "缺省 subjectKey 按规范标签精确匹配"
        assert row["verdict"] == "violation"
        assert [v["rule"] for v in row["violations"]] == ["domain"]
        assert row["violations"][0]["subject_key"] == key
        assert resp.json()["data"]["summary"] == {
            "total": 1, "passed": 0, "violated": 1, "unregistered": 0}

    def test_unregisteredPredicate_reportsWithoutViolation(self, store, client):
        """未登记 ≠ 违规（validation 的保守原则）：如实进 findings，verdict 放行。"""
        resp = _post(client, [{"subjectLabel": "从未见过的主体",
                               "predicateTermId": "undeclared_pred",
                               "objectTerm": "某物"}])

        assert resp.status_code == 200, resp.text
        row = resp.json()["data"]["results"][0]
        assert row["subjectKey"] == "", "匹配不到主体就传空串"
        assert row["verdict"] == "pass"
        assert row["violations"] == []
        assert {f["kind"] for f in row["findings"]} == {"unregistered"}

    def test_cleanTriple_passesWithNoFindings(self, store, client):
        registry = _setupTerms(store)
        key = store.upsertSubject("a1", "甲")
        registry.assignSubjectType(key, "person")

        resp = _post(client, [{"subjectLabel": "甲", "predicateTermId": "lives_in",
                               "objectTerm": "city"}])

        row = resp.json()["data"]["results"][0]
        assert row["verdict"] == "pass"
        assert row["findings"] == []

    def test_explicitSubjectKey_isUsedVerbatim(self, store, client):
        registry = _setupTerms(store)
        key = store.upsertSubject("a1", "甲")
        registry.assignSubjectType(key, "person")

        resp = _post(client, [{"subjectLabel": "对不上的标签", "subjectKey": key,
                               "predicateTermId": "lives_in", "objectTerm": "city"}])

        row = resp.json()["data"]["results"][0]
        assert row["subjectKey"] == key, "显式 subjectKey 原样生效，不走标签匹配"
        assert row["verdict"] == "pass"

    def test_emptyPredicate_isRejectedWithReason(self, client):
        resp = _post(client, [{"subjectLabel": "甲", "predicateTermId": "",
                               "objectTerm": "x"}])
        assert resp.status_code == 400, resp.text

    def test_summaryCounts_mixedBatch(self, store, client):
        registry = _setupTerms(store)
        key = store.upsertSubject("a1", "甲")
        registry.assignSubjectType(key, "person")
        otherKey = store.upsertSubject("a1", "乙")
        registry.assignSubjectType(otherKey, "city")  # lives_in 定义域 person → 违规

        resp = _post(client, [
            {"subjectLabel": "甲", "predicateTermId": "lives_in", "objectTerm": "city"},
            {"subjectLabel": "甲", "predicateTermId": "undeclared_pred", "objectTerm": "x"},
            {"subjectLabel": "陌生主体", "predicateTermId": "lives_in", "objectTerm": "city"},
            {"subjectLabel": "乙", "predicateTermId": "lives_in", "objectTerm": "city"},
        ])

        summary = resp.json()["data"]["summary"]
        assert summary["total"] == 4
        assert summary["violated"] == 1, "第 4 条 domain 违规"
        assert summary["passed"] == 3
        assert summary["unregistered"] == 2, "第 2 条谓词未登记＋第 3 条主体未登记"

    def test_dryRunIsReadOnly_noFactNoSubjectNoBaseline(self, store, client):
        registry = _setupTerms(store)
        store.upsertSubject("a1", "甲")

        _post(client, [{"subjectLabel": "甲", "predicateTermId": "lives_in",
                        "objectTerm": "city"}])
        _post(client, [{"subjectLabel": "新主体不该被建", "predicateTermId": "x_pred",
                        "objectTerm": "y"}])

        assert store.factCount() == 0, "validate 不落事实"
        assert store.subjectCount() == 1, "validate 不建主体"
        assert store.listBaselines() == [], "validate 不写基线"

    def test_validatorFailure_surfacesAsExplicit5xxWithReason(self, store, client, monkeypatch):
        """fail-soft：校验器异常回显式 5xx 带原因，不吞不假装干净。"""
        _setupTerms(store)

        class ExplodingReport:
            def findings(self, request, subjectKey):
                raise RuntimeError("注册表读数炸了")

        monkeypatch.setattr(
            "neurova.knowledge.ontology.pipeline.OntologyValidationReport",
            lambda registry: ExplodingReport())

        resp = _post(client, [{"subjectLabel": "甲", "predicateTermId": "lives_in",
                               "objectTerm": "city"}])
        assert resp.status_code == 500, resp.text
        assert "注册表读数炸了" in resp.text

    def test_tenCandidates_smokeWithin50ms(self, store):
        """性能冒烟（升级计划 §5 B2）：10 条候选 < 50ms（SQLite 本地读）。"""
        _setupTerms(store)
        key = store.upsertSubject("a1", "甲")
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        OntologyTermRegistry(store).assignSubjectType(key, "person")
        candidates = [
            {"subjectLabel": "甲", "predicateTermId": "lives_in", "objectTerm": "city"}
            for _ in range(10)
        ]

        started = time.perf_counter()
        result = asyncio.run(validateOntologyCandidates(
            body=OntologyValidateRequest(agentId="a1", triples=candidates),
            current_user=dict(ADMIN)))
        elapsedMs = (time.perf_counter() - started) * 1000

        assert result["data"]["summary"]["total"] == 10
        assert elapsedMs < 50, "10 条候选耗时 %.1fms，超出 50ms 预算" % elapsedMs
