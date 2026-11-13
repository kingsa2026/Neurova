# -*- coding: utf-8 -*-
"""C5（graphiti 对照批）：社区图增量自动维护。

rebuildIfDrifted：新检测结果与既有社区行按成员集合 Jaccard 比对，漂移
超阈值才全量替换（同事务先删后插）——修掉旧 detect 重复调用累积重复
社区行的病。pipeline.run/rollback 落盘后自动触发（fail-soft，不影响
本体流水线主结果）；手动 refresh 端点与 detect 并列（admin）。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.community_graph import CommunityGraphBuilder
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.pipeline import OntologyPipeline

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
ALICE = {"user_id": "1", "username": "alice", "role": "user", "tenant_id": "default"}
PREFIX = "/v1/knowledge"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


def _seedCluster(store, prefix, size=3):
    """一条链式簇：prefix0 -linked-> prefix1 -linked-> ..."""
    from neurova.knowledge.foundation.admission import (
        AdmissionRequest,
        productionAdmissionGate,
    )
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(store)
    registry.register("linked", "relation")
    gate = productionAdmissionGate(store)
    for i in range(size - 1):
        src, dst = "%s%d" % (prefix, i), "%s%d" % (prefix, i + 1)
        content = "%s linked %s" % (src, dst)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=src, predicateTermId="linked",
            objectTerm=dst, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))


class TestRebuildIfDrifted:
    def test_firstBuildWritesCommunities(self, store):
        _seedCluster(store, "A")
        builder = CommunityGraphBuilder(store, agentId="default", tenantId="default")
        report = builder.rebuildIfDrifted()
        assert report["refreshed"] is True
        assert report["communities"] >= 1
        assert builder.loadCommunities(), "首建落行"

    def test_noDriftSkipsRewrite(self, store):
        _seedCluster(store, "A")
        builder = CommunityGraphBuilder(store, agentId="default", tenantId="default")
        builder.rebuildIfDrifted()
        before = builder.loadCommunities()
        report = builder.rebuildIfDrifted()
        assert report["refreshed"] is False
        assert report["drift"] == 0.0
        assert builder.loadCommunities() == before, "无漂移不重写（community_id 不变）"

    def test_driftTriggersReplaceWithoutAccumulation(self, store):
        _seedCluster(store, "A")
        builder = CommunityGraphBuilder(store, agentId="default", tenantId="default")
        builder.rebuildIfDrifted()
        _seedCluster(store, "B")  # 新簇入图 → 漂移
        report = builder.rebuildIfDrifted()
        assert report["refreshed"] is True
        rows = builder.loadCommunities()
        labels = [frozenset(r["member_labels"]) for r in rows]
        assert len(labels) == len(set(labels)), "不累积重复社区行"
        joined = {m for r in rows for m in r["member_labels"]}
        assert {"B0", "B1", "B2"} <= joined, "新簇成员入册"

    def test_repeatedRebuildKeepsTableClean(self, store):
        _seedCluster(store, "A")
        builder = CommunityGraphBuilder(store, agentId="default", tenantId="default")
        counts = []
        for _ in range(3):
            builder.rebuildIfDrifted()
            counts.append(len(builder.loadCommunities()))
        assert len(set(counts)) == 1, "重复维护不累积行"


class TestPipelineIntegration:
    def test_runTriggersCommunityRefresh(self, store):
        _seedCluster(store, "A")
        pipeline = OntologyPipeline(store)
        result = pipeline.run(
            agentId="default", tenantId="default",
            factCandidates=[{"subjectLabel": "A0", "predicateTermId": "linked",
                             "objectTerm": "A9"}])
        assert result["accepted"] is True
        assert result["communities"]["communities"] >= 1, "落盘后社区自动刷新读数"

    def test_runRefreshFailSoft(self, store, monkeypatch):
        _seedCluster(store, "A")

        def _boom(self, *args, **kwargs):
            raise RuntimeError("社区检测炸了")

        monkeypatch.setattr(CommunityGraphBuilder, "rebuildIfDrifted", _boom)
        pipeline = OntologyPipeline(store)
        result = pipeline.run(
            agentId="default", tenantId="default",
            factCandidates=[{"subjectLabel": "A0", "predicateTermId": "linked",
                             "objectTerm": "A9"}])
        assert result["accepted"] is True, "社区刷新失败不影响流水线主结果"
        assert "error" in result["communities"], "失败读数如实带 error"

    def test_rollbackTriggersRefreshFailSoft(self, store):
        _seedCluster(store, "A")
        pipeline = OntologyPipeline(store)
        first = pipeline.run(agentId="default", tenantId="default",
                             factCandidates=[])
        assert first["accepted"] is True
        result = pipeline.rollback(first["baselineId"], tenantId="default")
        assert result["accepted"] is True
        assert "communities" in result, "回滚后也触发社区增量维护读数"


class TestRefreshEndpoint:
    @pytest.fixture
    def client(self, store, monkeypatch):
        from neurova.api.endpoints import knowledge_ontology

        # _ontologyParts 走全局门面——按仓纪律注入隔离实例，不碰生产库
        monkeypatch.setattr(
            "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store)
        app = FastAPI()
        app.include_router(knowledge_ontology.router, prefix=PREFIX)
        holder = {"user": dict(ADMIN)}
        # require_admin() 闭包吃的是 strictIdentityGate（= auth.get_current_user
        # 本体）——override 必须打在本体上，打 get_current_user_or_service 不生效
        app.dependency_overrides[knowledge_auth.get_current_user] = (
            lambda: holder["user"])
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = (
            lambda: holder["user"])
        return TestClient(app), holder

    def test_refresh_adminGated(self, client):
        client, holder = client
        holder["user"] = dict(ALICE)
        resp = client.post(PREFIX + "/ontology/communities/refresh")
        assert resp.status_code == 403

    def test_refresh_returnsReadout(self, client, store):
        _seedCluster(store, "A")
        client, _holder = client
        resp = client.post(PREFIX + "/ontology/communities/refresh")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["refreshed"] is True
        assert data["communities"] >= 1
