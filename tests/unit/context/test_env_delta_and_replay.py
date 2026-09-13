# -*- coding: utf-8 -*-
"""P2-4 环境增量 + P2-6 reasoning 回放闸门 + P2-2 记忆租约/citation。"""
import pytest

from neurova.context.env_delta import (
    EnvDeltaTracker,
    compute_env_fingerprint,
    get_env_delta_tracker,
    reset_env_delta_tracker,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_env_delta_tracker()
    yield
    reset_env_delta_tracker()


class TestEnvDelta:
    def test_first_turn_no_note(self):
        t = EnvDeltaTracker()
        fp = compute_env_fingerprint("/ws", "m1")
        assert t.note("s1", fp) is None  # 首轮全量，无增量

    def test_unchanged_no_note(self):
        t = EnvDeltaTracker()
        fp = compute_env_fingerprint("/ws", "m1")
        t.note("s1", fp)
        assert t.note("s1", compute_env_fingerprint("/ws", "m1")) is None

    def test_changed_produces_delta(self):
        t = EnvDeltaTracker()
        t.note("s1", compute_env_fingerprint("/ws", "m1"))
        note = t.note("s1", compute_env_fingerprint("/ws2", "m1"))
        assert note and "环境已变化" in note and "/ws" in note and "/ws2" in note

    def test_sessions_isolated(self):
        t = EnvDeltaTracker()
        t.note("s1", compute_env_fingerprint("/a", "m"))
        assert t.note("s2", compute_env_fingerprint("/a", "m")) is None

    def test_tracker_singleton_roundtrip(self):
        tr = get_env_delta_tracker()
        assert get_env_delta_tracker() is tr


class TestReasoningReplayGate:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_REASONING_REPLAY", raising=False)
        from neurova.agent.loops.reasoning_replay import should_replay_reasoning

        assert should_replay_reasoning("gpt-5") is False

    def test_env_on_requires_capability(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_REASONING_REPLAY", "1")
        from neurova.agent.loops.reasoning_replay import (
            build_reasoning_assistant_message,
            should_replay_reasoning,
        )

        # 无 REASONING 能力标记的模型不回放（能力门）
        assert should_replay_reasoning("not-a-real-model-xyz") is False

        # 消息构造契约（与闸门独立）
        msg = build_reasoning_assistant_message(
            "思考...", "回答",
            [type("TC", (), {"id": "c1", "function": type("F", (), {"name": "t", "arguments": "{}"})()})()],
        )
        assert msg["role"] == "assistant"
        assert msg["reasoning_content"] == "思考..."
        assert msg["tool_calls"][0]["function"]["name"] == "t"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
