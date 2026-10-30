# -*- coding: utf-8 -*-
"""W5 生成后事实回查守卫（specs/2026-10-30 §6.3 判据）。

句级确定性回查：数字/日期对事实 object 值与命中证据；contradicted 从保守，
只标记不改写；shadow 消息逐字不变，on 仅追加注记行；无血缘整段跳过。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.guards.answer_fact_guard import (
    guardMode,
    renderGuardNote,
    runAnswerFactGuard,
)

AGENT = "factGuardAgent"


@pytest.fixture()
def store(tmp_path):
    factStore = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield factStore
    factStore.close()


@pytest.fixture()
def seeded(store):
    subject = store.upsertSubject(AGENT, "华北回款率")
    factId = store.upsertFact(AGENT, subject, "rate_of", "78%", "华北回款率 78%")
    hits = [{
        "knowledge_id": "k1",
        "lineage_id": factId,
        "title": "华北回款率",
        "content": "华北回款率 78%",
    }]
    return store, factId, hits


def test_contradicted_whenValueAbsentFromEvidence(seeded, monkeypatch):
    store, _factId, hits = seeded
    monkeypatch.setenv("NEUROVA_KB_ANSWER_FACT_GUARD", "shadow")

    report = runAnswerFactGuard("华北回款率现在达到 92%。", hits, store, AGENT)

    assert report is not None
    assert report.checked == 1
    assert len(report.contradicted) == 1
    assert report.contradicted[0]["claim"] == "92%"
    assert report.contradicted[0]["evidenceStatus"] == "contradicted"


def test_supported_whenValueMatchesEvidence(seeded, monkeypatch):
    store, _factId, hits = seeded
    monkeypatch.setenv("NEUROVA_KB_ANSWER_FACT_GUARD", "shadow")

    report = runAnswerFactGuard("华北回款率是 78%。", hits, store, AGENT)

    assert report is not None
    assert report.checked == 1
    assert report.supported == 1
    assert report.contradicted == []


def test_noLineage_skipsEntirely(seeded, monkeypatch):
    store, _factId, hits = seeded
    monkeypatch.setenv("NEUROVA_KB_ANSWER_FACT_GUARD", "shadow")
    noLineage = [{"knowledge_id": "k1", "title": "华北回款率", "content": "华北回款率 78%"}]

    assert runAnswerFactGuard("华北回款率是 92%。", noLineage, store, AGENT) is None


def test_sentenceWithoutNumbers_notChecked(seeded, monkeypatch):
    store, _factId, hits = seeded
    monkeypatch.setenv("NEUROVA_KB_ANSWER_FACT_GUARD", "shadow")

    report = runAnswerFactGuard("华北回款率的口径需要确认。", hits, store, AGENT)

    assert report is not None
    assert report.checked == 0


def test_factStoreFailure_stepsAside(seeded, monkeypatch):
    store, _factId, hits = seeded
    monkeypatch.setenv("NEUROVA_KB_ANSWER_FACT_GUARD", "shadow")

    def _boom(_ids):
        raise RuntimeError("fact store down")

    monkeypatch.setattr(store, "factsByIds", _boom)

    assert runAnswerFactGuard("华北回款率是 92%。", hits, store, AGENT) is None


def test_offMode_neverRuns(seeded, monkeypatch):
    store, _factId, hits = seeded
    monkeypatch.setenv("NEUROVA_KB_ANSWER_FACT_GUARD", "off")

    assert guardMode() == "off"
    assert runAnswerFactGuard("华北回款率是 92%。", hits, store, AGENT) is None


def _pipeline():
    from neurova.agent.chat_pipeline import ChatPipeline

    pipeline = object.__new__(ChatPipeline)
    pipeline._agent = SimpleNamespace(config=SimpleNamespace(agent_id=AGENT))
    return pipeline


def test_wiring_shadowKeepsMessage_onAppendsOnlyNote(seeded, monkeypatch):
    store, _factId, hits = seeded
    from neurova.agent.chat_pipeline import ChatContext
    from neurova.knowledge.foundation import knowledge_facts as factsModule

    monkeypatch.setattr(factsModule, "get_knowledge_fact_store", lambda: store)
    original = "华北回款率现在达到 92%。"

    monkeypatch.setenv("NEUROVA_KB_ANSWER_FACT_GUARD", "shadow")
    shadowCtx = ChatContext(user_input="回款率多少")
    shadowCtx.reply = original
    shadowCtx.relevant_memories = hits
    shadowCtx.metadata = {"tenant_id": "default"}
    _pipeline()._applyAnswerFactGuard(shadowCtx)
    assert shadowCtx.reply == original, "shadow 消息必须逐字不变"
    assert (shadowCtx.metadata or {}).get("answer_fact_guard", {}).get("contradicted"), (
        "shadow 必须留读数"
    )

    monkeypatch.setenv("NEUROVA_KB_ANSWER_FACT_GUARD", "on")
    onCtx = ChatContext(user_input="回款率多少")
    onCtx.reply = original
    onCtx.relevant_memories = hits
    onCtx.metadata = {"tenant_id": "default"}
    _pipeline()._applyAnswerFactGuard(onCtx)
    assert onCtx.reply.startswith(original), "原句不得改写"
    assert "核验注记" in onCtx.reply and "92%" in onCtx.reply
    assert onCtx.reply == f"{original}\n\n{renderGuardNote(_reportFor(store, hits))}"


def _reportFor(store, hits):
    from neurova.knowledge.guards.answer_fact_guard import runAnswerFactGuard as _run

    return _run("华北回款率现在达到 92%。", hits, store, AGENT)


def test_wiring_guardFailure_leavesMessage(seeded, monkeypatch):
    store, _factId, hits = seeded
    from neurova.agent.chat_pipeline import ChatContext

    def _explode(*_a, **_k):
        raise RuntimeError("store unavailable")

    import neurova.knowledge.guards.answer_fact_guard as guardModule

    monkeypatch.setattr(guardModule, "runAnswerFactGuard", _explode)
    monkeypatch.setenv("NEUROVA_KB_ANSWER_FACT_GUARD", "on")
    ctx = ChatContext(user_input="回款率多少")
    ctx.reply = "华北回款率现在达到 92%。"
    ctx.relevant_memories = hits
    ctx.metadata = {"tenant_id": "default"}

    _pipeline()._applyAnswerFactGuard(ctx)

    assert ctx.reply == "华北回款率现在达到 92%。", "守卫失败不得改消息"
    assert "answer_fact_guard" not in (ctx.metadata or {})
