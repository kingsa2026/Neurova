# -*- coding: utf-8 -*-
"""术语「部分声明」的合并口径只有一个属主（承 §6-561「仍开」那条根因）。

现场：`PipelineTermUpsert` 直接喂 `registry.register()`，而 `register()` 是
INSERT OR REPLACE——批次里没声明的 aliases/external_iris/labels/module/identity_keys/
qualifier_schema 会被写回默认值。单条 PUT 面早就有「未提供即保留现值」的合并逻辑，
两处写面各写一份正是教义第 6 条要避免的双源；本轮把它收成注册表的一个方法，
REST PUT 与流水线 upsert 都走它。

判据只咬行为：
① 批次只改 label，其余声明逐栏保持；
② 显式空容器才是清空（`aliases: []` 真清掉）；
③ 批次里新术语仍拿默认裸值（不因为改成部分合并而写不出新行）；
④ 批次能声明 B8 关系特征（symmetric/transitive/aliases/external_iris/deprecated 等）；
⑤ REST PUT 不再抹掉 `namespace`/`iri_base` 这类没暴露的列；
⑥ 反向守卫：合并口径全仓只有一份实装（端点里不得再留 `_updateTermPayload`）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.pipeline import OntologyPipeline
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
PREFIX = "/v1/knowledge"
_ENDPOINTS = Path(__file__).resolve().parents[4] / "neurova" / "api" / "endpoints"


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
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    return TestClient(app)


def _declared(registry: OntologyTermRegistry) -> None:
    """一条把声明栏全填满的术语：任何一栏被写回默认值都看得见。"""
    registry.register(
        "RiskOrder", "concept", label="风险订单",
        aliases=["高危单"], externalIris={"skos_exactMatch": "http://example.org/RiskOrder"},
        identityKeys=["external_id"], labels={"zh": "风险订单", "en": "Risk Order"},
        altLabels={"zh": ["高危单"]}, module="domain",
        namespace="https://example.org/ns/", iriBase="https://example.org/base/",
        qualifierSchema={"level": {"required": True}}, version="v1")


@pytest.fixture
def seeded(store):
    _declared(OntologyTermRegistry(store))
    return store


def _runPipeline(store, termUpserts):
    registry = OntologyTermRegistry(store)
    engine = ForwardChainingEngine(store)
    pipeline = OntologyPipeline(store, registry=registry, engine=engine)
    return pipeline.run(agentId="default", tenantId="default",
                        termUpserts=termUpserts, ruleRegistrations=[],
                        factCandidates=[], reason="批次部分声明")


class TestPipelinePartialUpsert:
    def testBatchKeepsUndeclaredDeclarations(self, seeded):
        result = _runPipeline(seeded, [{
            "termId": "RiskOrder", "kind": "concept", "label": "风险订单改名"}])
        assert result["accepted"], result["summary"]
        term = OntologyTermRegistry(seeded).term("RiskOrder", tenantId="default")
        assert term["label"] == "风险订单改名"
        for column, expected in (
                ("aliases", ["高危单"]),
                ("external_iris", {"skos_exactMatch": "http://example.org/RiskOrder"}),
                ("identity_keys", ["external_id"]),
                ("labels", {"zh": "风险订单", "en": "Risk Order"}),
                ("alt_labels", {"zh": ["高危单"]}),
                ("module", "domain"),
                ("namespace", "https://example.org/ns/"),
                ("iri_base", "https://example.org/base/"),
                ("qualifier_schema", {"level": {"required": True}})):
            assert term[column] == expected, "%s 被批次写回默认值了" % column

    def testExplicitEmptyContainerStillClears(self, seeded):
        _runPipeline(seeded, [{
            "termId": "RiskOrder", "kind": "concept",
            "aliases": [], "labels": {}, "identityKeys": []}])
        term = OntologyTermRegistry(seeded).term("RiskOrder", tenantId="default")
        assert term["aliases"] == [] and term["labels"] == {}
        assert term["identity_keys"] == []
        # 只清这三栏，其余声明仍在
        assert term["module"] == "domain"
        assert term["external_iris"]["skos_exactMatch"]

    def testBatchStillCreatesFreshTerm(self, seeded):
        result = _runPipeline(seeded, [{
            "termId": "BrandNew", "kind": "concept", "label": "新术语"}])
        assert result["accepted"], result["summary"]
        term = OntologyTermRegistry(seeded).term("BrandNew", tenantId="default")
        assert term["aliases"] == [] and term["module"] == ""
        assert term["labels"] == {} and term["version"] == "v1"

    def testBatchDeclaresRelationFeatures(self, seeded):
        """批次面与单条写面对称：关系特征声明得出来，不再只有一半字段。"""
        result = _runPipeline(seeded, [
            {"termId": "batches_with", "kind": "relation", "label": "批次于",
             "aliases": ["批次关联"], "transitive": True, "cardinality": 1,
             "externalIris": {"skos_exactMatch": "http://example.org/bw"},
             "deprecated": True, "replacedBy": "RiskOrder"},
        ])
        assert result["accepted"], result["summary"]
        term = OntologyTermRegistry(seeded).term("batches_with", tenantId="default")
        assert term["transitive"] is True and term["cardinality"] == 1
        assert term["aliases"] == ["批次关联"]
        assert term["deprecated"] is True and term["replaced_by"] == "RiskOrder"
        assert term["external_iris"]["skos_exactMatch"] == "http://example.org/bw"


class TestRestPutKeepsHiddenColumns:
    def testPutLabelOnlyKeepsNamespaceAndIriBase(self, seeded, client):
        resp = client.put(PREFIX + "/ontology/terms/RiskOrder", json={
            "term_id": "RiskOrder", "kind": "concept", "label": "改名"})
        assert resp.status_code == 200, resp.text
        term = OntologyTermRegistry(seeded).term("RiskOrder", tenantId="default")
        assert term["label"] == "改名"
        assert term["namespace"] == "https://example.org/ns/"
        assert term["iri_base"] == "https://example.org/base/"

    def testPostStillWritesFreshRowWithoutPreexistingValues(self, seeded, client):
        resp = client.post(PREFIX + "/ontology/terms", json={
            "term_id": "post_only", "kind": "relation", "label": "POST 新行",
            "aliases": ["只此一栏"]})
        assert resp.status_code == 200, resp.text
        term = OntologyTermRegistry(seeded).term("post_only", tenantId="default")
        assert term["aliases"] == ["只此一栏"] and term["labels"] == {}


class TestMergeSingleSource:
    def testNoSecondMergeImplementationInEndpoints(self):
        """合并口径住在注册表；端点里再留一份 `_updateTermPayload` 就是双源。"""
        offenders = []
        for path in _ENDPOINTS.glob("knowledge_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {node.name for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if "_updateTermPayload" in names:
                offenders.append(path.name)
        assert offenders == [], "第二份「保留现值」合并实装又长回来了：%s" % offenders

    def testRegistryExposesTheOneMergePoint(self, seeded):
        registry = OntologyTermRegistry(seeded)
        assert hasattr(registry, "declarePartial")
        # 现值补齐走的是同一份字段表，不是端点手抄的清单
        term = registry.declarePartial("RiskOrder", "concept",
                                       {"label": "走单点合并"}, tenantId="default")
        assert term["label"] == "走单点合并"
        assert term["module"] == "domain" and term["aliases"] == ["高危单"]
