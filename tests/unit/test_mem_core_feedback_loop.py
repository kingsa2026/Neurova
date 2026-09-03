"""红绿灯 TDD：MemCore.apply_feedback_to_memories —— 反馈质量闭环。

原需求："点赞和踩一脚（用户对回复内容是否满意。用于改进agent的回复质量）"。
落库只是收集，本迭代把反馈接入记忆温度系统形成闭环：
- like  → update_memory_temperature（touch，+10 强化，更易被召回）
- dislike → update_memory(temperature=max(0, temp-15)) 抑制，加速遗忘
- feedback=None（取消反馈）→ 无操作
"""
from __future__ import annotations

from neurova.mem_core import MemCore


class FakeMemoryManager:
    """记录温度操作的假记忆管理器。"""

    def __init__(self, memories):
        self.memories = list(memories)
        self.touched = []
        self.temp_updates = []

    def get_all_memories(self):
        return [dict(m) for m in self.memories]

    def forget(self, memory_id, soft=True):
        self.memories = [m for m in self.memories if m["id"] != memory_id]
        return True

    def update_memory_temperature(self, memory_id, interaction_type="recall"):
        self.touched.append((memory_id, interaction_type))
        return True

    def update_memory(self, memory_id, **kwargs):
        self.temp_updates.append((memory_id, kwargs))
        return True


class FakeAgent:
    def __init__(self, memory_manager):
        self.memory_manager = memory_manager


def _mem(mid, content, temp=100.0):
    return {
        "id": mid,
        "content": content,
        "temperature": temp,
        "metadata": {"session_id": "s1", "sender_type": "user" if content.startswith("用户") else "agent"},
        "created_at": "2026-08-29T10:00:00+00:00",
    }


def _round_memories():
    return [
        _mem("m1", "用户: Q1"),
        _mem("m2", "助手: A1"),
    ]


def test_like_reinforces_round_memories():
    mm = FakeMemoryManager(_round_memories())
    core = MemCore(FakeAgent(mm))

    n = core.apply_feedback_to_memories(
        session_id="s1", user_input="Q1", agent_response="A1",
        feedback="like", approx_ts="2026-08-29T10:00:00",
    )

    assert n == 2
    assert {mid for mid, _ in mm.touched} == {"m1", "m2"}
    # touch 的 interaction_type 语义：反馈视为一次"use"
    assert all(it == "use" for _, it in mm.touched)
    assert mm.temp_updates == []


def test_dislike_suppresses_round_memories_with_floor():
    mm = FakeMemoryManager([_mem("m1", "用户: Q1", temp=100.0), _mem("m2", "助手: A1", temp=8.0)])
    core = MemCore(FakeAgent(mm))

    n = core.apply_feedback_to_memories(
        session_id="s1", user_input="Q1", agent_response="A1",
        feedback="dislike", approx_ts="2026-08-29T10:00:00",
    )

    assert n == 2
    assert mm.touched == []
    temps = {mid: kw.get("temperature") for mid, kw in mm.temp_updates}
    assert temps["m1"] == 85.0  # 100 - 15
    assert temps["m2"] == 0.0   # 下限保护：8 - 15 → 0


def test_cancel_feedback_is_noop():
    mm = FakeMemoryManager(_round_memories())
    core = MemCore(FakeAgent(mm))

    assert core.apply_feedback_to_memories("s1", "Q1", "A1", feedback=None) == 0
    assert core.apply_feedback_to_memories("s1", "Q1", "A1", feedback="meh") == 0
    assert mm.touched == [] and mm.temp_updates == []


def test_no_matching_memories_returns_zero():
    mm = FakeMemoryManager(_round_memories())
    core = MemCore(FakeAgent(mm))

    n = core.apply_feedback_to_memories(
        session_id="s1", user_input="不存在的问题", agent_response="不存在的回答", feedback="like",
    )
    assert n == 0


def test_no_memory_manager_returns_zero():
    class AgentWithoutMM:
        memory_manager = None

    core = MemCore(AgentWithoutMM())
    assert core.apply_feedback_to_memories("s1", "Q", "A", "like") == 0
