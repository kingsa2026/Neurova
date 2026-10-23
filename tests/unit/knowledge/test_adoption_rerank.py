"""采纳反馈进入检索重排：轻量先验、候选扩窗、只对最终注入计数。"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
from neurova.agent.memory_retrieval_chain import RetrievalContext
from neurova.knowledge.feedback_prior import adoptionWeight, rerankByAdoption


class FakeFactStore:
    def __init__(self, facts):
        self.facts = facts

    def narrativeFactForEntry(self, knowledge_id):
        return self.facts.get(knowledge_id)


def _fact(fact_id, outcome):
    return {
        "fact_id": fact_id,
        "latest_adoption_outcome": outcome,
        "evidence_state": "supported",
        "confidence": 0.9,
        "recorded_at": "2026-10-23",
    }


def test_weights_and_neutral_document():
    assert adoptionWeight("success") == 1.10
    assert adoptionWeight("failure") == 0.60
    assert adoptionWeight("unevidenced") == 1.0
    assert adoptionWeight(None) == 1.0
    rows = rerankByAdoption([
        {"id": "ok", "score": 0.80, "adoption_outcome": "success"},
        {"id": "bad", "score": 0.90, "adoption_outcome": "failure"},
        {"id": "doc", "score": 0.85},
    ])
    assert [row["id"] for row in rows] == ["ok", "doc", "bad"]
    assert rows[0]["base_score"] == 0.80
    assert rows[0]["adoption_prior"] == 1.10


@pytest.mark.asyncio
async def test_adapter_reranks_before_truncation_and_keeps_selected_lineage(monkeypatch):
    items = [
        {"knowledge_id": "k1", "title": "ok", "content": "c1", "score": 0.90},
        {"knowledge_id": "k2", "title": "bad", "content": "c2", "score": 0.85},
        {"knowledge_id": "k3", "title": "doc", "content": "c3", "score": 0.80},
        {"knowledge_id": "k4", "title": "ok2", "content": "c4", "score": 0.79},
    ]
    store = FakeFactStore({
        "k1": _fact("f1", "success"),
        "k2": _fact("f2", "failure"),
        "k4": _fact("f4", "success"),
    })
    calls = {}
    monkeypatch.setattr(
        "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
        lambda: store,
    )

    def fakeHybrid(*args, **kwargs):
        calls.update(kwargs)
        return [dict(item) for item in items]

    monkeypatch.setattr("neurova.knowledge.hybrid.hybrid_search_knowledge", fakeHybrid)

    adapter = KnowledgeRetrieverAdapter(repo=Mock())
    result = await adapter.retrieve(RetrievalContext(query="q", limit=2, user_id="u1"))

    assert calls["limit"] == 6, "候选窗必须按最终 top-k 扩窗，给降权项留替补"
    assert [m["knowledge_id"] for m in result.memories] == ["k1", "k4"]
    assert result.memories[0]["adoption_outcome"] == "success"
    assert result.memories[0]["adoption_prior"] == 1.10
    assert result.memories[0]["base_score"] == 0.90
    assert result.metadata["lineage_ids"] == ["f1", "f4"], (
        "只把最终注入的命中写进 lineage；被重排挤掉的 f2 不得进入反馈/归因"
    )


@pytest.mark.asyncio
async def test_document_entry_adoption_reranks_and_records_injection(monkeypatch):
    class DocRepo:
        def __init__(self):
            self.injected = []

        def entryFeedbackMap(self, ids):
            return {
                "d1": {"adoption_outcome": "success", "injected_count": 0},
                "d2": {"adoption_outcome": "failure", "injected_count": 0},
            }

        def recordEntryInjections(self, agent_id, ids):
            self.injected.append((agent_id, list(ids)))
            return len(ids)

    repo = DocRepo()
    items = [
        {"knowledge_id": "d1", "title": "ok", "content": "c1", "score": 0.80},
        {"knowledge_id": "d2", "title": "bad", "content": "c2", "score": 0.90},
    ]
    monkeypatch.setattr(
        "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
        lambda: FakeFactStore({}),
    )
    monkeypatch.setattr(
        "neurova.knowledge.hybrid.hybrid_search_knowledge",
        lambda *args, **kwargs: [dict(item) for item in items],
    )

    adapter = KnowledgeRetrieverAdapter(repo=repo)
    result = await adapter.retrieve(
        RetrievalContext(query="q", limit=1, user_id="u1", metadata={"agent_id": "a1"})
    )

    assert [m["knowledge_id"] for m in result.memories] == ["d1"]
    assert result.memories[0]["adoption_outcome"] == "success"
    assert result.metadata["knowledge_entry_ids"] == ["d1"]
    assert repo.injected == [("a1", ["d1"])]


@pytest.mark.asyncio
async def test_injection_count_uses_final_selection_only(monkeypatch):
    items = [
        {"knowledge_id": "k1", "title": "ok", "content": "c1", "score": 0.90},
        {"knowledge_id": "k2", "title": "bad", "content": "c2", "score": 0.85},
        {"knowledge_id": "k4", "title": "ok2", "content": "c4", "score": 0.79},
    ]
    store = FakeFactStore({
        "k1": _fact("f1", "success"),
        "k2": _fact("f2", "failure"),
        "k4": _fact("f4", "success"),
    })
    captured = []
    monkeypatch.setattr(
        "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "neurova.knowledge.foundation.read_surface.recordHitsAsInjection",
        lambda fact_store, hits: captured.append([h["knowledge_id"] for h in hits]),
    )
    monkeypatch.setattr(
        "neurova.knowledge.hybrid.hybrid_search_knowledge",
        lambda *args, **kwargs: [dict(item) for item in items],
    )

    adapter = KnowledgeRetrieverAdapter(repo=Mock())
    adapter._surface = lambda: object()
    await adapter.retrieve(RetrievalContext(query="q", limit=2, user_id="u1"))

    assert captured == [["k1", "k4"]], "注入计数只能数最终注入的条目，不能数候选窗"
