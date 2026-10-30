# -*- coding: utf-8 -*-
"""W3 golden multi-hop 评测（specs/2026-10-30 §4.2/§4.4，红灯先行）。

两条"必须走关系才能命中"的 golden 链 + 一条词法对照例，全部挂
RetrievalBenchmark 主锚（ADR 0016）：graph 关时多跳脱靶、开时命中，
对照例不回归——这是 2026-10-24 §4.4 "recall 不降、NDCG 提升才切 on"
判据的落地读数。
"""
from __future__ import annotations

import pytest

from neurova.knowledge.evaluation.retrieval_benchmark import RetrievalBenchmark
from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger
from neurova.knowledge.hybrid import hybrid_search_knowledge

AGENT = "bench"


class FakeRepo:
    """词法静默/强命中的最小仓库：golden 期望只经图谱路可达。"""

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


ENTRIES = [
    {"knowledge_id": "k1", "title": "阿尔法指标说明", "content": "阿尔法指标的常规说明"},
    {"knowledge_id": "k2", "title": "无关材料壹", "content": "别的领域内容"},
    {"knowledge_id": "k3", "title": "伽马口径细则", "content": "某口径的细则正文"},
    {"knowledge_id": "k4", "title": "无关材料贰", "content": "别的领域内容"},
    {"knowledge_id": "k5", "title": "茁口径细则", "content": "另一条口径的细则正文"},
    {"knowledge_id": "k6", "title": "无关材料叁", "content": "别的领域内容"},
]

GOLDEN_CASES = [
    ("阿尔法指标 是什么", ["k3"]),      # 链一：阿尔法→贝塔维度→伽马口径(k3)
    ("德尔塔指标 概览", ["k5"]),        # 链二：德尔塔→伊普西隆维度→茁口径(k5)
    ("阿尔法指标说明", ["k1"]),         # 词法对照例：不开图也必须命中
]


@pytest.fixture()
def kb(tmp_path):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    ledger = KnowledgeLineageLedger(store, toolVersion="golden-test")

    # 链一：阿尔法指标 --关联--> 贝塔维度 --归属--> 伽马口径（事实挂 k3）
    subjAlpha = store.upsertSubject(AGENT, "阿尔法指标")
    subjBeta = store.upsertSubject(AGENT, "贝塔维度")
    subjGamma = store.upsertSubject(AGENT, "伽马口径")
    factA = store.upsertFact(AGENT, subjAlpha, "relates_to", "贝塔维度", "阿尔法关联贝塔")
    factB = store.upsertFact(AGENT, subjBeta, "belongs_to", "伽马口径", "贝塔归属伽马")
    ledger.attach(factB, [{
        "actorType": "pipeline", "actorId": "golden",
        "mediumRef": "entry:k3", "statementText": "伽马口径细则见 k3",
    }])

    # 链二：德尔塔指标 --关联--> 伊普西隆维度 --归属--> 茁口径（事实挂 k5）
    subjDelta = store.upsertSubject(AGENT, "德尔塔指标")
    subjEpsilon = store.upsertSubject(AGENT, "伊普西隆维度")
    subjZeta = store.upsertSubject(AGENT, "茁口径")
    store.upsertFact(AGENT, subjDelta, "relates_to", "伊普西隆维度", "德尔塔关联伊普西隆")
    factE = store.upsertFact(AGENT, subjEpsilon, "belongs_to", "茁口径", "伊普西隆归属茁")
    ledger.attach(factE, [{
        "actorType": "pipeline", "actorId": "golden",
        "mediumRef": "entry:k5", "statementText": "茁口径细则见 k5",
    }])
    yield store
    store.close()


def _graphRouteOn(store, query):
    """复刻 adapter._graphRoute 的 on 形态：fact→entry 映射 + 0.10 权重。"""
    walker = GraphFactWalker(store, agentId=AGENT)
    hops = walker.walkFromQuery(query, maxHops=2, limit=6, tenantId="default")
    ranks, support = [], {}
    for hop in hops or []:
        entryId = str(hop.get("entry_id") or "")
        if not entryId or entryId in dict(ranks):
            continue
        ranks.append((entryId, 1.0 / (len(ranks) + 1)))
        support.setdefault(entryId, []).append({
            "fact_id": hop.get("id"), "hops": hop.get("hop"), "path": hop.get("path"),
        })
    return ranks, support


def test_goldenMultiHop_offMisses_onHits_withRegressionGate(kb, tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_MAIN_RERANK", "off")
    repo = FakeRepo(ENTRIES)
    bench = RetrievalBenchmark(str(tmp_path / "eval.db"))
    for query, expected in GOLDEN_CASES:
        bench.addCase(query, expected, createdBy="golden", labelingMethod="manual")

    def searchOff(query):
        return hybrid_search_knowledge(
            repo, {}, query, limit=3, agent_id=AGENT, vector_index=None,
        )

    def searchOn(query):
        ranks, support = _graphRouteOn(kb, query)
        return hybrid_search_knowledge(
            repo, {}, query, limit=3, agent_id=AGENT, vector_index=None,
            graphRanks=ranks or None, graphSupport=support or None, graphWeight=0.10,
        )

    reportOff = bench.run(repo, user={}, agentId=AGENT, topK=3,
                          searchFn=searchOff, variant="graph_off", note="golden 关图")
    reportOn = bench.run(repo, user={}, agentId=AGENT, topK=3,
                         searchFn=searchOn, variant="graph_on", note="golden 开图")

    assert reportOff["measure_state"] == "measured"
    assert reportOn["measure_state"] == "measured"
    # 多跳例关图脱靶、开图命中；词法对照例两侧都命中（不回归）
    assert reportOff["recall_at_k"] == pytest.approx(1 / 3)
    assert reportOn["recall_at_k"] == pytest.approx(1.0)
    assert reportOn["ndcg_at_k"] - reportOff["ndcg_at_k"] >= 0.05, (
        "转正判据：NDCG@10 提升 ≥ 0.05（specs/2026-10-30 §4.3）"
    )

    verdict = bench.compareVariants(reportOff, reportOn, minCases=3, tolerance=0.01)
    assert verdict["verdict"] == "improved"
    bench.gateNoRegression(reportOff, reportOn, minCases=3, tolerance=0.01)


def test_goldenMultiHop_onResults_carryPathEvidence(kb, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_MAIN_RERANK", "off")
    repo = FakeRepo(ENTRIES)
    ranks, support = _graphRouteOn(kb, "阿尔法指标 是什么")
    assert "k3" in dict(ranks), "关系可达的条目必须进图谱秩"
    hits = hybrid_search_knowledge(
        repo, {}, "阿尔法指标 是什么", limit=3, agent_id=AGENT, vector_index=None,
        graphRanks=ranks, graphSupport=support, graphWeight=0.10,
    )
    k3 = next(row for row in hits if row["knowledge_id"] == "k3")
    evidence = k3["graph_support"][0]
    assert evidence["hops"] == 2, "golden 链必须是两跳（hop≥2 才算走查命中）"
    assert evidence["path"], "命中必须带完整 path"
