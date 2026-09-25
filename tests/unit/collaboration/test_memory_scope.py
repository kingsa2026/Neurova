"""memory_scope 纯函数单测：打标 / 允许集 / 三向过滤（群群隔离、单聊不被群污染、群读单聊基线）。"""
from __future__ import annotations

import asyncio

from neurova.collaboration.memory_scope import (
    DIRECT_SCOPE,
    allowed_scopes_for_turn,
    filter_memories_by_scope,
    filter_by_scope,
    memory_scope,
    scope_from_metadata,
    scope_tag_for_turn,
)


def _mem(scope=None, sid=""):
    md = {"session_id": sid}
    if scope is not None:
        md["chat_scope"] = scope
    return {"id": sid or "x", "content": "c", "metadata": md}


def test_scope_tag_for_turn():
    assert scope_tag_for_turn(collab=False) == DIRECT_SCOPE
    assert scope_tag_for_turn(collab=True, room_id="project_a") == "room:project_a"


def test_allowed_scopes():
    assert allowed_scopes_for_turn(collab=False) == {"direct"}
    assert allowed_scopes_for_turn(collab=True, room_id="project_a") == {"direct", "room:project_a"}


def test_memory_scope_defaults_direct_for_untagged():
    assert memory_scope(_mem()) == DIRECT_SCOPE            # 历史/无标签
    assert memory_scope(_mem(scope="room:project_a")) == "room:project_a"


def test_single_chat_never_sees_room_memories():
    mems = [_mem(scope="direct"), _mem(scope="room:project_a"), _mem()]  # 最后=历史=direct
    out = filter_memories_by_scope(mems, collab=False)
    scopes = [memory_scope(m) for m in out]
    assert scopes == [DIRECT_SCOPE, DIRECT_SCOPE]          # 两条 direct 保留，room 被剔除


def test_group_reads_baseline_and_own_room_only():
    mems = [
        _mem(scope="direct"),
        _mem(scope="room:project_a"),
        _mem(scope="room:project_b"),
        _mem(),  # 历史=direct 基线
    ]
    out = filter_memories_by_scope(mems, collab=True, room_id="project_a")
    scopes = [memory_scope(m) for m in out]
    assert "room:project_b" not in scopes                  # 群群隔离
    assert scopes.count("room:project_a") == 1             # 本群可见
    assert scopes.count(DIRECT_SCOPE) == 2                 # 单聊基线可读


# ── 写入侧打标：_step_save_memory 按 turn_origin 写 chat_scope ──
def _make_pipe():
    from neurova.post_chat_pipeline import PostChatPipeline

    calls: list = []

    class _MM:
        emotion_module = None

        def remember(self, content, memory_type, metadata, origin):
            calls.append(metadata)
            return "mid"

    pipe = object.__new__(PostChatPipeline)  # 跳过重初始化，专测打标行为
    mm = _MM()
    pipe._get_dependency = lambda name: mm if name == "memory_manager" else None
    pipe._save_emotion_to_memory = lambda *a, **k: None
    return pipe, calls


async def _drive_save(pipe, session_id, metadata):
    # 关键：_step_results 是 ContextVar；在主线程上下文外一切写/append 都
    # 限定在 asyncio.run 的任务上下文内（随任务销毁），不泄给同线程后续用例。
    pipe._step_results = []
    await pipe._step_save_memory("hi", "yo", session_id, True, metadata)


def test_step_save_memory_tags_room_scope():
    pipe, calls = _make_pipe()
    asyncio.run(_drive_save(pipe, "project_a", {"turn_origin": "collaboration"}))
    assert calls, "应写入两条记忆"
    assert all(m["chat_scope"] == "room:project_a" for m in calls)


def test_step_save_memory_defaults_direct():
    pipe, calls = _make_pipe()
    asyncio.run(_drive_save(pipe, "sess_1", {}))
    assert all(m["chat_scope"] == DIRECT_SCOPE for m in calls)


# ── 历史遗留：无 chat_scope 时从 session_id project_ 前缀回溯 ──
def test_legacy_room_memory_inferred_from_session_prefix():
    # 打标启用前的群聊记忆：只有 metadata.session_id=project_x，无 chat_scope。
    legacy_room = {"id": "m", "content": "c", "metadata": {"session_id": "project_a"}}
    assert memory_scope(legacy_room) == "room:project_a"
    # 单聊会话 id → 仍为 direct
    single = {"id": "m", "content": "c", "metadata": {"session_id": "sess_1"}}
    assert memory_scope(single) == DIRECT_SCOPE
    # 单聊轮不得召回遗留群记忆；同一房间轮可
    assert filter_memories_by_scope([legacy_room], collab=False) == []
    assert len(filter_memories_by_scope([legacy_room], collab=True, room_id="project_a")) == 1


def test_filter_by_scope_works_on_pool_chunks():
    from types import SimpleNamespace
    chunk_direct = SimpleNamespace(metadata={"session_id": "sess_1"})
    chunk_room_a = SimpleNamespace(metadata={"session_id": "project_a"})
    chunk_room_b = SimpleNamespace(metadata={"session_id": "project_b"})
    getter = lambda c: c.metadata
    # 单聊：仅 direct（跨普通会话保留，排除两个群）
    out = filter_by_scope([chunk_direct, chunk_room_a, chunk_room_b], getter, collab=False)
    assert out == [chunk_direct]
    # 群 A：direct + 本群，排除群 B
    out = filter_by_scope(
        [chunk_direct, chunk_room_a, chunk_room_b], getter, collab=True, room_id="project_a"
    )
    assert out == [chunk_direct, chunk_room_a]


def test_scope_from_metadata_explicit_wins():
    assert scope_from_metadata({"chat_scope": "direct", "session_id": "project_a"}) == "direct"
