# -*- coding: utf-8 -*-
"""W1 查询侧别名归一（specs/2026-10-30 §2.5 判据，红灯先行）。

别名账（knowledge_subjects.aliases_json）此前只有事实层与图锚在读，条目检索
的查询侧从不展开——本文件钉住：展开只追加规范名、shadow 不改排序、off 零开销、
失败让路、合并链消解到幸存主体。
"""
from __future__ import annotations

import pytest

from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
from neurova.agent.memory_retrieval_chain import RetrievalContext
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.hybrid import hybrid_search_knowledge
from neurova.knowledge.query_normalization import (
    invalidateQueryNormalizationCache,
    normalizeMode,
    normalizeQueryForRetrieval,
)
from neurova.knowledge.retrieval_metrics import (
    get_retrieval_metrics,
    reset_retrieval_metrics,
)


class FakeRepo:
    """substring 评分的最小仓库：hybrid 的 tfidf 主路打分即可判命中。"""

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


@pytest.fixture()
def store(tmp_path):
    factStore = KnowledgeFactStore(str(tmp_path / "kb_query_norm.db"))
    yield factStore
    factStore.close()


@pytest.fixture(autouse=True)
def _deterministicEnv(monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_MAIN_RERANK", "off")
    invalidateQueryNormalizationCache()
    yield
    invalidateQueryNormalizationCache()


# ── §2.5 判据 1：别名独有查询 off 脱靶、on 命中 ─────────────────────────

def test_aliasOnlyQuery_missesWhenOff_hitsWhenOn(store, monkeypatch):
    store.upsertSubject("a1", "客户流失率", aliases=["跑量"], tenantId="t1")
    repo = FakeRepo([
        {"knowledge_id": "k1", "title": "客户流失率口径", "content": "按月统计"},
    ])

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "off")
    assert hybrid_search_knowledge(
        repo, {"user_id": "u1"}, "跑量怎么算", limit=5, vector_index=None
    ) == [], "off 档别名查询必须脱靶（现状即缺陷形态）"

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "on")
    norm = normalizeQueryForRetrieval(store, "跑量怎么算", "a1", "t1")
    assert norm.appendedTerms == ["客户流失率"]
    assert norm.expanded == "跑量怎么算 客户流失率"
    on = hybrid_search_knowledge(
        repo, {"user_id": "u1"}, norm.expanded, limit=5, vector_index=None
    )
    assert [row["knowledge_id"] for row in on] == ["k1"]


# ── §2.5 判据 2：shadow 不改排序逐字一致，只带 matchedSubjects 读数 ─────

@pytest.mark.asyncio
async def test_shadowKeepsResultsEqual_andCarriesMatches(store, monkeypatch):
    store.upsertSubject("a1", "客户流失率", aliases=["跑量"], tenantId="t1")
    captured = {}

    def fakeHybrid(*args, **kwargs):
        captured.update(kwargs)
        return [{
            "knowledge_id": "k1", "title": "客户流失率口径", "content": "按月", "score": 0.5,
        }]

    monkeypatch.setattr("neurova.knowledge.hybrid.hybrid_search_knowledge", fakeHybrid)
    monkeypatch.setattr(
        "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
        lambda: store,
    )
    adapter = KnowledgeRetrieverAdapter(repo=FakeRepo([]))
    context = RetrievalContext(
        query="跑量怎么算", limit=2, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    )

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "off")
    offResult = await adapter.retrieve(context)
    assert "query_normalization" not in offResult.metadata

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "shadow")
    shadowResult = await adapter.retrieve(context)
    assert shadowResult.memories == offResult.memories, "shadow 不得改变返回"
    assert captured["query"] == "跑量怎么算", "shadow 不得改写查询"
    normMeta = shadowResult.metadata["query_normalization"]
    assert normMeta["mode"] == "shadow"
    assert normMeta["changed"] is False
    match = normMeta["matched_subjects"][0]
    assert match["subject_key"].startswith("subj_")
    assert match["canonical_label"] == "客户流失率"
    assert match["matched_term"] == "跑量"
    assert match["matched_via"] == "alias"


# ── §2.5 判据 3：规范词查询不追加、排序不劣化 ───────────────────────────

def test_canonicalQuery_onDoesNotExpand(store, monkeypatch):
    store.upsertSubject("a1", "客户流失率", tenantId="t1")
    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "on")
    norm = normalizeQueryForRetrieval(store, "客户流失率 口径", "a1", "t1")
    assert norm.appendedTerms == []
    assert norm.expanded == norm.original
    assert norm.matchedSubjects[0].matchedVia == "canonical"


# ── §2.5 判据 4：merged_into 链上的旧别名消解到幸存主体 ─────────────────

def test_mergedAlias_resolvesToSurvivor(store, monkeypatch):
    oldKey = store.upsertSubject("a1", "老指标", aliases=["老叫法"], tenantId="t1")
    newKey = store.upsertSubject("a1", "新指标", tenantId="t1")
    store.mergeSubjects(oldKey, newKey, reason="测试合并")

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "on")
    norm = normalizeQueryForRetrieval(store, "老叫法是什么", "a1", "t1")
    assert norm.matchedSubjects[0].subjectKey == newKey
    assert norm.matchedSubjects[0].canonicalLabel == "新指标"
    assert norm.appendedTerms == ["新指标"]


# ── §2.5 判据 5：事实库异常让路，返回原查询不抛 ─────────────────────────

def test_storeFailure_failSoft(monkeypatch):
    class BoomStore:
        def listSubjects(self, *args, **kwargs):
            raise RuntimeError("别名账不可用")

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "on")
    norm = normalizeQueryForRetrieval(BoomStore(), "随便问", "a1", "t1")
    assert norm.expanded == "随便问"
    assert norm.matchedSubjects == []
    assert norm.changed is False


# ── §2.5 判据 6：追加词上限 4、总长上限 512 ─────────────────────────────

def test_expansionCaps(store, monkeypatch):
    for index in range(6):
        store.upsertSubject("a1", "指标%d" % index, aliases=["别名%d" % index], tenantId="t1")
    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "on")
    query = " ".join("别名%d" % index for index in range(6)) + " 汇总"
    norm = normalizeQueryForRetrieval(store, query, "a1", "t1")
    assert len(norm.matchedSubjects) == 6
    assert len(norm.appendedTerms) == 4
    assert len(norm.expanded) <= 512


# ── §2.5 判据 7：缓存 TTL 内不重查库，失效后立即重查；off 零开销 ────────

def test_cache_reusesUntilInvalidated_andOffNeverTouchesStore(store, monkeypatch):
    calls = {"list": 0}
    realList = store.listSubjects

    def countingList(*args, **kwargs):
        calls["list"] += 1
        return realList(*args, **kwargs)

    store.listSubjects = countingList
    store.upsertSubject("a1", "客户流失率", aliases=["跑量"], tenantId="t1")

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "off")
    normalizeQueryForRetrieval(store, "跑量", "a1", "t1")
    assert calls["list"] == 0, "off 档零开销：不许碰别名账"

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "on")
    normalizeQueryForRetrieval(store, "跑量", "a1", "t1")
    normalizeQueryForRetrieval(store, "跑量", "a1", "t1")
    assert calls["list"] == 1, "TTL 内必须复用缓存"

    invalidateQueryNormalizationCache()
    normalizeQueryForRetrieval(store, "跑量", "a1", "t1")
    assert calls["list"] == 2, "失效后必须立即重查"


def test_normalizeMode_invalidFallsBackToOff(monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "随便")
    assert normalizeMode() == "off"
    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "shadow")
    assert normalizeMode() == "shadow"
    monkeypatch.delenv("NEUROVA_KB_QUERY_NORMALIZE", raising=False)
    assert normalizeMode() == "off"


# ── B1 落点：retrieval_metrics 记录归一读数（shadow/on 才记，off 不记）──

@pytest.mark.asyncio
async def test_metrics_recordsQueryNormalization_onlyWhenActive(store, monkeypatch):
    store.upsertSubject("a1", "客户流失率", aliases=["跑量"], tenantId="t1")
    monkeypatch.setattr(
        "neurova.knowledge.hybrid.hybrid_search_knowledge",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
        lambda: store,
    )
    adapter = KnowledgeRetrieverAdapter(repo=FakeRepo([]))
    context = RetrievalContext(
        query="跑量怎么算", limit=2, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    )

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "off")
    reset_retrieval_metrics()
    await adapter.retrieve(context)
    assert "query_normalization" not in get_retrieval_metrics().snapshot()

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "shadow")
    reset_retrieval_metrics()
    await adapter.retrieve(context)
    snapshot = get_retrieval_metrics().snapshot()
    assert snapshot["query_normalization"]["retrievals"] == 1
    assert snapshot["query_normalization"]["with_matches"] == 1
    assert snapshot["query_normalization"]["matched_subjects_total"] == 1
