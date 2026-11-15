# -*- coding: utf-8 -*-
"""Ossie 风格语义模型互操作（P2-4）判据。

- 导出：术语/规则/形状一份文档，含 format 标记与租户；
- 导入缺省 dry-run：预检 finding 不落库；apply=true 经本体流水线整批成版
  （基线 id 回显）；kind 翻转/父类缺失拒绝成版；
- 非法 YAML/空文档显式 400；
- REST：导出登录可读（YAML 文本），导入仅管理员。
"""

from __future__ import annotations

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.ossie import exportOssie, importOssie
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


def _seed(store):
    registry = OntologyTermRegistry(store)
    registry.register("Order", "concept", label="订单",
                      definition="客户购买请求", aliases=["采购单"])
    registry.register("hasItem", "relation", label="有明细", domain=["Order"])
    return registry


def _doc():
    return {
        "format": "neurova-ontology-ossie/1",
        "semantic_layer": {
            "terms": [
                {"id": "Shipment", "kind": "concept", "name": "发运",
                 "description": "订单的物流履约", "synonyms": ["发货"]},
                {"id": "ShipmentLine", "kind": "concept", "name": "发运明细",
                 "parent": "Shipment"},
            ],
            "rules": [],
        },
    }


class TestOssieModule:
    def testExportCarriesTermsRulesShapes(self, store):
        _seed(store)
        doc = exportOssie(store, "default")
        assert doc["format"] == "neurova-ontology-ossie/1"
        ids = {t["id"] for t in doc["semantic_layer"]["terms"]}
        assert {"Order", "hasItem"} <= ids
        order = [t for t in doc["semantic_layer"]["terms"] if t["id"] == "Order"][0]
        assert order["name"] == "订单"
        assert order["synonyms"] == ["采购单"]

    def testImportDryRunWritesNothing(self, store):
        _seed(store)
        before = len(OntologyTermRegistry(store).terms(tenantId="default"))
        result = importOssie(store, _doc(), tenantId="default", apply=False)
        assert result["accepted"] is False
        assert result["dry_run"] is True
        assert result["terms"] == 2
        assert result["preflight"] == []
        assert len(OntologyTermRegistry(store).terms(tenantId="default")) == before

    def testImportApplyCreatesTermsWithBaseline(self, store):
        _seed(store)
        result = importOssie(store, _doc(), tenantId="default", apply=True,
                             createdBy="9")
        assert result["accepted"] is True
        assert result["applied"]["terms"] == 2
        assert result["baselineId"]
        registry = OntologyTermRegistry(store)
        assert registry.term("Shipment", tenantId="default") is not None
        assert registry.term("Shipment", tenantId="default")["label"] == "发运"

    def testImportUnknownParentRefused(self, store):
        _seed(store)
        doc = _doc()
        doc["semantic_layer"]["terms"] = [
            {"id": "Orphan", "kind": "concept", "name": "孤儿", "parent": "Ghost"}]
        result = importOssie(store, doc, tenantId="default", apply=True)
        assert result["accepted"] is False
        assert any("父类" in f["finding"] for f in result["preflight"])
        assert OntologyTermRegistry(store).term("Orphan", tenantId="default") is None

    def testImportKindFlipRefused(self, store):
        _seed(store)
        doc = _doc()
        doc["semantic_layer"]["terms"] = [{"id": "Order", "kind": "relation",
                                           "name": "订单"}]
        result = importOssie(store, doc, tenantId="default", apply=True)
        assert result["accepted"] is False
        assert any("kind 翻转" in f["finding"] for f in result["preflight"])

    def testInvalidDocumentsRejected(self, store):
        with pytest.raises(ValueError, match="YAML 映射"):
            importOssie(store, "- a\n- b", tenantId="default")
        with pytest.raises(ValueError, match="没有可导入"):
            importOssie(store, {"format": "neurova-ontology-ossie/1"},
                        tenantId="default")
        with pytest.raises(ValueError, match="kind"):
            importOssie(store, {"semantic_layer": {"terms": [
                {"id": "X", "kind": "bogus"}]}}, tenantId="default")


class TestOssieRest:
    @pytest.fixture
    def client(self, store):
        from neurova.api.endpoints import knowledge_ossie

        app = FastAPI()
        app.include_router(knowledge_ossie.router, prefix=PREFIX)
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(ADMIN)
        yield TestClient(app)

    def testExportYamlReadable(self, client, store):
        _seed(store)
        resp = client.get(PREFIX + "/ontology/export.ossie.yaml")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/yaml")
        doc = yaml.safe_load(resp.text)
        assert doc["format"] == "neurova-ontology-ossie/1"

    def testImportViewerForbidden(self, client, store):
        client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(VIEWER)
        resp = client.post(PREFIX + "/ontology/import-ossie",
                           json={"document": yaml.safe_dump(_doc())})
        assert resp.status_code == 403

    def testImportDryRunAndApply(self, client, store):
        payload = yaml.safe_dump(_doc(), allow_unicode=True)
        dry = client.post(PREFIX + "/ontology/import-ossie",
                          json={"document": payload, "apply": False})
        assert dry.status_code == 200
        assert dry.json()["data"]["accepted"] is False

        applied = client.post(PREFIX + "/ontology/import-ossie",
                              json={"document": payload, "apply": True})
        assert applied.status_code == 200
        assert applied.json()["data"]["accepted"] is True

    def testImportBadYamlIs400(self, client):
        resp = client.post(PREFIX + "/ontology/import-ossie",
                           json={"document": "a: [unclosed"})
        assert resp.status_code == 400
