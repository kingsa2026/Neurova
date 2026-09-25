"""RoomTurnRouter 单元测试：@路由 + 默认应答者 + 执行（落库/广播/调 Agent）。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from neurova.collaboration.room_turn_router import RoomTurnRouter, resolve_targets, build_room_history
from neurova.sync.session_sync_manager import EventType

MEMBERS = [{"id": "a1", "name": "Alpha"}, {"id": "a2", "name": "凯蒂"}]


# ── 纯逻辑：resolve_targets ──────────────────────────────────
def test_at_mention_by_name():
    assert resolve_targets("@凯蒂 看看", MEMBERS, "a1") == ["a2"]


def test_at_mention_by_id():
    assert resolve_targets("hello @a2", MEMBERS, "a1") == ["a2"]


def test_multiple_mentions_in_order():
    assert resolve_targets("@Alpha 然后 @凯蒂", MEMBERS, "") == ["a1", "a2"]


def test_no_mention_falls_back_to_responder():
    assert resolve_targets("随便聊聊", MEMBERS, "a2") == ["a2"]


def test_no_mention_no_responder_uses_first_member():
    assert resolve_targets("hi", MEMBERS, "") == ["a1"]


def test_empty_members_returns_empty():
    assert resolve_targets("hi", [], "") == []


def test_ignores_empty_id_member():
    # 历史遗留：/start 未传 owner 会写入空键成员；应被忽略，不得回落成空 id 而误触 default agent
    assert resolve_targets("hi", [{"id": "", "name": ""}], "") == []


def test_fallback_skips_empty_to_first_real_member():
    assert resolve_targets("hi", [{"id": "", "name": ""}, {"id": "a1", "name": "A"}], "") == ["a1"]


# ── 跨 agent 共享上下文：build_room_history ─────────────────
def test_build_room_history_labels_and_drops_current():
    rows = [
        {"sender_type": "user", "sender_id": "u1", "content": "hi Neurova"},
        {"sender_type": "agent", "sender_id": "a1", "content": "hello"},
        {"sender_type": "user", "sender_id": "u1", "content": "@凯 继续"},
    ]
    hist = build_room_history(rows, "@凯 继续", {"a1": "Neurova"})
    # 去掉本轮当前 user 消息 → 剩 2 条；agent 发言冠名区分“别人说的”
    assert hist == [
        {"role": "user", "content": "hi Neurova"},
        {"role": "assistant", "content": "[Neurova]: hello"},
    ]


def test_build_room_history_caps_recent():
    rows = [{"sender_type": "user", "sender_id": "u", "content": f"m{i}"} for i in range(30)]
    hist = build_room_history(rows, "__none__", {}, max_turns=5)
    assert len(hist) == 5
    assert hist[-1]["content"] == "m29"


def test_run_agent_injects_shared_history():
    # 根因回归：被 @ 的 agent 必须拿到房间共享转录（含其他 agent 回复），才能接住上下文。
    store = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    store.history.return_value = [
        {"sender_type": "user", "sender_id": "u1", "content": "plan trip"},
        {"sender_type": "agent", "sender_id": "a1", "content": "where?"},
        {"sender_type": "user", "sender_id": "u1", "content": "japan"},
    ]
    captured = {}

    async def fake_chat(msg, **kw):
        captured.update(kw)
        return {"text": "ok"}

    agent = MagicMock()
    agent.chat = fake_chat
    router = RoomTurnRouter(store=store, bus=bus, agent_lookup=MagicMock(return_value=agent))
    asyncio.run(router.handle_user_message(
        "project_x", "japan", "u1",
        [{"id": "a1", "name": "Neurova"}, {"id": "a2", "name": "凯"}], "a2",
    ))
    assert captured["session_id"] == "project_x"
    meta = captured["metadata"]
    assert meta["turn_origin"] == "collaboration"
    assert meta["history"] == [
        {"role": "user", "content": "plan trip"},
        {"role": "assistant", "content": "[Neurova]: where?"},
    ]


# ── 编排：handle_user_message ────────────────────────────────
def test_handle_user_message_persists_and_routes():
    store = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    agent = MagicMock()

    async def fake_chat(msg, **kw):
        return {"text": "pong"}

    agent.chat = fake_chat
    lookup = MagicMock(return_value=agent)
    router = RoomTurnRouter(store=store, bus=bus, agent_lookup=lookup)

    asyncio.run(router.handle_user_message("project_x", "@Alpha ping", "u1", MEMBERS, ""))

    senders = [(c.args[1], c.args[2]) for c in store.append.call_args_list]
    assert ("user", "u1") in senders          # 人类消息落库
    assert ("agent", "a1") in senders         # 被 @ 的 Alpha 回应落库
    types = [c.args[1] for c in bus.publish.call_args_list]
    assert EventType.USER_MESSAGE.value in types
    assert EventType.AGENT_REPLY.value in types
    # 仅被 @ 的 a1 回应，a2 不调用
    assert [c.kwargs.get("agent_id") or c.args[0] for c in lookup.call_args_list] == ["a1"]


def test_agent_error_when_lookup_none():
    store = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    router = RoomTurnRouter(store=store, bus=bus, agent_lookup=MagicMock(return_value=None))
    asyncio.run(router.handle_user_message("project_x", "@Alpha x", "u1", MEMBERS, ""))
    types = [c.args[1] for c in bus.publish.call_args_list]
    assert EventType.AGENT_ERROR.value in types


def test_agent_reply_persists_and_broadcasts_turn_meta():
    # 回归闭环：agent.chat 返回体携 tool_messages/reasoning → 落库 meta + 广播载荷，
    # 房间刷新可重建工具/推理步骤。
    store = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    agent = MagicMock()
    tools = [{"type": "tool_call", "tool_name": "search", "params": {"q": "x"}}]

    async def fake_chat(msg, **kw):
        return {"text": "pong", "tool_messages": tools, "reasoning": "thinking..."}

    agent.chat = fake_chat
    router = RoomTurnRouter(store=store, bus=bus, agent_lookup=MagicMock(return_value=agent))
    asyncio.run(router.handle_user_message("project_x", "@Alpha ping", "u1", MEMBERS, ""))

    agent_append = next(c for c in store.append.call_args_list if c.args[1] == "agent")
    assert agent_append.kwargs["meta"] == {"tool_calls": tools, "reasoning_content": "thinking..."}
    reply_publish = next(c for c in bus.publish.call_args_list if c.args[1] == EventType.AGENT_REPLY.value)
    payload = reply_publish.args[2]
    assert payload["tool_messages"] == tools
    assert payload["reasoning"] == "thinking..."
