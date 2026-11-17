# -*- coding: utf-8 -*-
"""S11 多 agent 协作双入口·入口二——红灯（超越方案 S11 批，波4 会话I）。

四组红灯（方案 S11 节 + 附录 D S11 行）：
① 房间协作消息（@全部成员）触发 swarm 编排（mock agent 成员）而非逐个独立应答；
② 进度事件回房间广播（spawn 的 session/room 指向房间会话 + 发起系统消息上墙）；
③ 非成员发起被 403（三级鉴权谓词复用）；
④ 预算参数生效（发起人显式预算落到 run 的运行窗口）。
另钉：统一任务书拼装（房间消息不直通 TaskUnit 正文）+ 具名常量截断。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_room_collab_01234567")

import pytest

from neurova.collaboration.room_bus import RoomBus
from neurova.collaboration.room_store import RoomStore
from neurova.collaboration.room_turn_router import (
    ROOM_COLLAB_TASK_MAX_CHARS,
    RoomTurnRouter,
    isCollaborationTrigger,
    composeRoomCollabBrief,
)

ROOM = "room_collab_1"
OWNER = "owner_u"
MEMBER_A = "member_u"
ACTOR = "member_u"

MEMBERS = [
    {"id": "agent_lead", "name": "主笔"},
    {"id": "agent_helper", "name": "助手"},
    {"id": "agent_check", "name": "复核"},
]


class _FakeRepo:
    """房间持久层替身（同 test_room_store 形态）。"""

    def __init__(self):
        self.saved = []

    def save_message(self, agent_id, session_id, role, content, metadata=None, *, user_id=""):
        self.saved.append({
            "agent_id": agent_id, "session_id": session_id, "role": role,
            "content": content, "metadata": metadata or {}, "timestamp": len(self.saved) + 1,
        })
        return True

    def get_history(self, agent_id, session_id, max_messages=0):
        return self.saved


@pytest.fixture
def roomStore(monkeypatch):
    repo = _FakeRepo()
    store = RoomStore(repo=repo)
    monkeypatch.setattr("neurova.collaboration.room_store.get_room_store", lambda: store)
    return store


@pytest.fixture
def roomBus(monkeypatch):
    mgr = MagicMock()
    mgr.broadcast_event = AsyncMock(return_value=0)
    bus = RoomBus(manager=mgr)
    monkeypatch.setattr("neurova.collaboration.room_bus.get_room_bus", lambda: bus)
    return bus


@pytest.fixture
def router(roomStore, roomBus):
    lookup = MagicMock()
    lookup.chat = AsyncMock(return_value={"text": "不应被逐个调用"})
    return RoomTurnRouter(store=roomStore, bus=roomBus, agent_lookup=lookup), lookup


def _spawnResult(sid: str):
    return {"subagent_id": sid, "agent_id": sid, "status": "pending", "background": True}


# ── ① 协作模式识别：@全部成员 ────────────────────────────────────────


class TestCollabTrigger:
    def test_all_members_mentioned_triggers(self):
        text = "@主笔 @助手 @复核 请协作完成一份竞品分析"
        assert isCollaborationTrigger(text, MEMBERS) is True

    def test_partial_mention_does_not_trigger(self):
        assert isCollaborationTrigger("@主笔 请完成分析", MEMBERS) is False

    def test_no_mention_does_not_trigger(self):
        assert isCollaborationTrigger("大家好", MEMBERS) is False

    def test_single_member_room_does_not_trigger(self):
        assert isCollaborationTrigger("@主笔 单人房间", MEMBERS[:1]) is False

    def test_named_constant_exists(self):
        assert ROOM_COLLAB_TASK_MAX_CHARS > 0, "任务指令截断必须走具名常量（附录 A2 钉子）"


# ── ② 协作消息触发 swarm 编排，而非逐个独立应答 ──────────────────────


class TestCollabOrchestration:
    @pytest.mark.asyncio
    async def test_collab_message_orchestrates_swarm(self, router, roomStore, roomBus):
        rt, lookup = router
        swarm = MagicMock()
        swarm.spawn = AsyncMock(side_effect=[
            _spawnResult("swarm_lead"), _spawnResult("swarm_h"), _spawnResult("swarm_c"),
        ])
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=swarm):
            await rt.handle_user_message(
                ROOM, "@主笔 @助手 @复核 协作完成竞品分析", ACTOR, MEMBERS)
        # swarm 编排：每名成员一路 spawn（lead 先行、支援依赖主执行者）
        assert swarm.spawn.await_count == 3, "协作消息必须交 SwarmManager 编排（每成员一路 spawn）"
        # 不再逐个独立应答（Agent.chat 不得被调用）
        lookup.chat.assert_not_awaited()
        # 主从/依赖：支援成员的 task_unit.dependencies 指向主的 subagent_id
        leadKw = swarm.spawn.await_args_list[0].kwargs
        helperKw = swarm.spawn.await_args_list[1].kwargs
        assert leadKw["agent_id"] == "agent_lead"
        assert helperKw["task_unit"]["dependencies"] == ["swarm_lead"]

    @pytest.mark.asyncio
    async def test_progress_events_target_room_session(self, router, roomStore, roomBus):
        """执行事件回房间广播：spawn 的 session/room 指向房间会话（复用 H-4/S9 通道）。"""
        rt, _ = router
        swarm = MagicMock()
        swarm.spawn = AsyncMock(side_effect=[
            _spawnResult("swarm_lead"), _spawnResult("swarm_h"), _spawnResult("swarm_c"),
        ])
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=swarm):
            out = await rt.orchestrateRoomCollaboration(ROOM, "协作任务", ACTOR, MEMBERS)
        assert out.get("success") is True
        for call in swarm.spawn.await_args_list:
            kw = call.kwargs
            assert kw["session_id"] == ROOM, "subagent_* 事件必须广播到房间会话"
            assert kw["room_id"] == ROOM, "member 记忆按 room 作用域共享（S9 黑板）"
            assert kw["origin"] == "room_collab"
        # 发起事实以系统消息上墙（房间可回看）
        kinds = [ (r.get("meta") or {}).get("kind") for r in roomStore.history(ROOM) ]
        assert "swarm_collab" in kinds, "发起协作必须有系统消息上墙"

    @pytest.mark.asyncio
    async def test_budget_and_max_members_applied(self, router):
        rt, _ = router
        swarm = MagicMock()
        swarm.spawn = AsyncMock(side_effect=lambda **kw: _spawnResult(f"swarm_{kw['agent_id']}"))
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=swarm):
            out = await rt.orchestrateRoomCollaboration(
                ROOM, "协作任务", ACTOR, MEMBERS, budgetSeconds=123.5, maxMembers=1)
        assert out.get("success") is True
        budgets = [c.kwargs.get("runtimeBudgetSec") for c in swarm.spawn.await_args_list]
        assert budgets == [123.5, 123.5], "发起人显式预算必须落到每一路 run 的运行窗口"
        # maxMembers=1：主执行者 1 路 + 支援 1 路（第三名成员不参与本批）
        assert swarm.spawn.await_count == 2

    @pytest.mark.asyncio
    async def test_lead_rejection_fails_honestly(self, router, roomStore, roomBus):
        rt, _ = router
        swarm = MagicMock()
        swarm.spawn = AsyncMock(return_value={
            "rejected": True,
            "rejection": {"code": "BUDGET_EXCEEDED", "message": "预算已超支"},
        })
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=swarm):
            out = await rt.orchestrateRoomCollaboration(ROOM, "协作任务", ACTOR, MEMBERS)
        assert out.get("success") is False
        assert "预算" in out.get("error", ""), "治理拒绝必须如实上抛，不静默"
        assert swarm.spawn.await_count == 1, "主执行者被拒后不得继续派支援"

    @pytest.mark.asyncio
    async def test_brief_composed_not_raw_passthrough(self, router):
        """统一任务书拼装：房间消息不直通 TaskUnit 正文。"""
        rt, _ = router
        swarm = MagicMock()
        swarm.spawn = AsyncMock(side_effect=[
            _spawnResult("swarm_lead"), _spawnResult("swarm_h"), _spawnResult("swarm_c"),
        ])
        raw = "协作完成竞品分析"
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=swarm):
            await rt.orchestrateRoomCollaboration(ROOM, raw, ACTOR, MEMBERS)
        leadTask = swarm.spawn.await_args_list[0].kwargs["task"]
        assert "【协作任务书】" in leadTask
        assert raw in leadTask, "任务指令原文保留在任务书中"
        assert leadTask != raw, "不得把房间消息当 TaskUnit 正文直通"
        assert "主笔" in leadTask and "助手" in leadTask, "参与成员与主从关系入任务书"

    def test_brief_truncates_by_named_constant(self):
        huge = "x" * (ROOM_COLLAB_TASK_MAX_CHARS * 3)
        brief = composeRoomCollabBrief(
            ROOM, ACTOR, "agent_lead", MEMBERS, huge, [], {})
        assert len(brief) < ROOM_COLLAB_TASK_MAX_CHARS * 2, "任务书必须按具名常量截断"
        assert "【协作任务书】" in brief


# ── ③④ 入口二动作端点：成员发起 + 非成员 403 + 预算透传 ─────────────


class TestStartCollaborationEndpoint:
    @pytest.fixture
    def roomProject(self, monkeypatch):
        project = SimpleNamespace(
            project_id=ROOM, owner_id=OWNER,
            members={OWNER: {"role": "owner"}, MEMBER_A: {"role": "member"}},
            metadata={"responder_agent_id": "agent_lead"},
        )
        manager = MagicMock()
        manager.get_project.return_value = project
        # 注意：patch 使用点（collaboration_room_api 已 from-import 该名字），
        # 而不是定义点——全量套件里模块先于本用例被导入，定义点补丁不生效。
        monkeypatch.setattr(
            "neurova.api.endpoints.collaboration_room_api.get_collaboration_manager",
            lambda: manager)
        return project

    @pytest.fixture
    def memberDicts(self, monkeypatch):
        dicts = [{"id": m["id"], "name": m["name"]} for m in MEMBERS]
        monkeypatch.setattr(
            "neurova.api.endpoints.collaboration_room_api._member_dicts",
            lambda project: dicts)
        return dicts

    @pytest.mark.asyncio
    async def test_non_member_forbidden(self, roomProject, memberDicts):
        from fastapi import HTTPException

        from neurova.api.endpoints import collaboration_room_api as roomApi

        with pytest.raises(HTTPException) as excinfo:
            await roomApi.start_room_collaboration(
                ROOM,
                roomApi.StartCollaborationBody(task="协作任务"),
                {"user_id": "intruder", "role": "user"},
            )
        assert excinfo.value.status_code == 403, "非成员发起协作必须 403"

    @pytest.mark.asyncio
    async def test_member_starts_collaboration(self, roomProject, memberDicts):
        from neurova.api.endpoints import collaboration_room_api as roomApi

        rt = MagicMock()
        rt.orchestrateRoomCollaboration = AsyncMock(return_value={"success": True})
        with patch("neurova.api.endpoints.collaboration_room_api.get_room_turn_router",
                   return_value=rt):
            res = await roomApi.start_room_collaboration(
                ROOM,
                roomApi.StartCollaborationBody(task="协作任务", budget_seconds=66.0),
                {"user_id": MEMBER_A, "role": "user"},
            )
        assert res["code"] == 0
        rt.orchestrateRoomCollaboration.assert_awaited_once()
        kwargs = rt.orchestrateRoomCollaboration.call_args.kwargs
        assert kwargs["budgetSeconds"] == 66.0, "发起人显式预算必须透传给编排"
        assert kwargs["responder_agent_id"] == "agent_lead"

    @pytest.mark.asyncio
    async def test_empty_task_rejected(self, roomProject, memberDicts):
        from fastapi import HTTPException

        from neurova.api.endpoints import collaboration_room_api as roomApi

        with pytest.raises(HTTPException) as excinfo:
            await roomApi.start_room_collaboration(
                ROOM,
                roomApi.StartCollaborationBody(task="   "),
                {"user_id": MEMBER_A, "role": "user"},
            )
        assert excinfo.value.status_code == 400
