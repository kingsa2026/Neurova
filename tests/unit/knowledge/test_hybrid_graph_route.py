# -*- coding: utf-8 -*-
"""图谱条目影子路由：默认不改序，开启后计分并附 graph_support。"""
from __future__ import annotations

from types import SimpleNamespace

from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
from neurova.knowledge.hybrid import hybrid_search_knowledge
from neurova.knowledge.repository import KnowledgeRepository

USER = {"user_id": "u1", "tenant_id": "t1", "role": "user"}


class _Walker:
    def walkFromQuery(self, query, limit=10, tenantId="default", **kwargs):
        return [{
            "id": "fact-1", "entry_id": "k2", "hop": 2,
            "path": "甲方 -part_of-> 乙方", "tenant_id": tenantId,
        }]


def testGraphShadowDoesNotChangeOrderButAttachesEvidence(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    k1 = repo.create_knowledge("agent", "甲方文档", "甲方 预算 内容",
                               tenant_id="t1", visibility="public")
    k2 = repo.create_knowledge("agent", "乙方文档", "乙方 预算 内容",
                               tenant_id="t1", visibility="public")
    baseline = hybrid_search_knowledge(repo, USER, "预算", limit=2, vector_index=None)
    shadow = hybrid_search_knowledge(
        repo, USER, "预算", limit=2, vector_index=None,
        graphRanks=[(k2["knowledge_id"], 1.0)],
        graphSupport={k2["knowledge_id"]: [{"fact_id": "fact-1", "hops": 2}]},
        graphWeight=0.0,
    )

    assert [r["knowledge_id"] for r in shadow] == [r["knowledge_id"] for r in baseline]
    byId = {r["knowledge_id"]: r for r in shadow}
    assert byId[k2["knowledge_id"]]["graph_support"][0]["fact_id"] == "fact-1"
    assert byId[k2["knowledge_id"]]["confidence_breakdown"]["graph"] > 0

    boosted = hybrid_search_knowledge(
        repo, USER, "预算", limit=2, vector_index=None,
        graphRanks=[(k2["knowledge_id"], 1.0)], graphWeight=0.5,
    )
    assert boosted[0]["knowledge_id"] == k2["knowledge_id"]


def testAdapterMapsGraphHopsToEntryRanks():
    adapter = KnowledgeRetrieverAdapter(repo=None, graphWalker=_Walker())
    context = SimpleNamespace(query="甲方", limit=5, metadata={"tenant_id": "t1"})

    ranks, support, weight = adapter._graphRoute(context, "agent", 5)

    assert ranks == [("k2", 1.0)]
    assert support["k2"][0]["fact_id"] == "fact-1"
    assert weight == 0.0
