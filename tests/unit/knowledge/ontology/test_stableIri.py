# -*- coding: utf-8 -*-
"""B12 L6：稳定 IRI 解析端点与跨租户段 helper（升级计划 §12.7）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
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
    from neurova.api.endpoints import knowledge_ontology_iri

    app = FastAPI()
    app.include_router(knowledge_ontology_iri.router, prefix=PREFIX)
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
    return TestClient(app)


class TestStableIri:
    def test_kbgTermIriResolves(self, store, client):
        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation", label="属于")

        resp = client.get(PREFIX + "/ontology/iri/kbg:part_of")

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["kind"] == "term" and data["term_id"] == "part_of"
        assert data["term"]["label"] == "属于"

    def test_externalIriResolvesToTerm(self, store, client):
        from urllib.parse import quote

        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation",
                          externalIris={"skos_exactMatch": "http://example.org/vocab#partOf"})

        # `#` 是 URI fragment 分隔符，调用方必须编码后传入（服务端解码回原形）
        resp = client.get(PREFIX + "/ontology/iri/"
                          + quote("http://example.org/vocab#partOf", safe=""))

        assert resp.status_code == 200
        assert resp.json()["data"]["term_id"] == "part_of"

    def test_unknownIriIs404(self, client):
        resp = client.get(PREFIX + "/ontology/iri/kbg:nobody_knows_me")
        assert resp.status_code == 404

    def test_tenantScopedIriHelper(self):
        """跨租户导出带租户段（kbg:<tenant>_<id>）；单租户导出不带。"""
        from neurova.knowledge.ontology.term_registry import tenantScopedIri

        assert tenantScopedIri("tenant-b", "part_of") == "kbg:tenant-b_part_of"
