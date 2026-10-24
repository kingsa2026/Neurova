# -*- coding: utf-8 -*-
"""本体按租户分区（升级计划 v25，已拍板：本体归属按租户隔离）。

验收：
- v25 迁移把两表重建为 (tenant_id, id) 复合主键，存量行归 default；
- 同 term_id/rule_id 跨租户不冲突、读面互不见；
- 种子规则按租户幂等补种（写入首跳），生产闸的谓词校验只看本租户术语；
- schema 端点按操作者租户过滤，`tenant_scoped` 如实翻真。
"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

T1_ADMIN = {"user_id": "1", "username": "a", "role": "admin",
            "tenant_id": "t1", "neuser_id": "1"}
T2_ADMIN = {"user_id": "2", "username": "b", "role": "admin",
            "tenant_id": "t2", "neuser_id": "2"}
PREFIX = "/v1/knowledge"


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield s
    s.close()


class TestV25Migration:
    def testLegacyTablesRebuiltWithTenantKey(self, tmp_path):
        db = tmp_path / "facts.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ontology_terms (
                term_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '', parent_term_id TEXT,
                domain_terms TEXT NOT NULL DEFAULT '[]',
                range_terms TEXT NOT NULL DEFAULT '[]',
                cardinality INTEGER, disjoint_with TEXT NOT NULL DEFAULT '[]',
                required_props TEXT NOT NULL DEFAULT '[]',
                version TEXT NOT NULL DEFAULT 'v1',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            ALTER TABLE ontology_terms ADD COLUMN range_kinds TEXT NOT NULL DEFAULT '[]';
            INSERT INTO ontology_terms (term_id, kind, label, created_at, updated_at)
                VALUES ('document', 'concept', '文档', '2026-01-01', '2026-01-01');
            CREATE TABLE IF NOT EXISTS ontology_rules (
                rule_id TEXT PRIMARY KEY, head_predicate TEXT NOT NULL,
                head_subject_var TEXT NOT NULL, body_json TEXT NOT NULL DEFAULT '[]',
                negated_predicates TEXT NOT NULL DEFAULT '[]',
                stratification_level INTEGER NOT NULL DEFAULT 0,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                version TEXT NOT NULL DEFAULT 'v1',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            INSERT INTO ontology_rules (rule_id, head_predicate, head_subject_var, created_at, updated_at)
                VALUES ('legacy-rule', 'is_a', 'X', '2026-01-01', '2026-01-01');
        """)
        conn.execute("PRAGMA user_version = 24")
        conn.commit()
        conn.close()

        store = KnowledgeFactStore(str(db))

        info = store._conn.execute("PRAGMA table_info(ontology_terms)").fetchall()
        assert info[0][1] == "tenant_id"
        assert [row[1] for row in info if row[5]] == ["tenant_id", "term_id"]
        row = store._conn.execute(
            "SELECT tenant_id, label FROM ontology_terms WHERE term_id='document'").fetchone()
        assert tuple(row) == ("default", "文档")
        rule = store._conn.execute(
            "SELECT tenant_id FROM ontology_rules WHERE rule_id='legacy-rule'").fetchone()
        assert tuple(rule) == ("default",)
        store.close()


class TestTenantScopedOntology:
    def testSameTermIdAcrossTenantsDoesNotCollide(self, store):
        registry = OntologyTermRegistry(store)
        registry.register("doc", "concept", label="T1文档", tenantId="t1")
        registry.register("doc", "concept", label="T2文档", tenantId="t2")

        assert registry.term("doc", tenantId="t1")["label"] == "T1文档"
        assert registry.term("doc", tenantId="t2")["label"] == "T2文档"
        assert [t["term_id"] for t in registry.terms(tenantId="t1")] == ["doc"]

    def testSameRuleIdAcrossTenantsDoesNotCollide(self, store):
        engine = ForwardChainingEngine(store)
        body = [{"atom": "type_of", "subject": "X", "object": "Y"}]
        first = engine.registerRule("r1", "is_a", body, tenantId="t1", version="v1")
        second = engine.registerRule("r1", "mentions", body, tenantId="t2", version="v1")

        assert first["head_predicate"] == "is_a"
        assert second["head_predicate"] == "mentions"
        assert [r["rule_id"] for r in engine.rules(tenantId="t1")] == ["r1"]
        assert engine.rules(tenantId="t2")[0]["head_predicate"] == "mentions"

    def testAdmissionValidatesAgainstOwnTenantTerms(self, store):
        """校验只看本租户类型表：同一写入在 t1 被定义域拒，在 t2 因谓词未登记免检放行。"""
        registry = OntologyTermRegistry(store)
        registry.register("doc", "concept", tenantId="t1")
        registry.register("other", "concept", tenantId="t1")
        registry.register("rel", "relation", tenantId="t1", domain=["doc"])
        gate = productionAdmissionGate(store, toolVersion="test")

        def _req(tenant):
            return AdmissionRequest(
                agentId="agent", tenantId=tenant,
                subjectLabel="A", predicateTermId="rel", objectTerm="B",
                content="A rel B", relationKind="entity",
                assertions=[{"actorType": "user", "actorId": "1",
                             "statementText": "A rel B"}],
            )

        # t1：主体先落 is_a 再挂主类型列（列由抽取侧写，闸不管），
        # rel 的定义域是 doc → 违规被拒。
        first = gate.admit(AdmissionRequest(
            agentId="agent", tenantId="t1",
            subjectLabel="A", predicateTermId="is_a", objectTerm="other",
            content="A is_a other", relationKind="entity",
            assertions=[{"actorType": "user", "actorId": "1",
                         "statementText": "A is_a other"}],
        ))
        registry.assignSubjectType(first.subjectKey, "other", tenantId="t1")
        with pytest.raises(Exception):
            gate.admit(_req("t1"))

        # t2：rel 未登记 → 免检放行（各租户各自校验，互不借用对方的表）。
        receipt = gate.admit(_req("t2"))
        assert receipt.factId

    def testSeedRulesArePerTenantAndIdempotent(self, store):
        gate = productionAdmissionGate(store, toolVersion="test")
        engine = gate._collaborators["forward_chaining"]

        # default 租户在装配点有种；t1 首次写入前由闸补种，幂等。
        gate.admit(AdmissionRequest(
            agentId="agent", tenantId="t1",
            subjectLabel="A", predicateTermId="is_a", objectTerm="B",
            content="A is_a B", relationKind="entity",
            assertions=[{"actorType": "user", "actorId": "1",
                         "statementText": "A is_a B"}],
        ))
        t1Rules = {r["rule_id"] for r in engine.rules(tenantId="t1")}
        assert t1Rules, "t1 租户首次写入后应有种子规则"
        count = len(engine.rules(tenantId="t1"))
        gate.admit(AdmissionRequest(
            agentId="agent", tenantId="t1",
            subjectLabel="C", predicateTermId="is_a", objectTerm="D",
            content="C is_a D", relationKind="entity",
            assertions=[{"actorType": "user", "actorId": "1",
                         "statementText": "C is_a D"}],
        ))
        assert len(engine.rules(tenantId="t1")) == count


class TestTenantScopedSchemaEndpoint:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        monkeypatch.setattr(
            "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store)
        registry = OntologyTermRegistry(store)
        registry.register("t1_term", "concept", label="租户一", tenantId="t1")
        registry.register("t2_term", "concept", label="租户二", tenantId="t2")
        app = FastAPI()
        app.include_router(knowledge_module.router, prefix=PREFIX)
        yield TestClient(app), store
        store.close()

    def testSchemaFiltersByOperatorTenant(self, client):
        http, store = client
        http.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(T1_ADMIN)

        resp = http.get(PREFIX + "/ontology/schema")

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        ids = {t["term_id"] for t in data["terms"]}
        assert "t1_term" in ids
        assert "t2_term" not in ids
        assert data["tenant_scoped"] is True

    def testWriteLandsInOperatorTenant(self, client):
        http, store = client
        http.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(T2_ADMIN)

        resp = http.post(PREFIX + "/ontology/terms", json={
            "term_id": "fresh", "kind": "concept", "basis": "t2 建档"})

        assert resp.status_code == 200, resp.text
        activity = store.activity(resp.json()["data"]["activity_id"])
        assert activity["tenant_id"] == "t2"
