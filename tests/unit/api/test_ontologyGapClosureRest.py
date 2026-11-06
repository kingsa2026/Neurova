# -*- coding: utf-8 -*-
"""剩余三项缺口收口：质量报告 REST、企业源描述符提交 REST、术语声明字段写面。

判据只咬行为，不咬名字：
- 质量报告：写进去的坏形状必须在报告里点名，且两次读数逐字一致（导出确定性同款口径）；
- 企业源：合法描述符落库后列表可见，非法描述符整条拒且**零落库**，未启用态如实回显；
- 术语写面：labels/alt_labels/module/identity_keys/qualifier_schema 经 REST 写出来
  就能经 REST 读回去；PUT 未声明时保留现值；非法语言标记与 core→domain 翻转在写入处拒。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer", "tenant_id": "default"}
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
    from neurova.api.endpoints import knowledge_enterprise, knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    # 生产挂载点是 knowledge.py 聚合器（与 /ontology* 同级）；本档按域各挂一次。
    app.include_router(knowledge_enterprise.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    return TestClient(app)


def _seedPredicate(store: KnowledgeFactStore) -> OntologyTermRegistry:
    registry = OntologyTermRegistry(store)
    registry.register("Order", "concept", label="订单")
    registry.register("hasRiskLevel", "relation", label="有风险等级",
                      domain=["Order"])
    return registry


class TestQualityRest:
    def testReportNamesBadShapes(self, client, store):
        registry = _seedPredicate(store)
        registry.register("bare_term", "concept", label="")

        resp = client.get(PREFIX + "/ontology/quality")
        assert resp.status_code == 200
        data = resp.json()["data"]
        kinds = {(f["kind"], f["target"]) for f in data["findings"]}
        assert ("missingLabel", "bare_term") in kinds
        assert ("orphanClass", "bare_term") in kinds
        assert data["term_count"] == len(registry.terms(tenantId="default"))
        assert set(data["metrics"]) == {"consistency", "conciseness"}

    def testReportIsByteStable(self, client, store):
        _seedPredicate(store)
        first = client.get(PREFIX + "/ontology/quality").json()["data"]
        second = client.get(PREFIX + "/ontology/quality").json()["data"]
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def testViewerCanReadQuality(self, client):
        client.app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(VIEWER)
        assert client.get(PREFIX + "/ontology/quality").status_code == 200


class TestEnterpriseSourceRest:
    def testSubmitPersistsAndLists(self, client, store):
        _seedPredicate(store)
        body = {
            "source_id": "erp_orders",
            "descriptor": {
                "sourceType": "sql",
                "columns": ["order_id", "risk_level"],
                "subject": {"template": "订单{order_id}"},
                "predicate": {"termId": "hasRiskLevel"},
                "object": {"kind": "column", "column": "risk_level"},
            },
        }
        created = client.post(PREFIX + "/enterprise/sources", json=body)
        assert created.status_code == 200
        assert created.json()["data"]["enabled"] is False

        listed = client.get(PREFIX + "/enterprise/sources")
        assert listed.status_code == 200
        items = listed.json()["data"]["items"]
        assert [row["source_id"] for row in items] == ["erp_orders"]
        assert items[0]["descriptor"]["predicate"]["termId"] == "hasRiskLevel"

        one = client.get(PREFIX + "/enterprise/sources/erp_orders")
        assert one.status_code == 200
        assert one.json()["data"]["cursor"] == ""

    def testInvalidDescriptorRejectedAndNothingStored(self, client, store):
        _seedPredicate(store)
        body = {
            "source_id": "erp_bad",
            "descriptor": {
                "sourceType": "sql",
                "columns": ["order_id"],
                "subject": {"column": "order_id"},
                "predicate": {"termId": "not_registered"},
                "object": {"kind": "column", "column": "order_id"},
            },
        }
        resp = client.post(PREFIX + "/enterprise/sources", json=body)
        assert resp.status_code == 400
        assert "not_registered" in resp.json()["detail"]
        assert client.get(PREFIX + "/enterprise/sources").json()["data"]["items"] == []

    def testUnknownSourceTypeRejected(self, client, store):
        _seedPredicate(store)
        resp = client.post(PREFIX + "/enterprise/sources", json={
            "source_id": "x", "descriptor": {
                "sourceType": "carrier_pigeon", "columns": ["a"],
                "subject": {"column": "a"},
                "predicate": {"termId": "hasRiskLevel"},
                "object": {"kind": "literal", "value": "v"},
            }})
        assert resp.status_code == 400
        assert "carrier_pigeon" in resp.json()["detail"]

    def testNonAdminCannotSubmit(self, client, store):
        client.app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(VIEWER)
        resp = client.post(PREFIX + "/enterprise/sources",
                           json={"source_id": "x", "descriptor": {}})
        assert resp.status_code == 403

    def testDisabledSourceIngestsNothing(self, client, store):
        """关闸态（默认 enabled=False）在 REST 面上如实可见——摄取要真连接器，另立项。"""
        _seedPredicate(store)
        client.post(PREFIX + "/enterprise/sources", json={
            "source_id": "erp_orders", "descriptor": {
                "sourceType": "sql", "columns": ["order_id"],
                "subject": {"column": "order_id"},
                "predicate": {"termId": "hasRiskLevel"},
                "object": {"kind": "literal", "value": "High"}}})
        row = client.get(PREFIX + "/enterprise/sources/erp_orders").json()["data"]
        assert row["enabled"] is False
        assert row["adapter_registered"] is False


class TestTermDeclarationWriteRest:
    def testPostCarriesDeclarationFields(self, client, store):
        _seedPredicate(store)
        resp = client.post(PREFIX + "/ontology/terms", json={
            "term_id": "RiskOrder", "kind": "concept", "label": "风险订单",
            "parent_term_id": "Order",
            "labels": {"zh": "风险订单", "en": "Risk Order"},
            "alt_labels": {"zh": ["高危单"]},
            "module": "domain",
            "identity_keys": ["external_id"],
            "basis": "单测声明",
        })
        assert resp.status_code == 200
        items = client.get(PREFIX + "/ontology/terms").json()["data"]["items"]
        row = next(t for t in items if t["term_id"] == "RiskOrder")
        assert row["labels"] == {"zh": "风险订单", "en": "Risk Order"}
        assert row["alt_labels"] == {"zh": ["高危单"]}
        assert row["module"] == "domain"
        assert row["identity_keys"] == ["external_id"]

    def testPutKeepsDeclarationWhenOmitted(self, client, store):
        registry = _seedPredicate(store)
        registry.register("RiskOrder", "concept", parentTermId="Order",
                          labels={"zh": "风险订单"}, module="domain",
                          identityKeys=["external_id"])
        resp = client.put(PREFIX + "/ontology/terms/RiskOrder",
                          json={"term_id": "RiskOrder", "kind": "concept",
                                "label": "风险订单改"})
        assert resp.status_code == 200
        term = registry.term("RiskOrder", tenantId="default")
        assert term["label"] == "风险订单改"
        assert term["labels"] == {"zh": "风险订单"}
        assert term["module"] == "domain"
        assert term["identity_keys"] == ["external_id"]

    def testQualifierSchemaWrittenAndReadBack(self, client, store):
        resp = client.post(PREFIX + "/ontology/terms", json={
            "term_id": "shippedVia", "kind": "relation", "label": "经此运输",
            "domain": ["Order"],
            "qualifier_schema": {"carrier": {"required": True}},
        })
        assert resp.status_code == 200
        term = resp.json()["data"]["term"]
        assert term["qualifier_schema"] == {"carrier": {"required": True}}

    def testBadLangTagRejectedAtWrite(self, client, store):
        _seedPredicate(store)
        resp = client.post(PREFIX + "/ontology/terms", json={
            "term_id": "BadLang", "kind": "concept",
            "labels": {"中文": "不该收"},
        })
        assert resp.status_code == 400

    def testCoreModuleCannotFlipToDomain(self, client, store):
        registry = _seedPredicate(store)
        assert registry.term("is_a", tenantId="default")["module"] == "core"
        resp = client.put(PREFIX + "/ontology/terms/is_a", json={
            "term_id": "is_a", "kind": "relation", "module": "domain",
        })
        assert resp.status_code == 400

    def testPipelineTermUpsertCarriesDeclaration(self, client, store):
        """同一条根因的第二个写入口（B6 流水线）不许只有一半字段——批次里声明得出来。"""
        _seedPredicate(store)
        resp = client.post(PREFIX + "/ontology/pipeline/run", json={
            "agentId": "default",
            "termUpserts": [{
                "termId": "BatchOrder", "kind": "concept", "parentTermId": "Order",
                "labels": {"zh": "批次单"}, "module": "domain",
                "identityKeys": ["external_id"],
            }],
            "reason": "批次声明",
        })
        assert resp.status_code == 200, resp.json()
        term = OntologyTermRegistry(store).term("BatchOrder", tenantId="default")
        assert term["labels"] == {"zh": "批次单"}
        assert term["module"] == "domain"
        assert term["identity_keys"] == ["external_id"]
