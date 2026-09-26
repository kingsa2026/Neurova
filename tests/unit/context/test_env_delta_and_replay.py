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
        from neurova.agent.loops.reasoning_replay import should_replay_reasoning

        # 无 REASONING 能力标记的模型不回放（能力门）
        assert should_replay_reasoning("not-a-real-model-xyz") is False

    def test_replay_message_has_single_constructor(self):
        """回放消息只在 BaseAgentLoop.buildToolRoundMessages 一处构造。

        reasoning_replay 曾自带一份 assistant 构造器，两侧对 tool_calls 的
        id 解析不同源（getattr 读 dict 恒取默认值→合成 call_0/call_1），
        与 tool 结果的 tool_call_id 配不上。平行定义已收口，此处钉住不回退。
        """
        import inspect

        from neurova.agent.loops import reasoning_replay

        assert not hasattr(reasoning_replay, "build_reasoning_assistant_message")
        source = inspect.getsource(reasoning_replay)
        assert '"tool_calls"' not in source, "回放模块不得再自行声明 tool_calls"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
