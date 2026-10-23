"""TurnOutcome 分类与质量事件账。"""
import asyncio
from unittest.mock import MagicMock

from neurova.quality.outcome_store import ConversationQualityStore
from neurova.quality.outcomes import classifyTurnOutcome


def test_classifier_uses_only_hard_signals():
    assert classifyTurnOutcome("content_filter", 9, 0.9) == "safety_refusal"
    assert classifyTurnOutcome("stop", 0, 0.0) == "insufficient_evidence"
    assert classifyTurnOutcome("stop", 2, 0.2) == "answered"
    assert classifyTurnOutcome("length", 2, 0.9) == "unknown"
    assert classifyTurnOutcome(None, None, None) == "unknown"


def test_explicit_outcome_wins_and_is_validated():
    assert classifyTurnOutcome("stop", 2, 0.9, "tool_failure") == "tool_failure"
    assert classifyTurnOutcome("stop", 2, 0.9, "handoff") == "handoff"
    assert classifyTurnOutcome("content_filter", 2, 0.9, "not-a-state") == "safety_refusal"


def test_store_metrics_and_idempotency(tmp_path):
    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    try:
        store.recordTurnOutcome("t1", "s1", outcome="answered")
        store.recordTurnOutcome("t2", "s2", outcome="safety_refusal")
        store.recordTurnOutcome("t3", "s3", outcome="insufficient_evidence")
        store.recordTurnOutcome("t4", "s4", outcome="unknown")
        store.recordEvent(
            "human_takeover_started", "s2",
            source="console_mark", sourceEventId="op-1", actorId="op",
            channel="console",
        )
        duplicate = store.recordEvent(
            "human_takeover_started", "s2",
            source="console_mark", sourceEventId="op-1", actorId="op",
        )

        metrics = store.metrics()

        assert duplicate["duplicate"] is True
        assert metrics["turns"] == 4
        assert metrics["outcomes"]["safety_refusal"] == 1
        assert metrics["safety_refusal_rate"] == round(1 / 3, 6)
        assert metrics["insufficient_evidence_rate"] == round(1 / 3, 6)
        assert metrics["unknown_outcome_rate"] == 0.25
        assert metrics["human_takeover_rate"] == 0.25
        assert metrics["takeover_sources"] == {"console_mark": 1}
    finally:
        store.close()


def test_explicit_turn_outcome_overrides_automatic(tmp_path):
    """显式 outcome 后写不能被自动分类的幂等键吃掉；指标按轮只算一次。"""
    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    try:
        store.recordTurnOutcome("t1", "s1", outcome="answered")
        store.recordTurnOutcome(
            "t1", "s1", outcome="tool_failure", source="explicit_api"
        )
        metrics = store.metrics()
    finally:
        store.close()

    assert metrics["turns"] == 1
    assert metrics["turn_outcome_events"] == 2
    assert metrics["outcomes"] == {"tool_failure": 1}
    assert metrics["tool_failure_rate"] == 1.0


def test_latest_explicit_outcome_wins_for_same_turn(tmp_path):
    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    try:
        store.recordTurnOutcome("t1", "s1", outcome="answered", source="explicit_api")
        store.recordTurnOutcome(
            "t1", "s1", outcome="tool_failure", source="explicit_api"
        )
        metrics = store.metrics()
    finally:
        store.close()

    assert metrics["turns"] == 1
    assert metrics["outcomes"] == {"tool_failure": 1}


def test_tool_record_only_declares_explicit_outcome():
    """success=False 不等于整轮 tool_failure；只有记录显式声明才覆盖。"""
    from neurova.agent.chat_pipeline import ChatPipeline

    class _Context:
        def __init__(self):
            self.metadata = {}

    plain = _Context()
    ChatPipeline._recordExplicitToolOutcome(
        plain, [{"type": "tool_result", "success": False}],
    )
    assert "turn_outcome_override" not in plain.metadata

    declared = _Context()
    ChatPipeline._recordExplicitToolOutcome(
        declared,
        [{"type": "tool_result", "success": False, "turn_outcome": "tool_failure"}],
    )
    assert declared.metadata["turn_outcome_override"] == "tool_failure"


def test_execution_chain_crash_marks_explicit_tool_failure():
    """producer 与 reader 同字段：执行链崩溃记录必须带显式 turn_outcome。"""
    from neurova.agent.loops.base import BaseAgentLoop

    _message, records = BaseAgentLoop._failedToolOutcome(
        None,
        {"id": "call-1", "function": {"name": "probe_tool"}},
        RuntimeError("chain boom"),
    )

    assert records[0]["success"] is False
    assert records[0]["turn_outcome"] == "tool_failure"


def test_empty_store_is_unevidenced(tmp_path):
    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    try:
        metrics = store.metrics()
    finally:
        store.close()
    assert metrics["measure_state"] == "unevidenced"
    assert metrics["safety_refusal_rate"] is None
    assert metrics["human_takeover_rate"] is None


def test_post_chat_records_turn_outcome(tmp_path, monkeypatch):
    from neurova.post_chat_pipeline import PostChatPipeline

    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    monkeypatch.setattr("neurova.quality.get_quality_store", lambda: store)
    agent = MagicMock()
    agent._save_to_session = MagicMock(return_value="sess-1")
    agent._collect_tool_messages = MagicMock(return_value=[])
    pipeline = PostChatPipeline(agent)

    asyncio.run(pipeline._step_save_session(
        user_input="q", reply="a", session_id="sess-1", save_memory=True,
        metadata={"finish_reason": "stop", "retrieval_hits": 2, "retrieval_quality": 0.8},
    ))

    metrics = store.metrics()
    store.close()
    assert metrics["turns"] == 1
    assert metrics["outcomes"]["answered"] == 1
