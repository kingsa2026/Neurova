"""红绿灯 TDD：MemCore.delete_round_memories —— 删除/覆写轮次时清除对应记忆。

记忆落库契约（post_chat_pipeline._step_save_memory）：
    memory_manager.remember(
        content=f"用户: {user_input}" / f"助手: {reply}",
        metadata={"sender_type": "user"/"agent", "session_id": session_id},
    )

匹配规则：session_id + sender_type + 内容精确匹配；同一内容在多轮重复出现时
（如"继续"），按 created_at 与轮次消息时间戳的接近程度取最近一条，只删该轮的，
不误删同内容的历史轮。空内容跳过（孤立尾 user 消息没有 assistant 回复）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from neurova.mem_core import MemCore


class FakeMemoryManager:
    """记录 forget 调用的假记忆管理器（duck typing，不耦合实现）。"""

    def __init__(self, memories):
        # memories: list of dict {id, content, metadata, created_at}
        self.memories = list(memories)
        self.forgotten = []

    def get_all_memories(self):
        return [dict(m) for m in self.memories]

    def forget(self, memory_id, soft=True):
        self.forgotten.append((memory_id, soft))
        self.memories = [m for m in self.memories if m["id"] != memory_id]
        return True


class FakeAgent:
    def __init__(self, memory_manager):
        self.memory_manager = memory_manager


def _mem(mid, content, session_id, sender, created_at):
    return {
        "id": mid,
        "content": content,
        "metadata": {"session_id": session_id, "sender_type": sender},
        "created_at": created_at,
    }


def test_deletes_matching_user_and_agent_memories():
    mm = FakeMemoryManager([
        _mem("m1", "用户: Q1", "s1", "user", "2026-08-29T10:00:00+00:00"),
        _mem("m2", "助手: A1", "s1", "agent", "2026-08-29T10:00:01+00:00"),
    ])
    core = MemCore(FakeAgent(mm))

    n = core.delete_round_memories(
        session_id="s1",
        user_input="Q1",
        agent_response="A1",
        approx_ts="2026-08-29T10:00:00.500000",
    )

    assert n == 2
    assert {mid for mid, _ in mm.forgotten} == {"m1", "m2"}
    assert all(soft is False for _, soft in mm.forgotten)  # 硬删除


def test_duplicate_content_picks_closest_created_at():
    # 两轮用户消息内容相同（"继续"），只删时间上最接近的那条
    mm = FakeMemoryManager([
        _mem("m-old", "用户: 继续", "s1", "user", "2026-08-29T09:00:00+00:00"),
        _mem("m-new", "用户: 继续", "s1", "user", "2026-08-29T10:00:00+00:00"),
    ])
    core = MemCore(FakeAgent(mm))

    n = core.delete_round_memories(
        session_id="s1", user_input="继续", agent_response="",
        approx_ts="2026-08-29T09:59:59",
    )

    assert n == 1
    assert mm.forgotten[0][0] == "m-new"


def test_skips_other_sessions_and_empty_content():
    mm = FakeMemoryManager([
        _mem("m1", "用户: Q1", "s2", "user", "2026-08-29T10:00:00+00:00"),  # 其他 session
        _mem("m2", "用户: Q1", None, "user", "2026-08-29T10:00:00+00:00"),  # 无 session_id
    ])
    core = MemCore(FakeAgent(mm))

    n = core.delete_round_memories(
        session_id="s1", user_input="Q1", agent_response="",
    )

    assert n == 0
    assert mm.forgotten == []


def test_no_memory_manager_returns_zero():
    class AgentWithoutMM:
        memory_manager = None

    core = MemCore(AgentWithoutMM())
    assert core.delete_round_memories("s1", "Q", "A") == 0


def test_memory_manager_failure_is_swallowed():
    class BrokenMM:
        def get_all_memories(self):
            raise RuntimeError("storage down")

    core = MemCore(FakeAgent(BrokenMM()))
    # 记忆清除是 best-effort：失败不阻断轮次删除主流程
    assert core.delete_round_memories("s1", "Q", "A") == 0
