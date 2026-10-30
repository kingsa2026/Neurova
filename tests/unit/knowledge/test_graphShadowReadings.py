# -*- coding: utf-8 -*-
"""W3 图谱影子读数（specs/2026-10-30 §4.4 判据，红灯先行）。

影子模式下 graph 候选不改变排序，但必须有"候选与最终 top-k 关系"的读数——
否则 2026-10-24 §4.4 的转正判据（recall 不降、NDCG 提升才切 on）永远悬空。
"""
from __future__ import annotations

import pytest

from neurova.knowledge.hybrid import hybrid_search_knowledge
from neurova.knowledge.retrieval_metrics import (
    get_retrieval_metrics,
    reset_retrieval_metrics,
)


class FakeRepo:
    def __init__(self, items):
        self._items = items

    def visible_items(self, user, **kwargs):
        return [dict(item) for item in self._items]

    def search_visible_items(self, *, user, query, limit, **kwargs):
        tokens = [token for token in str(query or "").split() if token]
        scored = []
        for item in self._items:
            text = str(item.get("title", "")) + " " + str(item.get("content", ""))
            hits = sum(1 for token in tokens if token in text)
            if hits:
                scored.append({**item, "score": hits / max(1, len(tokens))})
        scored.sort(key=lambda row: (-row["score"], row["knowledge_id"]))
        return scored[:limit]


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_MAIN_RERANK", "off")
    reset_retrieval_metrics()
    yield
    reset_retrieval_metrics()


@pytest.fixture()
def repo():
    return FakeRepo([
        {"knowledge_id": "k1", "title": "词条甲", "content": "词条甲的正文"},
        {"knowledge_id": "k2", "title": "词条乙", "content": "词条乙的正文"},
        {"knowledge_id": "k3", "title": "词条丙", "content": "词条丙的正文"},
    ])


def test_shadowGraphRanks_keepResultsIdentical_butProduceReadings(repo):
    query = "词条甲"
    off = hybrid_search_knowledge(repo, {"user_id": "u1"}, query, limit=3, vector_index=None)
    shadow = hybrid_search_knowledge(
        repo, {"user_id": "u1"}, query, limit=3, vector_index=None,
        graphRanks=[("k2", 1.0), ("k_missing", 0.5)], graphWeight=0.0,
    )
    assert [(r["knowledge_id"], r["score"]) for r in shadow] == \
        [(r["knowledge_id"], r["score"]) for r in off], "shadow 不得改变返回（逐字一致）"

    snapshot = get_retrieval_metrics().snapshot()
    shadowReadings = snapshot["graph_shadow"]
    assert shadowReadings["retrievals_with_candidates"] == 1
    assert shadowReadings["candidates_total"] == 2
    # k2 在最终结果里的名次（1 起）；k_missing 不在结果里不计
    assert shadowReadings["top5_reach"] == 1
    assert shadowReadings["top1_reach"] == 0, "k2 不在第一名"
    assert "graph" not in snapshot["route_hits"], (
        "影子档 graph 未参与融合，路计数不得把它算成命中（否则 on 判据恒真）"
    )


def test_onMode_countsGraphRoute_andReach(repo):
    on = hybrid_search_knowledge(
        repo, {"user_id": "u1"}, "词条甲", limit=3, vector_index=None,
        graphRanks=[("k1", 1.0)], graphWeight=0.10,
    )
    assert on[0]["knowledge_id"] == "k1"
    snapshot = get_retrieval_metrics().snapshot()
    assert snapshot["route_hits"].get("graph", 0) >= 1, "on 模式 graph 路必须进路计数"
    readings = snapshot["graph_shadow"]
    assert readings["retrievals_with_candidates"] == 1
    assert readings["top1_reach"] == 1, "graph 首候选 k1 排到第一名"
    assert readings["top5_reach"] == 1


def test_noCandidates_noGraphShadowKey(repo):
    hybrid_search_knowledge(repo, {"user_id": "u1"}, "词条甲", limit=3, vector_index=None)
    assert "graph_shadow" not in get_retrieval_metrics().snapshot(), (
        "无候选不产生读数（缺的读数点名，不伪造 0）"
    )


def test_positionalGraphRanks_alsoMeasured(repo):
    # (repo, user, query, limit, scope, agent_id, vector_index, weights, k,
    #  category, tags, source, updated_after, graphRanks, graphSupport, graphWeight)
    hybrid_search_knowledge(
        repo, {"user_id": "u1"}, "词条甲", 3, "all", None, None, None, 60,
        None, None, None, None, [("k2", 1.0)], None, 0.0,
    )
    readings = get_retrieval_metrics().snapshot()["graph_shadow"]
    assert readings["retrievals_with_candidates"] == 1
    assert readings["candidates_total"] == 1


def test_metrics_snapshot_graph_shadow_absent_after_reset(repo):
    hybrid_search_knowledge(
        repo, {"user_id": "u1"}, "词条甲", limit=3, vector_index=None,
        graphRanks=[("k1", 1.0)], graphWeight=0.10,
    )
    reset_retrieval_metrics()
    assert "graph_shadow" not in get_retrieval_metrics().snapshot()
