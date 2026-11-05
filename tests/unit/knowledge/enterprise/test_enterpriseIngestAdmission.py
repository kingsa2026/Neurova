# -*- coding: utf-8 -*-
"""B14 admission 接线判据（升级计划 §14.3/§14.4）：fake adapter → mapping → 咽喉。

事实落库经唯一写口；坏一行只退它自己；重放幂等；跨租户不可见。
"""

from __future__ import annotations

import asyncio

import pytest

from neurova.knowledge.enterprise.fake_adapter import FakeEnterpriseAdapter
from neurova.knowledge.enterprise.registry import EnterpriseIngestor
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def ingestor(store):
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept"},
        {"termId": "has_status", "kind": "relation", "domain": ["Order"]},
    ])
    return EnterpriseIngestor(store, registry=registry)


def _descriptor(tenantId="default"):
    return {"sourceId": "erp_prod", "tenantId": tenantId, "sourceType": "sql",
            "columns": ["order_id", "status"],
            "logicalTable": "orders",
            "subject": {"template": "order:{order_id}"},
            "predicate": {"termId": "has_status"},
            "object": {"column": "status", "kind": "column"},
            "qualifiers": {}, "enabled": True,
            "agentId": "default"}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestEnterpriseIngestAdmission:
    def test_rowsLandAsFactsThroughGate(self, store, ingestor):
        result = ingestor.ingestBatch(
            _descriptor(),
            [{"order_id": "42", "status": "open"},
             {"order_id": "43", "status": "closed"}])

        assert result["admitted"] == 2 and result["rejected"] == 0
        facts = store.searchableFacts(agentId="default")
        assert any(f["canonical_label"] == "order:42" and f["object_term"] == "open"
                   for f in facts), "事实经咽喉落库"

    def test_badRowDoesNotDragTheBatch(self, store, ingestor):
        """本体违规的一行只退它自己，finding 留名——好行照常落库。"""
        result = ingestor.ingestBatch(
            _descriptor(),
            [{"order_id": "42", "status": "open"},
             {"order_id": "43", "status": ""}])   # 空 objectTerm ⇒ admit 必填校验拒

        assert result["admitted"] == 1
        assert result["rejected"] >= 1
        assert result["rejections"], "被拒行留名"

    def test_replayIsIdempotent(self, store, ingestor):
        rows = [{"order_id": "42", "status": "open"}]
        first = ingestor.ingestBatch(_descriptor(), rows)
        before = len(store.searchableFacts(agentId="default"))

        second = ingestor.ingestBatch(_descriptor(), rows)

        assert first["admitted"] == 1 and second["admitted"] == 1, \
            "重放走咽喉内容键去重，不产生重复事实"
        assert len(store.searchableFacts(agentId="default")) == before

    def test_crossTenantInvisible(self, store, ingestor):
        ingestor.ingestBatch(_descriptor(tenantId="tenant-a"),
                             [{"order_id": "42", "status": "open"}])

        factsB = store.searchableFacts(agentId="default", tenantId="tenant-b")
        assert all(f["object_term"] != "open" or f["canonical_label"] != "order:42"
                   for f in factsB), "租户隔离：tenant-b 看不到 tenant-a 的接入事实"

    def test_registryWhitelistDefaultEmpty(self):
        from neurova.knowledge.enterprise.registry import EnterpriseSourceRegistry

        registry = EnterpriseSourceRegistry()
        assert registry.sources() == [], "默认不注册任何真实适配器"
        with pytest.raises(ValueError, match="白名单"):
            registry.register("x", "telepathy", FakeEnterpriseAdapter())
