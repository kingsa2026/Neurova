# -*- coding: utf-8 -*-
"""多租户读隔离：条目/检索/FTS/事实都按 tenant_id 分区，管理员不跨租户穿透。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.fts_index import KnowledgeFtsIndex
from neurova.knowledge.repository import KnowledgeRepository

T1_ADMIN = {"user_id": "u1", "username": "a", "role": "admin", "tenant_id": "t1"}
T2_ADMIN = {"user_id": "u2", "username": "b", "role": "admin", "tenant_id": "t2"}


@pytest.fixture()
def repo(tmp_path):
    r = KnowledgeRepository(str(tmp_path / "kb"))
    r.create_knowledge("agent", "租户一文档", "alpha 检索内容",
                       owner_user_id="u1", tenant_id="t1", visibility="public")
    r.create_knowledge("agent", "租户二文档", "alpha 检索内容",
                       owner_user_id="u2", tenant_id="t2", visibility="public")
    return r


def _ids(items):
    return {item["title"] for item in items}


class TestRepositoryIsolation:
    def testAdminOnlySeesOwnTenant(self, repo):
        assert _ids(repo.visible_items(T1_ADMIN)) == {"租户一文档"}
        assert _ids(repo.visible_items(T2_ADMIN)) == {"租户二文档"}

    def testSearchOnlyReturnsOwnTenant(self, repo):
        hits = repo.search_visible_items(T1_ADMIN, "alpha", limit=10)

        assert _ids(hits) == {"租户一文档"}

    def testLegacyEntryDefaultsToDefaultTenant(self, repo):
        repo.create_knowledge("agent", "旧条目", "no tenant", visibility="public")

        legacy = [item for item in repo.visible_items(
            {"user_id": "x", "role": "user", "tenant_id": "default"}, scope="public"
        ) if item["title"] == "旧条目"]
        assert legacy and legacy[0]["tenant_id"] == "default"


class TestFtsIsolation:
    def testSearchFiltersByTenant(self, tmp_path):
        index = KnowledgeFtsIndex(str(tmp_path / "fts.db"))
        index.reconcile({"agent": [
            {"knowledge_id": "a", "title": "租户一", "content": "alpha", "tenant_id": "t1",
             "visibility": "public", "lifecycle_status": "active", "updated_at": 1},
            {"knowledge_id": "b", "title": "租户二", "content": "alpha", "tenant_id": "t2",
             "visibility": "public", "lifecycle_status": "active", "updated_at": 1},
        ]})

        t1 = index.search("alpha", {"user_id": "u1", "tenant_id": "t1"})
        t2 = index.search("alpha", {"user_id": "u2", "tenant_id": "t2"})

        assert [row["knowledge_id"] for row in t1] == ["a"]
        assert [row["knowledge_id"] for row in t2] == ["b"]
        index.close()


class TestFactIsolation:
    def testSameTripleDifferentTenantDoesNotCollide(self, tmp_path):
        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        subjectKey = store.upsertSubject("agent", "Alpha")
        first = store.upsertFact("agent", subjectKey, "pred.budget", "100万元",
                                 "预算 100 万元", contentKey="ck:100", tenantId="t1")
        second = store.upsertFact("agent", subjectKey, "pred.budget", "100万元",
                                  "预算 100 万元", contentKey="ck:100", tenantId="t2")

        assert first != second
        assert store.fact(first)["tenant_id"] == "t1"
        assert [f["fact_id"] for f in store.searchableFacts(tenantId="t1")] == [first]
        assert [f["fact_id"] for f in store.searchableFacts(tenantId="t2")] == [second]
        store.close()

    def testActivityCarriesTenant(self, tmp_path):
        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        activityId = store.insertActivity("admit", tenantId="t1")

        assert store.activity(activityId)["tenant_id"] == "t1"
        store.close()


class TestApiWritesTenant:
    def testCreateUsesIdentityTenant(self, tmp_path, monkeypatch):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_core.get_repository", lambda: repo
        )
        app = FastAPI()
        app.include_router(knowledge_module.router, prefix="/v1/knowledge")
        app.dependency_overrides[
            knowledge_auth.get_current_user_or_service
        ] = lambda: dict(T1_ADMIN)
        client = TestClient(app)

        resp = client.post("/v1/knowledge", json={"title": "导入", "content": "内容"})

        assert resp.status_code == 200, resp.text
        item = repo.visible_items(T1_ADMIN, scope="private")[0]
        assert item["tenant_id"] == "t1"
        assert repo.visible_items(T2_ADMIN) == []


class TestSubjectAndGraphTenant:
    def testSameLabelInTwoTenantsIsSeparateSubject(self, tmp_path):
        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        key1 = store.upsertSubject("agent", "预算口径", tenantId="t1")
        key2 = store.upsertSubject("agent", "预算口径", tenantId="t2")

        assert key1 != key2
        assert [s["subject_key"] for s in store.listSubjects("agent", tenantId="t1")] == [key1]
        assert store.resolveSubjectKey("agent", "预算口径", tenantId="t2") == key2
        store.close()

    def testCrossTenantMergeIsRejected(self, tmp_path):
        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        key1 = store.upsertSubject("agent", "甲", tenantId="t1")
        key2 = store.upsertSubject("agent", "乙", tenantId="t2")

        with pytest.raises(ValueError, match="跨租户"):
            store.mergeSubjects(key1, key2, reason="越权")
        store.close()

    def testGraphManagerIsDirectoryIsolatedPerTenant(self):
        from neurova.cognitive_layers.knowledge_graph.manager import (
            get_agent_knowledge_graph_manager,
        )

        defaultGraph = get_agent_knowledge_graph_manager("tenant-agent")
        t1Graph = get_agent_knowledge_graph_manager("tenant-agent", tenant_id="t1")
        t2Graph = get_agent_knowledge_graph_manager("tenant-agent", tenant_id="t2")

        assert len({id(defaultGraph), id(t1Graph), id(t2Graph)}) == 3
        assert defaultGraph.tenant_id == "default"
        assert t1Graph.tenant_id == "t1"
        assert t1Graph._storage_dir != t2Graph._storage_dir


class TestTenantScopedExpiry:
    def testEntryExpiryOnlyTouchesOwnTenant(self, repo):
        t1 = repo.create_knowledge("agent", "租户一到期", "x", tenant_id="t1",
                                   visibility="public", valid_until="2020-01-01")
        t2 = repo.create_knowledge("agent", "租户二到期", "x", tenant_id="t2",
                                   visibility="public", valid_until="2020-01-01")

        result = repo.expireDueEntries(apply=True, tenantId="t1")

        assert result["archived"] == 1
        assert repo.get_item("agent", t1["knowledge_id"])["lifecycle_status"] != "active"
        assert repo.get_item("agent", t2["knowledge_id"])["lifecycle_status"] == "active"

    def testFactExpiryOnlyTouchesOwnTenant(self, tmp_path):
        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        subject1 = store.upsertSubject("agent", "甲", tenantId="t1")
        subject2 = store.upsertSubject("agent", "乙", tenantId="t2")
        fact1 = store.upsertFact("agent", subject1, "p", "o", "t1 fact",
                                 tenantId="t1", validUntil="2020-01-01")
        fact2 = store.upsertFact("agent", subject2, "p", "o", "t2 fact",
                                 tenantId="t2", validUntil="2020-01-01")

        expired = store.expireDueFacts(tenantId="t1")

        assert expired == 1
        assert store.fact(fact1)["status"] == "expired"
        assert store.fact(fact2)["status"] == "active"
        store.close()


class TestDocumentStats:
    def testOcrCoverageIsTenantScoped(self, repo):
        repo.create_knowledge("agent", "扫描件", "x", tenant_id="t1",
                              visibility="public", document_id="doc-1",
                              page_count=3, ocr_used=True,
                              ocr_confidence_avg=0.8)
        repo.create_knowledge("agent", "普通件", "x", tenant_id="t1",
                              visibility="public", document_id="doc-2",
                              page_count=1)
        repo.create_knowledge("agent", "他租户", "x", tenant_id="t2",
                              visibility="public", document_id="doc-3",
                              page_count=9, ocr_used=True)

        stats = repo.documentStats("t1")

        assert stats["document_count"] == 2
        assert stats["ocr_document_count"] == 1
        assert stats["ocr_coverage"] == 0.5
        assert stats["page_count"] == 4
        assert stats["ocr_confidence_avg"] == 0.8


class TestGraphReadIsolation:
    def test_temporalAndGraphWalkersStayInTenant(self, tmp_path):
        from neurova.knowledge.foundation.graph_walk import GraphFactWalker
        from neurova.knowledge.foundation.temporal_facts import TemporalFactReader

        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        for tenant, label, obj in (("t1", "甲方", "乙方"), ("t2", "丙方", "丁方")):
            subject = store.upsertSubject("agent", label, tenantId=tenant)
            store.upsertFact("agent", subject, "part_of", obj,
                             "%s → %s" % (label, obj), tenantId=tenant)
            second = store.upsertSubject("agent", obj, tenantId=tenant)
            store.upsertFact("agent", second, "part_of", obj + "2",
                             "%s → %s2" % (obj, obj), tenantId=tenant)

        reader = TemporalFactReader(store, agentId="agent")
        graph = GraphFactWalker(store, agentId="agent")

        t1Facts = reader.forQuery("甲方", tenantId="t1")
        t2Facts = reader.forQuery("甲方", tenantId="t2")
        t1Hops = graph.walkFromQuery("甲方", tenantId="t1")
        t2Hops = graph.walkFromQuery("甲方", tenantId="t2")

        assert t1Facts and not t2Facts
        assert t1Hops and not t2Hops
        assert all(f["tenant_id"] == "t1" for f in t1Facts)
        store.close()


class TestContentDedup:
    def testSameTenantSameContentReturnsExistingAndKeepsSourceEvidence(self, repo):
        first = repo.create_knowledge(
            "agent", "文档", "正文  相同", tenant_id="t1", source="upload:a",
            source_type="md", dedupe=True,
        )
        second = repo.create_knowledge(
            "agent", "文档副本", "正文 相同", tenant_id="t1", source="upload:b",
            source_type="md", dedupe=True,
        )

        assert second["knowledge_id"] == first["knowledge_id"]
        assert second.get("duplicate") is True
        stored = repo.get_item("agent", first["knowledge_id"])
        assert [s["source"] for s in stored["sources"]] == ["upload:a", "upload:b"]
        assert stored["title"] == "文档"

    def testSameContentDifferentTenantIsNotDeduped(self, repo):
        first = repo.create_knowledge("agent", "文档", "正文", tenant_id="t1", dedupe=True)
        second = repo.create_knowledge("agent", "文档", "正文", tenant_id="t2", dedupe=True)

        assert second["knowledge_id"] != first["knowledge_id"]


class TestMetadataFilters:
    def testAuthorSourceTypeOcrAndPageFilters(self, repo):
        repo.create_knowledge(
            "agent", "扫描预算", "共同关键词", tenant_id="t1", visibility="public",
            author="张三", source_type="pdf", ocr_used=True, page_count=5,
        )
        repo.create_knowledge(
            "agent", "文本预算", "共同关键词", tenant_id="t1", visibility="public",
            author="李四", source_type="md", ocr_used=False, page_count=1,
        )
        user = {"user_id": "u", "tenant_id": "t1", "role": "user"}

        def titles(**kwargs):
            hits = repo.search_visible_items(user, "共同关键词", limit=10, **kwargs)
            return {hit["title"] for hit in hits}

        assert titles(author="张三") == {"扫描预算"}
        assert titles(source_type="md") == {"文本预算"}
        assert titles(ocr_used=True) == {"扫描预算"}
        assert titles(page_min=2) == {"扫描预算"}
