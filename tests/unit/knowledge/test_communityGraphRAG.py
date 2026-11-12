# -*- coding: utf-8 -*-
"""W8 社区检测与 global/drift 检索（specs/2026-11-12 §9）：标签传播（stdlib 纯
Python）在既有图上迭代至稳定；层级＝对社区代表点图再检测；global/drift 命中断言；
摘要生成经注入的摘要器（LLM 客户端惰性复用，缺省摘要空＝诚实形态）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.community_graph import (
    CommunityGraphBuilder,
    communityGlobalSearch,
    communityDriftSearch,
)


def _buildGraph(store):
    """小图：两簇（A1-A2-A3 互连；B1-B2-B3 互连），簇间仅 A1-B1 一条弱边。"""
    from neurova.knowledge.foundation.admission import (
        AdmissionRequest,
        productionAdmissionGate,
    )
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    registry = OntologyTermRegistry(store)
    registry.register("cluster_a", "concept")
    registry.register("cluster_b", "concept")
    gate = productionAdmissionGate(store)
    # 簇内多条边走不同谓词（冲突裁决按 (subject,predicate) 分组——同一谓词的
    # 多条事实会被 most_recent 取代到一行）；社区图读面不滤谓词。簇间单条＝弱链。
    registry.register("linked_a", "relation")
    registry.register("linked_b", "relation")
    edges = [("A1", "A2", "linked_a"), ("A2", "A1", "linked_a"),
             ("A2", "A3", "linked_b"), ("A3", "A2", "linked_a"),
             ("A3", "A1", "linked_b"), ("A1", "A3", "linked_a"),
             ("B1", "B2", "linked_a"), ("B2", "B1", "linked_a"),
             ("B2", "B3", "linked_b"), ("B3", "B2", "linked_a"),
             ("B3", "B1", "linked_b"), ("B1", "B3", "linked_a"),
             ("A1", "B1", "linked_b")]
    for src, dst, pred in edges:
        content = "%s %s %s" % (src, pred, dst)
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=src, predicateTermId=pred,
            objectTerm=dst, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": content}]))
    return registry


@pytest.fixture
def kb(tmp_path):
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


class TestLabelPropagation:
    def test_twoClustersDetected(self, kb):
        _buildGraph(kb)
        builder = CommunityGraphBuilder(kb, agentId="default", tenantId="default")
        communities = builder.detect()
        assert len(communities) >= 2, "两簇应被分开"
        members = {frozenset(c["member_labels"]) for c in communities}
        assert any({"A1", "A2", "A3"} <= m for m in members), "A 簇完整"
        assert any({"B1", "B2", "B3"} <= m for m in members), "B 簇完整"

    def test_persistsAndReloads(self, kb):
        _buildGraph(kb)
        builder = CommunityGraphBuilder(kb, agentId="default", tenantId="default")
        communities = builder.detect(summarizer=lambda labels: "摘要:" + ",".join(labels))
        assert communities[0]["summary_text"].startswith("摘要"), "注入摘要器生成摘要"
        # 重载读数（v48 表）
        again = CommunityGraphBuilder(kb, agentId="default", tenantId="default")
        loaded = again.loadCommunities()
        assert len(loaded) == len(communities), "社区读数持久化"


class TestCommunitySearch:
    def test_globalSearchHitsSummary(self, kb):
        _buildGraph(kb)
        builder = CommunityGraphBuilder(kb, agentId="default", tenantId="default")
        builder.detect(summarizer=lambda labels: "维护手册 齿轮箱 " + ",".join(labels))
        hits = communityGlobalSearch(kb, "齿轮箱 维护", agentId="default",
                                     tenantId="default")
        assert hits, "global：查询→社区摘要 map 命中"

    def test_driftSearchFollowsNeighborhood(self, kb):
        _buildGraph(kb)
        builder = CommunityGraphBuilder(kb, agentId="default", tenantId="default")
        builder.detect()
        hits = communityDriftSearch(kb, "A1", agentId="default", tenantId="default")
        assert hits, "drift：实体邻域＋所属社区摘要"
        assert any("A" in str(h.get("labels")) for h in hits)
