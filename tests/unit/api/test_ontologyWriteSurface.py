# -*- coding: utf-8 -*-
"""本体写面（S2）：术语/规则 CRUD、删除前影响面、变更留痕。

验收（升级计划 §11.4 S2）：
- 非法结构在写入处即拒（400），坏类型进不了表；
- 写端点仅管理员可用（403）；
- 删除被引用的术语不静默制造悬空引用——返回 409 与影响面清单；
- 每次写变更留痕（activity：操作人、动作、依据），依据取调用方声明的 basis。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

ADMIN = {"user_id": "1", "username": "root", "role": "admin",
         "tenant_id": "t1", "neuser_id": "1"}
USER = {"user_id": "2", "username": "alice", "role": "user",
        "tenant_id": "t1", "neuser_id": "2"}
PREFIX = "/v1/knowledge"


class _Api:
    def __init__(self, client, store, registry, engine):
        self.client = client
        self.store = store
        self.registry = registry
        self.engine = engine

    def asUser(self, user):
        self.client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(user)


@pytest.fixture()
def api(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store)
    registry = OntologyTermRegistry(store)
    registry.register("document", "concept", label="文档", tenantId="t1")
    registry.register("report", "concept", label="报告", parentTermId="document", tenantId="t1")
    engine = ForwardChainingEngine(store)

    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
    yield _Api(TestClient(app), store, registry, engine)
    store.close()


def _termsById(api):
    resp = api.client.get(PREFIX + "/ontology/schema")
    assert resp.status_code == 200, resp.text
    return {t["term_id"]: t for t in resp.json()["data"]["terms"]}


def _ruleIds(api):
    return {r["rule_id"] for r in _schemaRules(api)}


def _schemaRules(api):
    resp = api.client.get(PREFIX + "/ontology/schema")
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["rules"]


class TestWriteAuthorization:
    @pytest.mark.parametrize("method,path,body", [
        ("post", "/ontology/terms", {"term_id": "x", "kind": "concept"}),
        ("put", "/ontology/terms/document", {"kind": "concept"}),
        ("delete", "/ontology/terms/document", None),
        ("post", "/ontology/rules", {"rule_id": "r", "head_predicate": "is_a", "body": []}),
        ("delete", "/ontology/rules/r", None),
    ])
    def testNonAdminWriteIsForbidden(self, api, method, path, body):
        api.asUser(USER)
        if body is None:
            resp = getattr(api.client, method)(PREFIX + path)
        else:
            resp = getattr(api.client, method)(PREFIX + path, json=body)

        assert resp.status_code == 403, resp.text


class TestTermCrud:
    def testCreateTermLandsInSchema(self, api):
        resp = api.client.post(PREFIX + "/ontology/terms", json={
            "term_id": "sensor", "kind": "concept", "label": "传感器",
            "basis": "新增设备类型",
        })

        assert resp.status_code == 200, resp.text
        assert _termsById(api)["sensor"]["label"] == "传感器"

    def testCreateDuplicateTermConflicts(self, api):
        resp = api.client.post(PREFIX + "/ontology/terms", json={
            "term_id": "document", "kind": "concept",
        })

        assert resp.status_code == 409, resp.text

    def testUpdateMissingTermIs404(self, api):
        resp = api.client.put(PREFIX + "/ontology/terms/ghost", json={
            "kind": "concept",
        })

        assert resp.status_code == 404, resp.text

    def testUpdateTermKeepsIdentityAndBumpsFields(self, api):
        resp = api.client.put(PREFIX + "/ontology/terms/report", json={
            "kind": "concept", "label": "周报", "version": "v2",
        })

        assert resp.status_code == 200, resp.text
        report = _termsById(api)["report"]
        assert report["label"] == "周报"
        assert report["version"] == "v2"
        assert report["parent_term_id"] == "document"

    def testInvalidKindIs400(self, api):
        resp = api.client.post(PREFIX + "/ontology/terms", json={
            "term_id": "magic", "kind": "spell",
        })

        assert resp.status_code == 400, resp.text
        assert "spell" in resp.json()["detail"]

    def testDanglingParentIs400(self, api):
        resp = api.client.post(PREFIX + "/ontology/terms", json={
            "term_id": "orphan", "kind": "concept", "parent_term_id": "ghost",
        })

        assert resp.status_code == 400, resp.text

    def testDeleteUnusedTermSucceeds(self, api):
        api.client.post(PREFIX + "/ontology/terms", json={
            "term_id": "sensor", "kind": "concept"})
        resp = api.client.delete(PREFIX + "/ontology/terms/sensor")

        assert resp.status_code == 200, resp.text
        assert "sensor" not in _termsById(api)

    def testDeleteMissingTermIs404(self, api):
        resp = api.client.delete(PREFIX + "/ontology/terms/ghost")

        assert resp.status_code == 404, resp.text

    def testDeleteTermWithChildrenReturnsImpact(self, api):
        resp = api.client.delete(PREFIX + "/ontology/terms/document")

        assert resp.status_code == 409, resp.text
        impact = resp.json()["detail"]["impact"]
        assert impact["child_terms"] == ["report"]

    def testDeleteTermReferencedByFactsReturnsImpact(self, api):
        subjectKey = api.store.upsertSubject("agent", "Alpha", tenantId="t1")
        api.store.upsertFact("agent", subjectKey, "document", "一份文档",
                             "正文", contentKey="ck:1", tenantId="t1")
        resp = api.client.delete(PREFIX + "/ontology/terms/document")

        assert resp.status_code == 409, resp.text
        impact = resp.json()["detail"]["impact"]
        assert impact["fact_count"] == 1

    def testDeleteTermReferencedBySubjectTypeReturnsImpact(self, api):
        subjectKey = api.store.upsertSubject("agent", "Alpha", tenantId="t1")
        api.registry.assignSubjectType(subjectKey, "document", tenantId="t1")
        resp = api.client.delete(PREFIX + "/ontology/terms/document")

        assert resp.status_code == 409, resp.text
        impact = resp.json()["detail"]["impact"]
        assert impact["typed_subject_count"] == 1


class TestRuleCrud:
    BODY = [{"atom": "type_of", "subject": "X", "object": "Y"}]

    def testCreateRuleLandsInSchema(self, api):
        resp = api.client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "r-doc", "head_predicate": "is_a", "body": self.BODY,
            "basis": "设备归属推导",
        })

        assert resp.status_code == 200, resp.text
        assert "r-doc" in _ruleIds(api)

    def testCreateDuplicateRuleConflicts(self, api):
        api.client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "r-doc", "head_predicate": "is_a", "body": self.BODY})
        resp = api.client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "r-doc", "head_predicate": "is_a", "body": self.BODY})

        assert resp.status_code == 409, resp.text

    def testConditionClassRuleSurvivesTheWriteSurface(self, api):
        """条件类规则必须能从 HTTP 写面登记并原样读回——形状参数不许只长在引擎侧。

        活体（§8.2）第一版正是在这里失配的：写面模型没有 `head_object_const`，
        条件类经 REST 登记不出来，只有直连引擎的单测才成立（票面 B1 的
        live-verify 因此从未真的成立过）。
        """
        api.client.post(PREFIX + "/ontology/terms", json={
            "term_id": "riskLevel", "kind": "relation", "label": "风险等级",
            "basis": "条件类写面回归"})
        api.client.post(PREFIX + "/ontology/terms", json={
            "term_id": "HighRiskDoc", "kind": "concept", "label": "高风险文档",
            "basis": "条件类写面回归"})
        resp = api.client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "r-cond", "head_predicate": "is_a",
            "body": [{"atom": "riskLevel", "subject": "X", "objectConst": "High"}],
            "head_object_const": "HighRiskDoc",
            "basis": "条件类写面回归",
        })

        assert resp.status_code == 200, resp.text
        rules = {r["rule_id"]: r for r in _schemaRules(api)}
        assert rules["r-cond"]["shape"] == "conjunction"
        assert rules["r-cond"]["head_object_const"] == "HighRiskDoc"

        # PUT 的"未提供即保留现值"契约对新增一栏同样成立：不改形状才谈得上改版本
        # 改版照旧带上正文（PUT 省略 body 走"保留现值"那条支路今天仍是坏的，
        # 已登记台账另批修；本格只咬合条件类这一栏的保留契约）
        resp = api.client.put(PREFIX + "/ontology/rules/r-cond", json={
            "head_predicate": "is_a", "version": "v2", "basis": "只改版不改形状",
            "body": [{"atom": "riskLevel", "subject": "X", "objectConst": "High"}],
        })

        assert resp.status_code == 200, resp.text
        updated = {r["rule_id"]: r for r in _schemaRules(api)}["r-cond"]
        assert updated["version"] == "v2"
        assert updated["head_object_const"] == "HighRiskDoc", \
            "PUT 把条件类擦成了 relay——保留现值契约破了"
        assert updated["shape"] == "conjunction"

    def testInvalidRuleBodyIs400(self, api):
        resp = api.client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "r-bad", "head_predicate": "is_a", "body": [],
        })

        assert resp.status_code == 400, resp.text

    def testUpdateRuleWithoutBodyKeepsExistingBody(self, api):
        """改版只写版本号：body 省略即保留现值——此前这条支路是坏的。

        现役用例从不省略 body，所以"保留现值"那半句一直没被执行过：它把读面形状
        （kind/predicate）直接回灌写面解析器（只认 atom/not），改版当场 400，
        而 400 的文本读起来像"调用方传了坏 body"。本格把这条支路钉成会红的判据。
        """
        api.client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "r-keep", "head_predicate": "is_a", "body": self.BODY,
            "basis": "保留现值回归",
        })

        resp = api.client.put(PREFIX + "/ontology/rules/r-keep", json={
            "head_predicate": "is_a", "version": "v9", "basis": "只改版不重传正文",
        })

        assert resp.status_code == 200, resp.text
        rule = {r["rule_id"]: r for r in _schemaRules(api)}["r-keep"]
        assert rule["version"] == "v9"
        assert [a["predicate"] for a in rule["body"]] == ["type_of"],             "省略 body 把正文换了或清空了——保留现值不是嘴上说的"

    def testUpdateMissingRuleIs404(self, api):
        resp = api.client.put(PREFIX + "/ontology/rules/ghost", json={
            "head_predicate": "is_a", "body": self.BODY,
        })

        assert resp.status_code == 404, resp.text

    def testUpdateRuleBumpsVersion(self, api):
        api.client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "r-doc", "head_predicate": "is_a", "body": self.BODY})
        resp = api.client.put(PREFIX + "/ontology/rules/r-doc", json={
            "head_predicate": "is_a", "body": self.BODY, "version": "v2",
        })

        assert resp.status_code == 200, resp.text
        resp = api.client.get(PREFIX + "/ontology/schema")
        rule = next(r for r in resp.json()["data"]["rules"]
                    if r["rule_id"] == "r-doc")
        assert rule["version"] == "v2"

    def testDeleteRuleRemovesIt(self, api):
        api.client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "r-doc", "head_predicate": "is_a", "body": self.BODY})
        resp = api.client.delete(PREFIX + "/ontology/rules/r-doc")

        assert resp.status_code == 200, resp.text
        assert "r-doc" not in _ruleIds(api)

    def testDeleteMissingRuleIs404(self, api):
        resp = api.client.delete(PREFIX + "/ontology/rules/ghost")

        assert resp.status_code == 404, resp.text


class TestImpactSurface:
    def testImpactCountsEveryReferenceKind(self, api):
        subjectKey = api.store.upsertSubject("agent", "Alpha", tenantId="t1")
        api.store.upsertFact("agent", subjectKey, "document", "客体",
                             "正文", contentKey="ck:1", tenantId="t1")
        api.registry.assignSubjectType(subjectKey, "document", tenantId="t1")
        api.engine.registerRule(
            "r-doc", "document",
            [{"atom": "type_of", "subject": "X", "object": "Y"}], tenantId="t1")

        resp = api.client.get(PREFIX + "/ontology/impact", params={"term": "document"})

        assert resp.status_code == 200, resp.text
        impact = resp.json()["data"]
        assert impact["term_id"] == "document"
        assert impact["fact_count"] == 1
        assert impact["typed_subject_count"] == 1
        assert impact["child_terms"] == ["report"]
        assert impact["referencing_rules"] == ["r-doc"]

    def testUnknownTermIs404(self, api):
        resp = api.client.get(PREFIX + "/ontology/impact", params={"term": "ghost"})

        assert resp.status_code == 404, resp.text


class TestAuditTrail:
    def testTermWriteLandsActivity(self, api):
        resp = api.client.post(PREFIX + "/ontology/terms", json={
            "term_id": "sensor", "kind": "concept", "basis": "设备类型登记",
        })

        assert resp.status_code == 200, resp.text
        activityId = resp.json()["data"]["activity_id"]
        record = api.store.activity(activityId)
        assert record is not None
        assert record["activity_kind"] == "ontology_term_write"
        assert record["basis"] == "设备类型登记"
        assert record["inputs"]["actor"] == "1"
        assert record["inputs"]["action"] == "create"
        assert record["inputs"]["term_id"] == "sensor"

    def testRuleDeleteLandsActivity(self, api):
        api.client.post(PREFIX + "/ontology/rules", json={
            "rule_id": "r-doc", "head_predicate": "is_a",
            "body": [{"atom": "type_of", "subject": "X", "object": "Y"}]})
        resp = api.client.delete(
            PREFIX + "/ontology/rules/r-doc", params={"basis": "规则废弃"})

        assert resp.status_code == 200, resp.text
        record = api.store.activity(resp.json()["data"]["activity_id"])
        assert record["activity_kind"] == "ontology_rule_write"
        assert record["inputs"]["action"] == "delete"
        assert record["basis"] == "规则废弃"
