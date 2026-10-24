# -*- coding: utf-8 -*-
"""本体 schema 只读端点（S1：2D 调色板的数据面）。

契约：
- 读面复用注册表与规则引擎——端点里不许有第二份类型清单；
- `is_a` 的值域按类别展开：声明形状（range_kinds）与展开结果同时给出，展开不覆盖声明；
- schema 版本取 `db_migration` 的唯一出处，不在端点里写死数字；
- S1 只有读面，/ontology 路径上不存在写入口。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.core.db_migration import latest_version
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

USER = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
PREFIX = "/v1/knowledge"


class _Api:
    """夹具返回体：避免每格用例重复解包六个位置。"""

    def __init__(self, client, store, registry, engine, app):
        self.client = client
        self.store = store
        self.registry = registry
        self.engine = engine
        self.app = app


@pytest.fixture()
def api(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store)
    registry = OntologyTermRegistry(store)
    registry.register("document", "concept", label="文档")
    registry.register("report", "concept", label="报告", parentTermId="document")
    registry.register(
        "mentions", "relation", label="提及",
        domain=["document"], rangeTerms=["report"], cardinality=5,
        disjointWith=["depends_on"], requiredProps=["basis"], version="v2")
    engine = ForwardChainingEngine(store)
    engine.registerRule(
        "report-inherits-document", "is_a",
        [{"atom": "type_of", "subject": "X", "object": "Y"}],
        headSubjectVar="X", version="v3")

    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: USER
    yield _Api(TestClient(app), store, registry, engine, app)
    store.close()


def _schemaData(api):
    resp = api.client.get(PREFIX + "/ontology/schema")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0
    return body["data"]


def _termsById(data):
    return {t["term_id"]: t for t in data["terms"]}


class TestSchemaReadSurface:
    def test_registeredTermsLandWithTheirOwnFields(self, api):
        terms = _termsById(_schemaData(api))

        mentions = terms["mentions"]
        assert mentions["kind"] == "relation"
        assert mentions["label"] == "提及"
        assert mentions["domain_terms"] == ["document"]
        assert mentions["range_terms"] == ["report"]
        assert mentions["cardinality"] == 5
        assert mentions["disjoint_with"] == ["depends_on"]
        assert mentions["required_props"] == ["basis"]
        assert mentions["version"] == "v2"

    def testConceptHierarchyIsReadableAsData(self, api):
        terms = _termsById(_schemaData(api))

        assert terms["report"]["parent_term_id"] == "document"
        assert terms["document"]["parent_term_id"] is None

    def testRulesLandWithHydratedBodyAndVersion(self, api):
        rules = {r["rule_id"]: r for r in _schemaData(api)["rules"]}

        rule = rules["report-inherits-document"]
        assert rule["head_predicate"] == "is_a"
        assert rule["body"] == [{"kind": "atom", "predicate": "type_of",
                                 "subject": "X", "object": "Y"}]
        assert rule["depends_on"] == ["type_of"]
        assert rule["enabled"] is True
        assert rule["version"] == "v3"

    def testSchemaVersionComesFromTheSingleMigrationSource(self, api):
        assert _schemaData(api)["schema_version"] == latest_version("knowledge_foundation")

    def testSurfaceReadsFromRegistryNotAHardcodedList(self, api):
        """新登记的术语当场出现在读面上——写死的清单做不到这件事。"""
        api.registry.register("sensor", "concept", label="传感器")

        assert "sensor" in _termsById(_schemaData(api))


class TestRangeKindExpansion:
    def testDeclaredShapeAndExpansionAreBothReported(self, api):
        """`is_a` 只声明 range_kinds=["concept"]，展开随表增长，声明不被改写。"""
        isA = _termsById(_schemaData(api))["is_a"]

        assert isA["range_terms"] == []
        assert isA["range_kinds"] == ["concept"]
        assert set(isA["range_terms_effective"]) >= {"document", "report"}

    def testExpansionGrowsWithTheTable(self, api):
        api.registry.register("vehicle", "concept", label="载具")

        isA = _termsById(_schemaData(api))["is_a"]
        assert "vehicle" in isA["range_terms_effective"]


class TestOntologyIsTenantScoped:
    def testTenantScopedIsReportedHonestly(self, api):
        """v25 起本体按租户分区（已拍板已落地）；读面必须如实标出，
        schema 与写面都按操作者租户过滤。"""
        assert _schemaData(api)["tenant_scoped"] is True


class TestNoWriteSurfaceInS1:
    """S1 只交付读面。

    不翻 `app.routes`：fastapi 0.142 把 include_router 存成 `_IncludedRouter` 惰性项，
    按 `.path` 读拿不到子路由（本仓 `plugin_route_mount._pathTaken` 记过同一坑）。
    改成行为面判据——同一路径 GET 应答 200、写方法一律 405，两件事各自咬住"挂上了"
    与"没有写入口"，谁都不靠对方兜底。
    """

    def testSchemaPathAnswersGet(self, api):
        assert api.client.get(PREFIX + "/ontology/schema").status_code == 200

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def testSchemaPathRejectsWriteMethods(self, api, method):
        resp = getattr(api.client, method)(PREFIX + "/ontology/schema")
        assert resp.status_code == 405, "%s → %s %s" % (
            method.upper(), resp.status_code, resp.text)
