"""聊天反馈 → 知识事实采纳的自动血缘链。

只在服务端检索出的 lineage_ids 上写回；不接受客户端自报 fact_id。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.agent.chat_pipeline import ChatPipeline
from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.read_surface import attachGovernance


@pytest.fixture()
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    yield s
    s.close()


def _fact(store, kid, content="statement"):
    return store.upsertFact(
        "default", "subject-" + kid, "predicate", kid, content,
        recordKind="narrative", sourceTurnId="entry:%s" % kid,
    )


def test_attachGovernance_lineage_without_enrichment(store):
    fid = _fact(store, "kid-1")

    hits, lineage = attachGovernance(
        store, [{"knowledge_id": "kid-1", "confidence": 0.91}], enrich=False
    )

    assert lineage == [fid]
    assert hits[0]["lineage_id"] == fid
    assert hits[0]["confidence"] == 0.91, "enrich=False 不得用派生置信覆盖条目原值"
    assert "evidence_state" not in hits[0]


def test_adapter_normalize_item_carries_lineage_and_fact_id():
    item = KnowledgeRetrieverAdapter._normalize_item({
        "knowledge_id": "kid-1", "lineage_id": "fact-1",
        "title": "t", "content": "c", "source": "manual",
    })
    assert item["lineage_id"] == "fact-1"
    assert item["fact_id"] == "fact-1"


def test_chat_pipeline_extracts_structured_knowledge_citations():
    from neurova.memory.citation import CitationRegistry

    registry = CitationRegistry()
    handle = registry.register({"fact_id": "fact-1", "knowledge_id": "kid-1"})
    ctx = SimpleNamespace(
        metadata={}, reply='<memory_citation ref="%s"/>' % handle,
        citation_registry=registry,
    )

    ChatPipeline._recordKnowledgeCitations(ctx)

    assert ctx.metadata["knowledge_citation_ids"] == ["fact-1"]


def test_retrieval_chain_merges_lineage_from_supplement():
    """主记忆源命中时知识作为补充源；补充源的 lineage 不能被合并丢掉。"""
    import asyncio

    from neurova.agent.memory_retrieval_chain import (
        MemoryRetrievalChain,
        RetrievalContext,
        RetrievalQuality,
        RetrievalResult,
    )

    class FakeRetriever:
        def __init__(self, name, memory_id, lineage):
            self.name = name
            self.priority = 10 if name != "KnowledgeRetriever" else 25
            self._memory_id = memory_id
            self._lineage = lineage

        async def retrieve(self, context):
            return RetrievalResult(
                memories=[{"memory_id": self._memory_id, "content": "c"}],
                source=self.name,
                quality=0.9 if self.name != "KnowledgeRetriever" else 0.8,
                quality_level=RetrievalQuality.GOOD,
                retrieval_time=0.0,
                metadata={"lineage_ids": self._lineage},
            )

        def get_quality_score(self, results, query):
            return 0.9

    chain = MemoryRetrievalChain()
    chain.add_retriever(FakeRetriever("Unified", "m1", ["f-primary"]))
    chain.add_retriever(FakeRetriever("KnowledgeRetriever", "k1", ["f-knowledge"]))

    result = asyncio.run(chain._retrieve_chain(RetrievalContext(query="q", limit=5)))

    assert result.metadata["lineage_ids"] == ["f-primary", "f-knowledge"]


def test_chat_pipeline_records_deduped_lineage():
    ctx = SimpleNamespace(metadata={})
    result = SimpleNamespace(metadata={"lineage_ids": ["f1", "f1", "f2", ""]})

    ChatPipeline._recordKnowledgeLineage(ctx, result)

    assert ctx.metadata["knowledge_lineage_ids"] == ["f1", "f2"]


def test_post_chat_persists_lineage_in_assistant_metadata():
    from neurova.post_chat_pipeline import PostChatPipeline
    import asyncio

    agent = MagicMock()
    agent._save_to_session = MagicMock(return_value="sess-1")
    agent._collect_tool_messages = MagicMock(return_value=[])
    pipeline = PostChatPipeline(agent)

    asyncio.run(pipeline._step_save_session(
        user_input="q", reply="a", session_id="sess-1", save_memory=True,
        metadata={
            "knowledge_lineage_ids": ["f1", "f2"],
            "knowledge_citation_ids": ["f1"],
        },
    ))

    args, kwargs = agent._save_to_session.call_args
    assistant_meta = args[4] if len(args) > 4 else kwargs.get("assistant_metadata")
    assert assistant_meta["knowledge_lineage_ids"] == ["f1", "f2"]
    assert assistant_meta["knowledge_citation_ids"] == ["f1"]


def test_record_token_usage_even_split_and_idempotent(store):
    f1 = _fact(store, "t1")
    f2 = _fact(store, "t2")

    assert store.recordTokenUsage([f1, f2], 10, 5, sourceTurnId="turn-1") == 2
    metrics = store.tokenUsageMetrics()
    assert metrics["events"] == 2
    assert metrics["turns"] == 1
    assert metrics["attributed_total_tokens"] == 15
    assert metrics["attribution"] == "even_split"
    per_fact = {r["fact_id"]: r["total_tokens"] for r in metrics["by_fact"]}
    assert sorted(per_fact.values()) == [7, 8]

    assert store.recordTokenUsage([f1, f2], 10, 5, sourceTurnId="turn-1") == 0
    assert store.tokenUsageMetrics()["events"] == 2


def test_post_chat_records_retrieval_phase_and_citation_attribution(store, monkeypatch):
    import asyncio

    from neurova.post_chat_pipeline import PostChatPipeline

    f1 = _fact(store, "t6")
    f2 = _fact(store, "t7")
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store
    )
    monkeypatch.setattr(
        "neurova.core.usage_accounting.get_usage_accounting",
        lambda: SimpleNamespace(last_call=lambda: {
            "prompt_tokens": 10, "completion_tokens": 5, "model": "stub",
        }),
    )
    agent = MagicMock()
    agent._save_to_session = MagicMock(return_value="sess-1")
    agent._collect_tool_messages = MagicMock(return_value=[])
    pipeline = PostChatPipeline(agent)

    asyncio.run(pipeline._step_save_session(
        user_input="q", reply="a", session_id="sess-1", save_memory=True,
        metadata={
            "knowledge_lineage_ids": [f1, f2],
            "knowledge_citation_ids": [f1],
            "knowledge_retrieval_tokens": {f1: 7, f2: 5},
            "knowledge_retrieval_tokens_model": "retrieval-model",
        },
    ))

    metrics = store.tokenUsageMetrics()
    retrieval_models = {
        r["model"] for r in store._conn.execute(
            "SELECT model FROM knowledge_fact_usage WHERE phase = 'retrieval'"
        ).fetchall()
    }
    assert retrieval_models == {"retrieval-model"}, (
        "检索阶段必须记实际用于分词/检索的模型，不能借用生成阶段模型"
    )
    generation = [r for r in metrics["by_fact"] if r["fact_id"] == f2]
    assert generation and generation[0]["total_tokens"] == 5, "未被引用的 f2 只应计检索侧 5"
    phases = {r["phase"]: r["total_tokens"] for r in metrics["by_phase"]}
    assert phases["generation"] == 15
    assert phases["retrieval"] == 12
    assert metrics["turn_totals"]["unattributed_tokens"] == 0
    assert metrics["turn_totals"]["retrieval_unattributed_tokens"] == 0


def test_retrieval_unattributed_tokens_do_not_land_on_a_fact(store, monkeypatch):
    """文档命中的检索 token 进未归因桶；不能摊到任何 fact 头上。"""
    import asyncio

    from neurova.post_chat_pipeline import PostChatPipeline

    fact_id = _fact(store, "t8")
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store
    )
    monkeypatch.setattr(
        "neurova.core.usage_accounting.get_usage_accounting",
        lambda: SimpleNamespace(last_call=lambda: {}),
    )
    agent = MagicMock()
    agent._save_to_session = MagicMock(return_value="sess-1")
    agent._collect_tool_messages = MagicMock(return_value=[])
    pipeline = PostChatPipeline(agent)

    asyncio.run(pipeline._step_save_session(
        user_input="q", reply="a", session_id="sess-1", save_memory=True,
        metadata={
            "knowledge_lineage_ids": [fact_id],
            "knowledge_retrieval_tokens": {fact_id: 7},
            "knowledge_retrieval_tokens_total": 20,
            "knowledge_retrieval_tokens_model": "retrieval-model",
        },
    ))

    metrics = store.tokenUsageMetrics()
    assert metrics["by_phase"] == [{"phase": "retrieval", "total_tokens": 7, "events": 1}]
    assert metrics["turn_totals"]["retrieval_unattributed_tokens"] == 13
    assert metrics["turn_totals"]["retrieval_unattributed_share"] == round(13 / 20, 6)


def test_post_chat_persists_token_usage(store, monkeypatch):
    import asyncio

    from neurova.post_chat_pipeline import PostChatPipeline

    f1 = _fact(store, "t3")
    f2 = _fact(store, "t4")
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store
    )
    monkeypatch.setattr(
        "neurova.core.usage_accounting.get_usage_accounting",
        lambda: SimpleNamespace(last_call=lambda: {"prompt_tokens": 10, "completion_tokens": 5}),
    )
    agent = MagicMock()
    agent._save_to_session = MagicMock(return_value="sess-1")
    agent._collect_tool_messages = MagicMock(return_value=[])
    pipeline = PostChatPipeline(agent)

    asyncio.run(pipeline._step_save_session(
        user_input="q", reply="a", session_id="sess-1", save_memory=True,
        metadata={"knowledge_lineage_ids": [f1, f2]},
    ))

    metrics = store.tokenUsageMetrics()
    assert metrics["turns"] == 1
    assert metrics["attributed_total_tokens"] == 15


def test_content_filter_finish_counts_model_refusal():
    from neurova.agent.chat_pipeline import _recordFinishOutcome
    from neurova.knowledge.retrieval_metrics import (
        get_retrieval_metrics,
        reset_retrieval_metrics,
    )

    reset_retrieval_metrics()
    _recordFinishOutcome("content_filter")
    _recordFinishOutcome("stop")
    assert get_retrieval_metrics().snapshot()["outcomes"]["model_refusal"] == 1
    reset_retrieval_metrics()


def test_two_turns_same_session_get_two_turn_ids(store, monkeypatch):
    import asyncio

    from neurova.post_chat_pipeline import PostChatPipeline

    f1 = _fact(store, "t5")
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store
    )
    monkeypatch.setattr(
        "neurova.core.usage_accounting.get_usage_accounting",
        lambda: SimpleNamespace(last_call=lambda: {"prompt_tokens": 10, "completion_tokens": 5}),
    )
    agent = MagicMock()
    agent._save_to_session = MagicMock(return_value="sess-1")
    agent._collect_tool_messages = MagicMock(return_value=[])
    pipeline = PostChatPipeline(agent)

    for _ in range(2):
        asyncio.run(pipeline._step_save_session(
            user_input="q", reply="a", session_id="sess-1", save_memory=True,
            metadata={"knowledge_lineage_ids": [f1]},
        ))

    metrics = store.tokenUsageMetrics()
    assert metrics["turns"] == 2, "同一会话两轮必须有两个 turn_id，不能被会话级幂等吞掉"
    assert metrics["events"] == 2


def test_apply_feedback_to_facts_maps_three_states(store, monkeypatch):
    from neurova.api.endpoints import console

    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store
    )
    like = _fact(store, "like")
    dislike = _fact(store, "dislike")
    corrected = _fact(store, "corrected")

    assert console._apply_feedback_to_facts([like], "like", None)["recorded"] == 1
    assert store.fact(like)["adoption_outcome"] == "success"

    assert console._apply_feedback_to_facts([dislike], "dislike", None)["recorded"] == 1
    assert store.fact(dislike)["adoption_outcome"] == "failure"

    assert console._apply_feedback_to_facts([corrected], "like", "修正答案")["recorded"] == 1
    assert store.fact(corrected)["adoption_outcome"] == "failure"

    result = console._apply_feedback_to_facts(["missing"], "like", None)
    assert result["recorded"] == 0 and result["errors"]
