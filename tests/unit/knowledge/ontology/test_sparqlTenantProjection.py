# -*- coding: utf-8 -*-
"""KNOW-01：SPARQL 投影与缓存指纹统一跟随请求租户。

审计定位（全仓逐文件审计报告 2026-11-25 §6 KNOW-01）：
  - sparql_query.runSparqlQuery 图读取固定 PROJECTION_TENANT="default"；
  - query_cache.buildKey 术语/事实指纹同取 default。
影响：非 default 租户的 SPARQL 查询读到 default 知识图；缓存指纹跨租户失真。
判据咬合真实链路：真实 SQLite store → 生产准入闸写两个租户 → runSparqlQuery
按请求租户查询 → 行集与缓存失效都只认请求租户。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


def _assertion(text: str) -> list:
    return [{"actorType": "pipeline", "actorId": "unit",
             "mediumRef": "unit:test", "statementText": text}]


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("device", "concept")
    registry.register("linked", "relation")
    gate = productionAdmissionGate(s)
    yield s, gate
    s.close()


_QUERY = ("PREFIX kbg: <https://neurova.local/knowledge/>"
          " SELECT ?o WHERE { ?s kbg:linked ?o } LIMIT 10")


class TestSparqlTenantProjection:
    def test_projectionFollowsRequestTenant(self, kb, monkeypatch):
        """acme 租户查询必须读到 acme 的图，而不是 default 的投影。"""
        s, gate = kb
        from neurova.knowledge.ontology import sparql_query

        monkeypatch.setattr(sparql_query, "_rdflibAvailable", lambda: True)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="机甲A", predicateTermId="linked",
            objectTerm="机甲B", content="机甲A linked 机甲B", tenantId="acme",
            assertions=_assertion("机甲A linked 机甲B")))
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="设备A", predicateTermId="linked",
            objectTerm="设备B", content="设备A linked 设备B", tenantId="default",
            assertions=_assertion("设备A linked 设备B")))

        result = sparql_query.runSparqlQuery(s, _QUERY, agentId="default",
                                             tenantId="acme")
        objects = {row.get("o") for row in result["rows"]}
        assert "机甲B" in objects, "acme 查询必须命中 acme 租户事实"
        assert "设备B" not in objects, "acme 查询不得读到 default 租户事实"

    def test_cacheFingerprintFollowsRequestTenant(self, kb, monkeypatch):
        """acme 租户新写事实必须击穿 acme 的缓存行集（指纹盯请求租户）。"""
        s, gate = kb
        from neurova.knowledge.ontology import sparql_query

        monkeypatch.setattr(sparql_query, "_rdflibAvailable", lambda: True)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="机甲A", predicateTermId="linked",
            objectTerm="机甲B", content="机甲A linked 机甲B", tenantId="acme",
            assertions=_assertion("机甲A linked 机甲B")))
        first = sparql_query.runSparqlQuery(s, _QUERY, agentId="default",
                                            tenantId="acme")
        assert "机甲B" in {row.get("o") for row in first["rows"]}

        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="机甲C", predicateTermId="linked",
            objectTerm="机甲D", content="机甲C linked 机甲D", tenantId="acme",
            assertions=_assertion("机甲C linked 机甲D")))
        second = sparql_query.runSparqlQuery(s, _QUERY, agentId="default",
                                             tenantId="acme")
        objects = {row.get("o") for row in second["rows"]}
        assert "机甲D" in objects, "同租户新事实必须击穿缓存指纹"
