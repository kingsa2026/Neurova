# -*- coding: utf-8 -*-
"""W4 同名多口径主动澄清（specs/2026-10-30 §5.3 判据）。

三档开关：off 零开销且 metadata 键集合不变；shadow 只落载荷不改注入；
on 在注入块首加受控指引且引用句柄不变。触发器只消费既有账（主体别名表、
冲突账），caliber_hint 只取证据字段。
"""
from __future__ import annotations

import asyncio
import os

import pytest

from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
from neurova.agent.memory_retrieval_chain import RetrievalContext
from neurova.knowledge.ambiguity_clarification import (
    ambiguityMode,
    buildAmbiguityBlock,
    renderAmbiguityGuidance,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.query_normalization import invalidateQueryNormalizationCache

AGENT = "ambigAgent"
TENANT = "default"


@pytest.fixture(autouse=True)
def _freshCache():
    invalidateQueryNormalizationCache()
    yield
    invalidateQueryNormalizationCache()


@pytest.fixture()
def store(tmp_path):
    factStore = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield factStore
    factStore.close()


class FakeRepo:
    """最小仓库：命中的条目由测试直接给出（歧义载荷不依赖排序）。"""

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


def _seedTwoSubjectsSharingAlias(store):
    north = store.upsertSubject(AGENT, "华北回款率")
    south = store.upsertSubject(AGENT, "华南回款率")
    store.attachAlias(AGENT, north, "回款率", operator="tester", reason="同名多口径")
    store.attachAlias(AGENT, south, "回款率", operator="tester", reason="同名多口径")
    store.upsertFact(
        AGENT, north, "rate_of", "92%", "华北回款率 92%", qualifier={"统计口径": "旺季"}
    )
    store.upsertFact(AGENT, south, "rate_of", "78%", "华南回款率 78%")
    invalidateQueryNormalizationCache()
    return north, south


def test_multiSubject_twoSurvivorsShareOneTerm(store, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_AMBIGUITY_CLARIFY", "shadow")
    north, south = _seedTwoSubjectsSharingAlias(store)

    block = buildAmbiguityBlock(store, "回款率 现在是多少", [], AGENT, TENANT)

    assert block is not None, "两个主体共用一个别名必须触发 multi_subject"
    payload = block.toMetadata()
    assert payload["source"] == "multi_subject"
    assert payload["term"] == "回款率"
    assert {c["subject_key"] for c in payload["candidates"]} == {north, south}
    hints = {c["subject_key"]: c["caliber_hint"] for c in payload["candidates"]}
    assert hints[north] == ["旺季"], "caliber_hint 只取 qualifier 证据值，不加工"
    assert hints[south] == [], "无 qualifier 也无命中条目时显式给空，不猜"


def test_openConflict_pendingRowProducesPayload(store, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_AMBIGUITY_CLARIFY", "shadow")
    subject = store.upsertSubject(AGENT, "年度预算")
    store.attachAlias(AGENT, subject, "预算", operator="tester", reason="口径入口")
    marketing = store.upsertFact(
        AGENT, subject, "amount", "100万", "市场预算 100 万", qualifier={"部门": "市场"}
    )
    rd = store.upsertFact(
        AGENT, subject, "amount", "80万", "研发预算 80 万", qualifier={"部门": "研发"}
    )
    store.insertConflict(
        "value_contradiction", subject, "amount", [marketing, rd],
        0.8, "manual", "同谓词数值不同", tenantId=TENANT,
    )
    invalidateQueryNormalizationCache()

    block = buildAmbiguityBlock(store, "预算 今年多少", [], AGENT, TENANT)

    assert block is not None, "命中主体有未决冲突必须触发 open_conflict"
    payload = block.toMetadata()
    assert payload["source"] == "open_conflict"
    assert len(payload["candidates"]) == 2
    assert {tuple(c["caliber_hint"]) for c in payload["candidates"]} == {("市场",), ("研发",)}


def test_singleSubjectWithoutConflict_noPayload(store, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_AMBIGUITY_CLARIFY", "shadow")
    subject = store.upsertSubject(AGENT, "阿尔法指标")
    store.upsertFact(AGENT, subject, "defines", "常规说明", "阿尔法指标的常规说明")
    invalidateQueryNormalizationCache()

    assert buildAmbiguityBlock(store, "阿尔法指标是什么", [], AGENT, TENANT) is None


def test_offMode_skipsEvenWhenAmbiguous(store, monkeypatch):
    monkeypatch.setenv("NEUROVA_KB_AMBIGUITY_CLARIFY", "off")
    _seedTwoSubjectsSharingAlias(store)

    assert ambiguityMode() == "off"
    assert buildAmbiguityBlock(store, "回款率 现在是多少", [], AGENT, TENANT) is None
    monkeypatch.setenv("NEUROVA_KB_AMBIGUITY_CLARIFY", "not-a-mode")
    assert ambiguityMode() == "off", "非法取值按 off 处置，不许猜档"


def _adapterRun(store, monkeypatch, repo, mode):
    monkeypatch.setenv("NEUROVA_KB_AMBIGUITY_CLARIFY", mode)
    monkeypatch.setenv("NEUROVA_KB_MAIN_RERANK", "off")
    from neurova.knowledge.foundation import knowledge_facts as factsModule

    monkeypatch.setattr(factsModule, "get_knowledge_fact_store", lambda: store)
    adapter = KnowledgeRetrieverAdapter(repo, user={"user_id": "u1"})
    return asyncio.run(adapter.retrieve(RetrievalContext(
        query="回款率 现在是多少",
        limit=3,
        user_id="u1",
        metadata={"agent_id": AGENT, "tenant_id": TENANT},
    )))


def test_offMode_metadataKeySetUnchanged(store, monkeypatch):
    _seedTwoSubjectsSharingAlias(store)
    repo = FakeRepo([
        {"knowledge_id": "k1", "title": "华北回款率", "content": "回款率 旺季 92%"},
    ])

    off1 = _adapterRun(store, monkeypatch, repo, "off")
    off2 = _adapterRun(store, monkeypatch, repo, "off")

    assert "ambiguity" not in (off1.metadata or {})
    assert [(m.get("memory_id"), m.get("content")) for m in off1.memories] == \
        [(m.get("memory_id"), m.get("content")) for m in off2.memories], "off 两跑逐字一致"


def test_shadowMode_writesPayload_memoriesUnchanged(store, monkeypatch):
    _seedTwoSubjectsSharingAlias(store)
    repo = FakeRepo([
        {"knowledge_id": "k1", "title": "华北回款率", "content": "回款率 旺季 92%"},
    ])

    off = _adapterRun(store, monkeypatch, repo, "off")
    shadow = _adapterRun(store, monkeypatch, repo, "shadow")

    assert "ambiguity" in (shadow.metadata or {}), "shadow 必须把载荷写进 metadata"
    assert (shadow.metadata or {})["ambiguity"]["source"] == "multi_subject"
    assert [(m.get("memory_id"), m.get("content")) for m in shadow.memories] == \
        [(m.get("memory_id"), m.get("content")) for m in off.memories], "shadow 不得改注入内容"


def test_renderGuidance_namesCountAndTerm():
    block = {
        "source": "multi_subject",
        "term": "回款率",
        "candidates": [
            {"subject_key": "s1", "canonical_label": "华北回款率"},
            {"subject_key": "s2", "canonical_label": "华南回款率"},
        ],
    }
    guidance = renderAmbiguityGuidance(block)

    assert guidance.startswith("[检索歧义]「回款率」在知识库中有 2 个口径：")
    assert "不得静默择一" in guidance
    assert "华北回款率" in guidance and "华南回款率" in guidance


def test_guidance_gated_byOnMode(monkeypatch):
    """shadow 不碰提示词；on 才把载荷翻成指引。"""
    from types import SimpleNamespace

    from neurova.agent.chat_pipeline import ChatContext, ChatPipeline

    pipeline = object.__new__(ChatPipeline)
    pipeline._agent = SimpleNamespace(config=SimpleNamespace(agent_id=AGENT))
    ctx = ChatContext(user_input="回款率 现在是多少")
    ctx.metadata = {"knowledge_ambiguity": _payload()}

    monkeypatch.setenv("NEUROVA_KB_AMBIGUITY_CLARIFY", "off")
    assert pipeline._ambiguityGuidance(ctx) is None
    monkeypatch.setenv("NEUROVA_KB_AMBIGUITY_CLARIFY", "shadow")
    assert pipeline._ambiguityGuidance(ctx) is None, "shadow 档不得改注入内容"
    monkeypatch.setenv("NEUROVA_KB_AMBIGUITY_CLARIFY", "on")
    guidance = pipeline._ambiguityGuidance(ctx)
    assert guidance and "回款率" in guidance and "不得静默择一" in guidance


def _payload():
    return {
        "source": "multi_subject",
        "term": "回款率",
        "candidates": [
            {"subject_key": "s1", "canonical_label": "华北回款率", "caliber_hint": [], "entry_ids": []},
            {"subject_key": "s2", "canonical_label": "华南回款率", "caliber_hint": [], "entry_ids": []},
        ],
    }


@pytest.mark.asyncio
async def test_poolBranch_guidanceAtBlockHead_citationHandlesUnchanged():
    """on 档指引落在注入块首（信封内，不进 system 行），引用句柄 m1 不受影响。"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from neurova.context.orchestrator import ContextOrchestrator
    from neurova.memory.citation import CitationRegistry

    mockAgent = MagicMock()
    mockAgent.config = MagicMock()
    mockAgent.config.name = "test_agent"
    mockAgent.config.constitution = ""
    mockAgent.config.behavior_rules = []
    mockAgent.soul = "你是助手"
    mockAgent.personality = ""
    mockAgent.conversation_history = []
    mockAgent.context_builder = MagicMock()
    mockAgent.agent_id = AGENT

    orchestrator = ContextOrchestrator(mockAgent, use_pool=True, auto_tag=True)
    registry = CitationRegistry()
    registry.register({"memory_id": "mem-1", "content": "旧偏好"})
    memories = [{"memory_id": "mem-1", "content": "旧偏好"}]

    async def _run(guidance):
        with patch.object(orchestrator, "get_tools_description", new_callable=AsyncMock) as _tools:
            _tools.return_value = ""
            return await orchestrator.build_context(
                user_input="回款率 现在是多少",
                relevant_memories=memories,
                citation_registry=registry,
                retrieval_guidance=guidance,
            )

    baseline = await _run(None)
    withGuidance = await _run(renderAmbiguityGuidance(_payload()))

    lastBaseline = baseline[-1]["content"]
    lastWith = withGuidance[-1]["content"]
    assert "m1" in lastBaseline and "m1" in lastWith, "引用句柄不因指引改变"
    assert "检索歧义" not in lastBaseline
    assert "检索歧义" in lastWith, "on 档指引必须进注入信封"
    assert lastWith.index("检索歧义") < lastWith.index("[记忆]"), "指引必须在注入块首"
    assert all("检索歧义" not in msg["content"] for msg in withGuidance if msg["role"] == "system"), (
        "动态检索文本不得进 system 行（D4 甲案）"
    )
