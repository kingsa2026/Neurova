# -*- coding: utf-8 -*-
"""W2 检索脱靶登记（specs/2026-10-30 §3.4 判据，红灯先行）。

0 命中查询 → 候选别名行（pending，同查询累计 occurrences）；人工 approve 把别名
并入主体表并即时失效归一缓存——"写入 → 读取 → 反馈"闭环在本文件钉死。
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
from neurova.agent.memory_retrieval_chain import RetrievalContext
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.query_normalization import (
    invalidateQueryNormalizationCache,
    normalizeQueryForRetrieval,
)


@pytest.fixture()
def store(tmp_path):
    factStore = KnowledgeFactStore(str(tmp_path / "kb_alias_candidates.db"))
    yield factStore
    factStore.close()


@pytest.fixture(autouse=True)
def _invalidateCache():
    invalidateQueryNormalizationCache()
    yield
    invalidateQueryNormalizationCache()


# ── §3.4 判据 1：0 命中落 pending 行；同查询 occurrences+1 不加行 ────────

def test_captureCreatesPendingRow_andDedupesOccurrences(store):
    first = store.captureAliasCandidate("a1", "跑量怎么算", tenantId="t1")
    second = store.captureAliasCandidate("a1", "跑量怎么算", tenantId="t1")
    assert first and second == first
    rows = store.listAliasCandidates(tenantId="t1", status="pending")
    assert len(rows) == 1
    assert rows[0]["occurrences"] == 2
    assert rows[0]["normalized_query"] == "跑量怎么算"
    assert rows[0]["raw_query"] == "跑量怎么算"


def test_captureEmptyOrWhitespaceQueryReturnsNone(store):
    assert store.captureAliasCandidate("a1", "   ", tenantId="t1") is None
    assert store.captureAliasCandidate("a1", "", tenantId="t1") is None
    assert store.listAliasCandidates(tenantId="t1") == []


# ── §3.4 判据配套：捕获时回填 resolveSubjectKey 提示 ─────────────────────

def test_captureFillsSubjectHint(store):
    key = store.upsertSubject("a1", "客户流失率", aliases=["跑量"], tenantId="t1")
    store.captureAliasCandidate("a1", "跑量怎么算", tenantId="t1")
    row = store.listAliasCandidates(tenantId="t1", status="pending")[0]
    assert row["proposed_subject_key"] == key


def test_captureWithoutSubjectHintLeavesItNull(store):
    store.captureAliasCandidate("a1", "没人认领的词", tenantId="t1")
    row = store.listAliasCandidates(tenantId="t1", status="pending")[0]
    assert row["proposed_subject_key"] is None


# ── §3.4 判据 4：approve → 别名生效 → 归一缓存失效 → 同查询命中（闭环）──

def test_approveAttachesAlias_andNormalizationClosesLoop(store, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "on")
    key = store.upsertSubject("a1", "客户流失率", tenantId="t1")
    candidateId = store.captureAliasCandidate("a1", "跑量", tenantId="t1")

    # 查询词尚无任何主体认领 → 无提示，审批人显式指定 subject_key（提示路径
    # 由 test_captureFillsSubjectHint 与端点用例覆盖）。
    result = store.decideAliasCandidate(
        candidateId, "approved", operator="admin9",
        reason="审批通过", subjectKey=key, tenantId="t1",
    )
    assert result["subject_key"] == key
    assert "跑量" in store.subjectFor(key)["aliases"]

    invalidateQueryNormalizationCache()
    norm = normalizeQueryForRetrieval(store, "跑量怎么算", "a1", "t1")
    assert norm.matchedSubjects[0].subjectKey == key, "审批后归一必须立刻吃到新别名"

    closed = store.listAliasCandidates(tenantId="t1", status="approved")
    assert closed[0]["decided_by"] == "admin9"
    assert closed[0]["decide_reason"] == "审批通过"
    assert result["activity_id"], "审批必须留活动痕"


# ── §3.4 判据 5：reject 不动主体，activity 之外零副作用 ──────────────────

def test_rejectDoesNotTouchSubject(store):
    key = store.upsertSubject("a1", "客户流失率", tenantId="t1")
    candidateId = store.captureAliasCandidate("a1", "跑量", tenantId="t1")
    store.decideAliasCandidate(
        candidateId, "rejected", operator="admin9", reason="不是别名", tenantId="t1"
    )
    assert store.subjectFor(key)["aliases"] == []
    assert store.listAliasCandidates(tenantId="t1", status="rejected")[0][
        "decide_reason"
    ] == "不是别名"


# ── 判据配套：重复处置 / 未知候选 / 无主体可挂 → 显式错误 ────────────────

def test_decideTwiceRaises(store):
    candidateId = store.captureAliasCandidate("a1", "词", tenantId="t1")
    store.decideAliasCandidate(candidateId, "rejected", operator="a", tenantId="t1")
    with pytest.raises(ValueError):
        store.decideAliasCandidate(candidateId, "approved", subjectKey="subj_x", tenantId="t1")


def test_decideUnknownCandidateRaisesLookup(store):
    with pytest.raises(LookupError):
        store.decideAliasCandidate("kbac_nope", "approved", subjectKey="s", tenantId="t1")


def test_approveWithoutSubjectOrHintRaises(store):
    candidateId = store.captureAliasCandidate("a1", "没人认领的词", tenantId="t1")
    with pytest.raises(ValueError):
        store.decideAliasCandidate(candidateId, "approved", operator="a", tenantId="t1")


def test_approveUnknownSubjectRaisesLookup(store):
    candidateId = store.captureAliasCandidate("a1", "词", tenantId="t1")
    with pytest.raises(LookupError):
        store.decideAliasCandidate(
            candidateId, "approved", subjectKey="subj_missing", tenantId="t1"
        )


def test_approveMergedSubjectRaises(store):
    oldKey = store.upsertSubject("a1", "老名", tenantId="t1")
    newKey = store.upsertSubject("a1", "新名", tenantId="t1")
    store.mergeSubjects(oldKey, newKey, reason="合并")
    candidateId = store.captureAliasCandidate("a1", "词", tenantId="t1")
    with pytest.raises(ValueError):
        store.decideAliasCandidate(candidateId, "approved", subjectKey=oldKey, tenantId="t1")


# ── §3.4 判据 6：跨租户互不可见、互不合并 ────────────────────────────────

def test_tenantIsolation(store):
    store.captureAliasCandidate("a1", "同词", tenantId="t1")
    assert store.listAliasCandidates(tenantId="t2") == []
    store.captureAliasCandidate("a1", "同词", tenantId="t2")
    assert len(store.listAliasCandidates(tenantId="t1", status="pending")) == 1
    assert len(store.listAliasCandidates(tenantId="t2", status="pending")) == 1
    with pytest.raises(LookupError):
        store.decideAliasCandidate(
            store.listAliasCandidates(tenantId="t1", status="pending")[0]["candidate_id"],
            "approved", subjectKey="s", tenantId="t2",
        ), "跨租户按不存在处理"


# ── 判据配套：结行后同查询再脱靶新起 pending 行 ──────────────────────────

def test_decidedThenMissAgainOpensNewPendingRow(store):
    candidateId = store.captureAliasCandidate("a1", "词", tenantId="t1")
    store.decideAliasCandidate(candidateId, "rejected", operator="a", tenantId="t1")
    newId = store.captureAliasCandidate("a1", "词", tenantId="t1")
    assert newId and newId != candidateId
    statuses = sorted(
        row["status"] for row in store.listAliasCandidates(tenantId="t1")
    )
    assert statuses == ["pending", "rejected"]


# ── §3.4 判据 2/3：adapter 捕获受开关/平凡过滤/归一命中三道闸 ────────────

@pytest.mark.asyncio
async def test_adapterCapturesMissOnlyWhenEnabled(store, monkeypatch):
    monkeypatch.setattr(
        "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "neurova.knowledge.hybrid.hybrid_search_knowledge", lambda *args, **kwargs: []
    )
    adapter = KnowledgeRetrieverAdapter(repo=Mock())
    context = RetrievalContext(
        query="冷门黑话查询", limit=2, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    )

    monkeypatch.delenv("NEUROVA_KB_MISS_CAPTURE", raising=False)
    await adapter.retrieve(context)
    assert store.listAliasCandidates(tenantId="t1") == [], "开关默认关，不许落行"

    monkeypatch.setenv("NEUROVA_KB_MISS_CAPTURE", "on")
    await adapter.retrieve(context)
    await adapter.retrieve(context)
    rows = store.listAliasCandidates(tenantId="t1", status="pending")
    assert len(rows) == 1 and rows[0]["occurrences"] == 2


@pytest.mark.asyncio
async def test_adapterSkipsTrivialAndNormalizedMisses(store, monkeypatch):
    monkeypatch.setattr(
        "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "neurova.knowledge.hybrid.hybrid_search_knowledge", lambda *args, **kwargs: []
    )
    monkeypatch.setenv("NEUROVA_KB_MISS_CAPTURE", "on")
    adapter = KnowledgeRetrieverAdapter(repo=Mock())

    await adapter.retrieve(RetrievalContext(
        query="好", limit=2, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    ))
    await adapter.retrieve(RetrievalContext(
        query="!!!", limit=2, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    ))
    assert store.listAliasCandidates(tenantId="t1") == [], "平凡查询不落行"

    store.upsertSubject("a1", "客户流失率", aliases=["跑量"], tenantId="t1")
    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "shadow")
    invalidateQueryNormalizationCache()
    await adapter.retrieve(RetrievalContext(
        query="跑量", limit=2, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    ))
    assert store.listAliasCandidates(tenantId="t1") == [], (
        "归一已命中主体的查询不算脱靶（§3.4 判据 3）"
    )

    monkeypatch.setenv("NEUROVA_KB_QUERY_NORMALIZE", "off")
    await adapter.retrieve(RetrievalContext(
        query="跑量", limit=2, user_id="u1",
        metadata={"agent_id": "a1", "tenant_id": "t1"},
    ))
    assert len(store.listAliasCandidates(tenantId="t1", status="pending")) == 1
