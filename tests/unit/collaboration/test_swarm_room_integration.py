# -*- coding: utf-8 -*-
"""S9 团队/房间能力接入蜂群——房间桥接集成测试（超越方案 S9 批，波3 会话H）。

四组红灯（方案 S9 节 + 附录 D S9 行）：
① 升级与审批消息在房间可见（sender_type=system 房间消息，零新表零新协议）；
② 群主回复回灌判定成功；普通成员回复只记议见不判定（决策权限=房间群主制度）；
③ 候选 submitted/merged/conflict 事件在房间可查，人在房间可拦截合并；
④ 按团队名册选人 spawn 生效（角色复用 collaboration_template.AgentRole）。

外加：memory_scope 的 run:<run_id> 同构作用域与显式 chat_scope 透传（要点4）；
AgentTeam 与 Swarm 的边界复核（要点5，教义第7条：编排不双实现）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_swarm_room_int_0123456789")

import pytest

from neurova.agent.approval_chain import handleRoomSwarmReply, requestRunApproval
from neurova.agent.swarm import (
    SwarmManager,
    memberChatScope,
    reset_swarm_manager,
    get_swarm_manager,
    SubAgentRun,
)
from neurova.agent.team import AgentTeam
from neurova.collaboration.memory_scope import (
    allowed_scopes_for_tag,
    allowed_scopes_for_turn,
    filter_memories_by_scope,
    scope_tag_for_turn,
    turnScopeContext,
)
from neurova.collaboration.room_bus import RoomBus
from neurova.collaboration.room_store import RoomStore
from neurova.security.approval_manager import ApprovalManager
from neurova.security.approval_relay import installApprovalRelay

ROOM = "room_x"
OWNER = "owner_u"
MEMBER = "member_u"


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


@pytest.fixture(autouse=True)
def _cleanRoomBridge():
    """房间桥接的 pending 登记表是进程内模块级索引——用例间必须清场。"""
    from neurova.agent import approval_chain as ac

    ac._roomApprovalRegistry.clear()
    ac._roomCandidateRegistry.clear()
    yield
    ac._roomApprovalRegistry.clear()
    ac._roomCandidateRegistry.clear()


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
def roomProject(monkeypatch):
    """房间群主制度桩：owner_u 是群主，member_u 是普通成员。"""
    project = SimpleNamespace(
        project_id=ROOM, owner_id=OWNER, members={OWNER: {"role": "owner"}, MEMBER: {"role": "member"}},
    )
    manager = MagicMock()
    manager.get_project.return_value = project
    monkeypatch.setattr(
        "neurova.collaboration.collaboration_isolation.get_collaboration_manager", lambda: manager)
    return project


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    """真 ApprovalManager（临时数据根）+ 中继；WAIT_S=0 让审批请求不挂起等待。"""
    monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "0")
    mgr = ApprovalManager(str(tmp_path / "approval_room"))
    assert installApprovalRelay(mgr) is True
    with patch("neurova.security.approval_manager.get_approval_manager", return_value=mgr):
        yield mgr


@pytest.fixture
def parentMail():
    box = MagicMock()
    with patch("neurova.agent.mailbox.get_agent_mailbox", return_value=box):
        yield box


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


def makeRun(**kw) -> SubAgentRun:
    defaults = dict(
        agent_id="child", agent_name="子代理", task="整理数据",
        session_id="parent_s", origin="chat",
        member_session_id="swarm_member_room", room_id=ROOM,
    )
    defaults.update(kw)
    return SubAgentRun(**defaults)


def roomKinds(store, kind: str):
    return [r for r in store.history(ROOM) if (r.get("meta") or {}).get("kind") == kind]


# ── ① 升级与审批消息在房间可见 ──────────────────────────────────────


class TestEscalateAndApprovalVisibleInRoom:
    def test_escalation_lands_in_room_history(self, swarm, roomStore, roomBus):
        run = makeRun()
        swarm._runs[run.subagent_id] = run
        swarm.recordEscalation(run, reason="need_human", question="要继续读取文件吗", severity="high")
        rows = roomKinds(roomStore, "swarm_escalate")
        assert rows, "升级消息必须投递到协作房间（sender_type=system）"
        assert rows[-1]["sender_type"] == "system"
        assert "要继续读取文件吗" in rows[-1]["content"]
        assert rows[-1]["meta"]["subagent_id"] == run.subagent_id

    @pytest.mark.asyncio
    async def test_approval_request_lands_in_room_history(
        self, swarm, roomStore, roomBus, approvals, parentMail,
    ):
        run = makeRun()
        swarm._runs[run.subagent_id] = run
        verdict = await requestRunApproval(run, "删除生产数据库表", reason="清理过期分区", level="L2")
        assert verdict["pending"] is True
        rows = roomKinds(roomStore, "swarm_approval")
        assert rows, "审批请求必须投递到协作房间"
        meta = rows[-1]["meta"]
        assert meta["request_id"] == verdict["request_id"]
        assert meta["level"] == "L2"
        assert meta["subagent_id"] == run.subagent_id


# ── ② 群主回复回灌判定成功；普通成员回复只记议见 ────────────────────


class TestOwnerDecidesMemberOpinion:
    @pytest.mark.asyncio
    async def test_owner_decides_and_member_only_opinion(
        self, swarm, roomStore, roomBus, approvals, parentMail, roomProject,
    ):
        run = makeRun()
        swarm._runs[run.subagent_id] = run
        verdict = await requestRunApproval(run, "外发统计数据", reason="季度报表外发", level="L2")
        rid = verdict["request_id"]

        # 普通成员回复：只记议见，不判定
        res = handleRoomSwarmReply(ROOM, MEMBER, isAdmin=False, text="同意")
        assert res["matched"] == "approval"
        assert res.get("recorded") == "opinion"
        assert approvals.get_request(rid).status.value == "pending"

        # 群主回复：回灌判定成功
        res2 = handleRoomSwarmReply(ROOM, OWNER, isAdmin=False, text="同意批准")
        assert res2["matched"] == "approval"
        assert res2["decision_result"]["success"] is True
        req = approvals.get_request(rid)
        assert req.status.value == "approved"
        assert (req.approved_by or "") == OWNER, "审批单应记录房间决策人（群主）身份"

        # 拒绝路径：群主驳回 → rejected
        verdict2 = await requestRunApproval(run, "再删一次表", reason="测试拒绝路径", level="L2")
        res3 = handleRoomSwarmReply(ROOM, OWNER, isAdmin=False, text="驳回")
        assert res3["matched"] == "approval"
        assert res3["decision_result"]["success"] is True
        assert approvals.get_request(verdict2["request_id"]).status.value == "rejected"


# ── ③ 候选事件在房间可查 + 房间拦截 ─────────────────────────────────


class TestCandidateRoom:
    def test_submitted_event_visible_and_interceptable(self, swarm, roomStore, roomBus, roomProject):
        run = makeRun(task_unit={"artifactOwnership": "docs/api.md"})
        swarm._runs[run.subagent_id] = run
        cand = swarm._submitResultCandidate(run, "API 文档初稿")

        evts = roomKinds(roomStore, "swarm_candidate")
        assert evts, "候选提交事件必须投递到协作房间"
        assert evts[-1]["meta"]["candidate_id"] == cand.candidateId
        assert evts[-1]["meta"]["status"] == "submitted"

        # 群主在房间拦截该候选
        res = handleRoomSwarmReply(ROOM, OWNER, isAdmin=False, text=f"拦截 {cand.candidateId}")
        assert res["matched"] == "candidate"
        assert res["action"] == "intercept"
        assert swarm._candidates.candidate(cand.candidateId).status == "rejected"

    @pytest.mark.asyncio
    async def test_merged_event_visible_in_room(
        self, swarm, roomStore, roomBus, approvals, parentMail,
    ):
        run = makeRun()
        swarm._runs[run.subagent_id] = run
        cand = swarm._submitResultCandidate(run, "结果 A")
        outcome = await swarm._mergeCandidateForRun(run, cand)  # 默认 L0 自动放行
        assert outcome["merged"] is True
        evts = roomKinds(roomStore, "swarm_candidate")
        assert any(
            e["meta"].get("status") == "merged" and e["meta"].get("candidate_id") == cand.candidateId
            for e in evts
        ), "候选合入事件必须在房间可查"


# ── ④ 按团队名册选人 spawn ──────────────────────────────────────────


class TestTeamRosterSpawn:
    @pytest.fixture
    def teamRoster(self, monkeypatch, tmp_path):
        import neurova.api.endpoints.teams_api as teamsApi

        monkeypatch.setenv("NEUROVA_TEAMS_PATH", str(tmp_path / "teams_room.json"))
        teamsApi._teams_store.clear()
        teamsApi._teams_store["team1"] = {
            "id": "team1", "name": "评审小组",
            "members_detail": [
                {"user_id": "agent_writer", "name": "写手", "role": "author", "prompt": "负责起草文档"},
                {"user_id": "agent_reviewer", "name": "评审", "role": "reviewer", "prompt": "负责评审质量"},
            ],
        }
        yield teamsApi._teams_store
        teamsApi._teams_store.clear()

    @staticmethod
    def _stubExec(monkeypatch):
        async def _noExec(run, agent, initiator, stream, *a, **k):
            return run

        monkeypatch.setattr(SwarmManager, "_execute", _noExec)

    @staticmethod
    def _stubResolve(monkeypatch):
        def _resolve(self, agent_id):
            resolved = agent_id or "default"
            return SimpleNamespace(config=SimpleNamespace(name=resolved), llm_client=None), resolved, False

        monkeypatch.setattr(SwarmManager, "_resolve_agent", _resolve)

    def test_spawn_selects_member_by_task_text(self, swarm, teamRoster, monkeypatch):
        self._stubExec(monkeypatch)
        self._stubResolve(monkeypatch)
        out = asyncio.run(swarm.spawn("请评审这份 API 文档，重点评审质量", team_id="team1", background=True))
        assert not out.get("rejected"), out
        assert out.get("team_id") == "team1"
        assert out.get("selected_member", {}).get("user_id") == "agent_reviewer"

    def test_spawn_selects_by_role(self, swarm, teamRoster, monkeypatch):
        self._stubExec(monkeypatch)
        self._stubResolve(monkeypatch)
        out = asyncio.run(swarm.spawn("处理任务", team_id="team1", team_role="reviewer", background=True))
        assert not out.get("rejected"), out
        assert out.get("selected_member", {}).get("user_id") == "agent_reviewer"
        assert out.get("team_role") == "reviewer"

    def test_spawn_rejects_unknown_team(self, swarm, teamRoster, monkeypatch):
        self._stubExec(monkeypatch)
        out = asyncio.run(swarm.spawn("任务", team_id="ghost", background=True))
        assert out.get("rejected") is True
        assert out["rejection"]["code"] == "TEAM_UNKNOWN"

    def test_spawn_rejects_unknown_role(self, swarm, teamRoster, monkeypatch):
        self._stubExec(monkeypatch)
        out = asyncio.run(swarm.spawn("任务", team_id="team1", team_role="boss", background=True))
        assert out.get("rejected") is True
        assert out["rejection"]["code"] == "TEAM_ROLE_UNKNOWN"


# ── 要点4：memory_scope 的 run 作用域同构 + 显式 chat_scope 透传 ─────


class TestMemoryScopeRunExtension:
    def test_run_scope_same_shape_as_room(self):
        assert allowed_scopes_for_tag("run:r1") == {"direct", "run:r1"}
        assert allowed_scopes_for_tag("room:p1") == {"direct", "room:p1"}

    def test_explicit_chat_scope_passthrough(self):
        ctx = turnScopeContext({"chat_scope": "run:r1"}, "some_session")
        assert scope_tag_for_turn(**ctx) == "run:r1"
        assert allowed_scopes_for_turn(**ctx) == {"direct", "run:r1"}

    def test_filter_memories_with_explicit_scope(self):
        ctx = turnScopeContext({"chat_scope": "room:p9"}, "s")
        items = [{"metadata": {"chat_scope": "room:p9"}}, {"metadata": {"chat_scope": "direct"}}]
        kept = filter_memories_by_scope(items, **ctx)
        assert len(kept) == 2, "room 轮应可见 direct + 本房间"

    def test_member_chat_scope_from_run(self):
        assert memberChatScope(SimpleNamespace(room_id=ROOM)) == f"room:{ROOM}"
        assert memberChatScope(SimpleNamespace(room_id="")) == ""


# ── 要点5：AgentTeam 与 Swarm 边界复核（教义第7条）───────────────────


class TestTeamSwarmBoundary:
    def test_orchestration_stays_single_source(self):
        """AgentTeam=ACP 步骤编排；Swarm=进程内子代理治理。编排面不复制进 SwarmManager。"""
        assert hasattr(AgentTeam, "orchestrate")
        assert not hasattr(SwarmManager, "orchestrate")
