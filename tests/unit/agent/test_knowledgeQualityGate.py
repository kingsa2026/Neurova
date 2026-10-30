# -*- coding: utf-8 -*-
"""知识路质量门（specs/2026-10-30 §11.4 登记项的根修判据，红灯先行）。

缺陷（探针实测）：链采纳门 quality ≥ min_quality(0.3)，知识路质量 =
0.6×命中数/10 + 0.4×词面重合——别名驱动的命中按**原始查询**计重合（展开词
不计），1 条半重合命中只有 0.26，被链当"不足"整包丢弃，MoE 的 no_memory
占位（score=1.0）反而成为主结果。

本文件钉住两处根因的修法：重合按**实跑查询**计；词面重合通道独立达标
（≥0.4 重合）即过门，不再被计数项稀释。计数通道语义不变（语义/向量命中的
载体），全满与全空两侧行为逐字不变。
"""
from __future__ import annotations

import pytest

from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
from neurova.agent.memory_retrieval_chain import RetrievalContext
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.query_normalization import invalidateQueryNormalizationCache


class FakeRepo:
    """substring 评分的最小仓库（与 test_querySideNormalization 同型）。"""

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
    factStore = KnowledgeFactStore(str(tmp_path / "kb_quality_gate.db"))
    yield factStore
    factStore.close()


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch, store):
    # 显式依赖 store：lambda 闭包模块名会撞上 @pytest.fixture 重绑的定义对象
    monkeypatch.setenv("NEUROVA_KB_MAIN_RERANK", "off")
    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "on")
    monkeypatch.setattr(
        "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
        lambda: store,
    )
    invalidateQueryNormalizationCache()
    yield
    invalidateQueryNormalizationCache()


def _adapterWithEntries(items):
    return KnowledgeRetrieverAdapter(repo=FakeRepo(items))


@pytest.mark.asyncio
async def test_aliasDrivenSingleHit_passesQualityGate(store):
    """1 条别名驱动的相关命中必须过链采纳门（修前 0.26 < 0.3 整包被弃）。"""
    store.upsertSubject("a1", "客户流失率", aliases=["跑量"], tenantId="t1")
    adapter = _adapterWithEntries([
        {"knowledge_id": "k1", "title": "客户流失率口径说明", "content": "按月统计"},
    ])
    result = await adapter.retrieve(RetrievalContext(
        query="跑量", limit=5, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    ))
    assert [m.get("knowledge_id") for m in result.memories] == ["k1"]
    assert result.quality >= 0.3, (
        f"1 条相关命中必须过链采纳门，实得 {result.quality}——低于 min_quality(0.3) "
        "会被链整包丢弃，MoE 的 no_memory 占位反而当选（§11.4 缺陷形态）"
    )


@pytest.mark.asyncio
async def test_qualityScoredOnExecutedQuery(store, monkeypatch):
    """重合必须按实跑查询（含 W1 展开词）计，不按原始查询。"""
    store.upsertSubject("a1", "客户流失率", aliases=["跑量"], tenantId="t1")
    adapter = _adapterWithEntries([
        {"knowledge_id": "k1", "title": "客户流失率口径说明", "content": "按月统计"},
    ])
    captured = {}
    original = KnowledgeRetrieverAdapter.get_quality_score

    def spying(self, items, query):
        captured["query"] = query
        return original(self, items, query)

    monkeypatch.setattr(KnowledgeRetrieverAdapter, "get_quality_score", spying)
    await adapter.retrieve(RetrievalContext(
        query="跑量", limit=5, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    ))
    assert captured["query"] == "跑量 客户流失率", (
        f"质量重合必须按实跑查询计，实得 {captured['query']!r}——按原始查询计，"
        "别名驱动的命中重合恒为 0（双重折损）"
    )


@pytest.mark.asyncio
async def test_irrelevantSingleHit_staysBelowGate():
    """1 条不相关命中依旧不得过门（修法不许放进噪声）。"""
    adapter = _adapterWithEntries([
        {"knowledge_id": "k1", "title": "客户流失率口径说明", "content": "按月统计"},
    ])
    result = await adapter.retrieve(RetrievalContext(
        query="天文学 观测", limit=5, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    ))
    if result.memories:
        assert result.quality < 0.3, f"不相关命中不许过门，实得 {result.quality}"


@pytest.mark.asyncio
async def test_manyHitsWithoutOverlap_countChannelUnchanged():
    """多条无词面重合命中（语义/向量路形态）依旧由计数通道扛过门——行为不变。"""
    adapter = _adapterWithEntries([
        {"knowledge_id": "k%d" % index, "title": "条目%d" % index, "content": "内容%d"}
        for index in range(6)
    ])
    result = await adapter.retrieve(RetrievalContext(
        query="天文学 观测", limit=10, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    ))
    if result.memories:
        assert result.quality >= 0.3, (
            f"计数通道语义必须保持（语义命中无词面重合），实得 {result.quality}"
        )


def test_fullHouseQualityUnchanged():
    """满命中 + 全重合 = 1.0：上界行为逐字不变。"""
    adapter = KnowledgeRetrieverAdapter(repo=FakeRepo([]))
    items = [
        {"title": "客户流失率口径说明", "content": "客户流失率按月统计"}
        for _ in range(10)
    ]
    assert adapter.get_quality_score(items, "客户流失率") == 1.0


def test_emptyStillZero():
    """空结果 0 分：边界不变。"""
    adapter = KnowledgeRetrieverAdapter(repo=FakeRepo([]))
    assert adapter.get_quality_score([], "任意") == 0.0
