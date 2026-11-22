# -*- coding: utf-8 -*-
"""升级计划收口（U1/U3/U6/U12/U13）：五个新 REST 路由的行为判据。

全部走真 store + 真生产咽喉装配（mock 只到 FastAPI 依赖覆盖层）；
租户一律取登录态；写形入参错误显式 400。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.shapes import ShapeRegistry
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

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
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
        lambda: dict(ADMIN)
    return TestClient(app)


def _gate(store):
    return productionAdmissionGate(store, toolVersion="unit")


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return _gate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}]),
        allowPendingSegments=True).factId


class TestShaclValidateRoute:
    def test_dryRunReportsViolationAndOffSkips(self, client, store):
        _admit(store, "设备A", "serial_code", "bad-value")
        ShapeRegistry(store).register(
            "default", "shape_serial_pattern", "relation", "pattern",
            {"pattern": r"^DEV-\d+$"}, targetTermId="serial_code",
            severity="violation", message="序列号须形如 DEV-数字")
        subjectKey = store.resolveSubjectKey("default", "设备A")

        resp = client.post(PREFIX + "/ontology/validate/shacl", json={
            "subject_key": subjectKey, "mode": "enforce"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["supported"] is True and data["conforms"] is False
        assert any(v["severity"] == "Violation" for v in data["violations"])

        off = client.post(PREFIX + "/ontology/validate/shacl", json={
            "subject_key": subjectKey, "mode": "off"})
        assert off.json()["data"].get("skipped") is True

    def test_noShapesIsHonestNoop(self, client):
        resp = client.post(PREFIX + "/ontology/validate/shacl", json={})
        assert resp.status_code == 200
        assert resp.json()["data"].get("note") == "无已注册用户形状"


class TestBulkLoadRoute:
    def test_dryRunThenApplyAndWholeBatchReject(self, client, store):
        ShapeRegistry(store).register(
            "default", "shape_serial_pattern", "relation", "pattern",
            {"pattern": r"^SN-\d+$"}, targetTermId="serial_code",
            severity="violation", message="序列号须 SN-数字")
        rows = [{"subjectLabel": "设备%s" % i, "predicateTermId": "serial_code",
                 "objectTerm": "SN-%d" % i, "content": "设备%s 序列号 SN-%d" % (i, i)}
                for i in range(5)]
        ok = client.post(PREFIX + "/ontology/facts/bulk",
                         json={"rows": rows, "batch_size": 2, "dry_run": True})
        assert ok.status_code == 200
        assert ok.json()["data"]["dryRun"] is True

        applyResp = client.post(PREFIX + "/ontology/facts/bulk",
                                json={"rows": rows, "batch_size": 2, "dry_run": False})
        assert applyResp.status_code == 200
        assert applyResp.json()["data"]["admitted"] == 5

        before = store.factCount()
        bad = rows + [{"subjectLabel": "坏行", "predicateTermId": "serial_code",
                       "objectTerm": "BAD-001", "content": "坏行 序列号 BAD-001"}]
        rejected = client.post(PREFIX + "/ontology/facts/bulk",
                               json={"rows": bad, "batch_size": 2, "dry_run": False})
        assert rejected.status_code == 200
        assert rejected.json()["data"]["admitted"] == 0
        assert store.factCount() == before, "违规行必须整批零落盘"

    def test_rowsMustBeList(self, client):
        resp = client.post(PREFIX + "/ontology/facts/bulk", json={"rows": "nope"})
        assert resp.status_code == 400


class TestQualityGateRoute:
    def test_thresholdsFailAndPass(self, client, store):
        registry = OntologyTermRegistry(store)
        registry.register("Order", "concept", label="订单")
        registry.register("bare_term", "concept", label="")

        hit = client.post(PREFIX + "/ontology/quality/gate",
                          json={"thresholds": {"max_findings": 0}})
        assert hit.status_code == 200
        gate = hit.json()["data"]["gate"]
        assert gate["passed"] is False and gate["threshold_failures"]

        miss = client.post(PREFIX + "/ontology/quality/gate",
                           json={"thresholds": {"max_findings": 999}})
        assert miss.json()["data"]["gate"]["passed"] is True

    def test_badThresholdsIs400(self, client):
        resp = client.post(PREFIX + "/ontology/quality/gate",
                           json={"thresholds": {"unknown_key": 1}})
        assert resp.status_code == 400


class TestProveRoute:
    def test_proveDerivedConclusionAndMissing(self, client, store):
        engine = ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
            st, toolVersion="unit"))
        _admit(store, "甲", "part_of", "乙")
        _admit(store, "乙", "part_of", "丙")
        engine.registerRule("part_of_transitive", "part_of", [
            {"atom": "part_of", "subject": "X", "object": "Y"},
            {"atom": "part_of", "subject": "Y", "object": "Z"}])
        engine.fireAll(agentId="default")

        hit = client.post(PREFIX + "/ontology/prove", json={
            "subject": "甲", "predicate": "part_of", "object": "丙"})
        assert hit.status_code == 200
        proof = hit.json()["data"]
        assert proof["proved"] is True and proof["steps"]

        miss = client.post(PREFIX + "/ontology/prove", json={
            "subject": "丙", "predicate": "part_of", "object": "甲"})
        assert miss.json()["data"]["proved"] is False
        assert miss.json()["data"]["missing"]

    def test_missingFieldsIs400(self, client):
        resp = client.post(PREFIX + "/ontology/prove", json={"subject": "甲"})
        assert resp.status_code == 400


class TestExplainRoute:
    def test_explainDerivedFact(self, client, store):
        engine = ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
            st, toolVersion="unit"))
        _admit(store, "甲", "part_of", "乙")
        _admit(store, "乙", "part_of", "丙")
        engine.registerRule("part_of_transitive", "part_of", [
            {"atom": "part_of", "subject": "X", "object": "Y"},
            {"atom": "part_of", "subject": "Y", "object": "Z"}])
        derived = engine.fireAll(agentId="default")["derived"][0]

        resp = client.get(PREFIX + "/ontology/explain/" + derived)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert any(step["kind"] == "rule" for step in data["steps"])
        assert "part_of_transitive" in data["text"]

    def test_unknownFactIs404(self, client):
        resp = client.get(PREFIX + "/ontology/explain/fact_not_exists")
        assert resp.status_code == 404
