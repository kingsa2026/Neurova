# -*- coding: utf-8 -*-
"""S10 固定团队开放给主 agent——红灯（超越方案 S10 批，波4 会话I）。

五组红灯（方案 S10 节 + 附录 D S10 行）：
① list_teams 返回名册（数据单源 = teams_api JSON 落盘，不另建团队存储）；
② dispatch_team 按名册生成多路 spawn 且职责入任务书；TaskUnit.dependencies 步间编排；
③ 无 teamId 的 dispatch 结构化报错；未知团队拒绝；
④ 沉淀提议（propose_team）未经批准不写 teams_api、批准后写入
   （origin=agent_proposed / approved_by / promoted_from_run）；
⑤ 三工具（list_teams/dispatch_team/propose_team）对成员不可见（allowlist 剔除）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_team_dispatch_0123456789")

import pytest

import neurova.api.endpoints.teams_api as teamsApi
from neurova.agent.swarm import SwarmManager, computeSubagentToolAllowlist, reset_swarm_manager
from neurova.security.approval_manager import ApprovalManager
from neurova.security.approval_relay import installApprovalRelay


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return SwarmManager()


@pytest.fixture
def teamStore(monkeypatch, tmp_path):
    """团队名册单源：teams_api 的 JSON 落盘（临时目录隔离，用例间清场）。"""
    monkeypatch.setenv("NEUROVA_TEAMS_PATH", str(tmp_path / "teams_dispatch.json"))
    teamsApi._teams_store.clear()
    teamsApi._teams_store["team1"] = {
        "id": "team1",
        "name": "文档小队",
        "description": "写+评审",
        "members_detail": [
            {"user_id": "agent_writer", "name": "写手", "role": "author", "prompt": "负责起草文档"},
            {"user_id": "agent_reviewer", "name": "评审", "role": "reviewer", "prompt": "负责评审质量"},
        ],
    }
    yield teamsApi._teams_store
    teamsApi._teams_store.clear()
    teamsApi._pendingTeamProposals.clear()


@pytest.fixture
def executor():
    agent = MagicMock()
    agent.current_session_id = "sess-main"
    from neurova.tool_executor import ToolExecutor

    return ToolExecutor(agent), agent


# ── ① list_teams：列固定团队（名册摘要） ────────────────────────────


class TestListTeamsTool:
    @pytest.mark.asyncio
    async def test_list_teams_returns_roster(self, teamStore, executor):
        exe, _ = executor
        result = await exe._execute_list_teams({})
        teams = result.get("teams") or []
        assert result.get("count") == 1
        assert teams[0]["id"] == "team1"
        assert teams[0]["name"] == "文档小队"
        members = teams[0]["members"]
        assert [m["userId"] for m in members] == ["agent_writer", "agent_reviewer"]
        assert members[0]["duty"] == "负责起草文档"

    @pytest.mark.asyncio
    async def test_list_teams_schema_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        for name in ("list_teams", "dispatch_team", "propose_team"):
            assert name in _BUILTIN_SCHEMAS, f"{name} 未注册 schema"


# ── ②③ dispatch_team：多路 spawn + 职责入任务书 + 依赖步间编排 ───────


class TestDispatchTeam:
    @pytest.mark.asyncio
    async def test_dispatch_spawns_per_roster_member_with_duty(self, swarm, teamStore):
        spawn = AsyncMock(
            side_effect=[
                {"subagent_id": "swarm_a", "status": "pending", "background": True},
                {"subagent_id": "swarm_b", "status": "pending", "background": True},
            ]
        )
        with patch.object(SwarmManager, "spawn", spawn):
            out = await swarm.dispatchTeam("team1", "产出一版 API 文档", session_id="sess-main")
        assert out.get("success") is True
        assert out.get("team_id") == "team1"
        assert [d["subagent_id"] for d in out["dispatches"]] == ["swarm_a", "swarm_b"]
        assert spawn.await_count == 2
        first = spawn.await_args_list[0].kwargs
        second = spawn.await_args_list[1].kwargs
        # 多路 spawn：按名册逐成员派生，agent_id = 成员 user_id
        assert first["agent_id"] == "agent_writer"
        assert second["agent_id"] == "agent_reviewer"
        # 成员职责 prompt 注入任务书角色段
        assert "负责起草文档" in first["task"]
        assert "负责评审质量" in second["task"]
        assert "产出一版 API 文档" in first["task"]
        # run 带团队溯源标
        assert first["origin"] == "team_dispatch"
        assert first["team_id"] == "team1"
        assert first["team_role"] == "author"
        assert second["team_role"] == "reviewer"

    @pytest.mark.asyncio
    async def test_dispatch_remaps_task_unit_dependencies(self, swarm, teamStore):
        """TaskUnit.dependencies 步间编排：按名册序号/成员名声明的依赖映射到本次 spawn id。"""
        spawn = AsyncMock(
            side_effect=[
                {"subagent_id": "swarm_a", "status": "pending", "background": True},
                {"subagent_id": "swarm_b", "status": "blocked", "background": True},
            ]
        )
        taskUnit = {
            "goal": "产出一版 API 文档",
            "acceptanceCriteria": ["覆盖全部端点"],
            "dependencies": ["0"],  # 成员 1 依赖成员 0 的产出
        }
        with patch.object(SwarmManager, "spawn", spawn):
            out = await swarm.dispatchTeam(
                "team1", "产出一版 API 文档", taskUnit=taskUnit, session_id="sess-main")
        assert out.get("success") is True
        secondUnit = spawn.await_args_list[1].kwargs["task_unit"]
        assert secondUnit["dependencies"] == ["swarm_a"], "成员 1 的依赖应映射到成员 0 的 subagent_id"
        firstUnit = spawn.await_args_list[0].kwargs["task_unit"]
        assert firstUnit["dependencies"] == [], "首个成员不应带本次派生内部的依赖"

    @pytest.mark.asyncio
    async def test_dispatch_without_team_id_rejected(self, swarm, teamStore):
        out = await swarm.dispatchTeam("", "任务")
        assert out.get("rejected") is True
        assert out["rejection"]["code"] == "TEAM_ID_REQUIRED"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_team_rejected(self, swarm, teamStore):
        out = await swarm.dispatchTeam("ghost", "任务")
        assert out.get("rejected") is True
        assert out["rejection"]["code"] == "TEAM_UNKNOWN"

    @pytest.mark.asyncio
    async def test_dispatch_empty_roster_rejected(self, swarm, teamStore):
        teamStore["team1"]["members_detail"] = []
        out = await swarm.dispatchTeam("team1", "任务")
        assert out.get("rejected") is True
        assert out["rejection"]["code"] == "TEAM_EMPTY"

    @pytest.mark.asyncio
    async def test_dispatch_tool_calls_swarm(self, teamStore, executor):
        exe, agent = executor
        fakeSwarm = MagicMock()
        fakeSwarm.dispatchTeam = AsyncMock(return_value={"success": True, "dispatches": []})
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=fakeSwarm):
            result = await exe._execute_dispatch_team({"team_id": "team1", "task": "任务"})
        assert result.get("success") is True
        fakeSwarm.dispatchTeam.assert_awaited_once()
        kwargs = fakeSwarm.dispatchTeam.call_args.kwargs
        assert kwargs["teamId"] == "team1"
        assert kwargs["task"] == "任务"
        assert kwargs["session_id"] == "sess-main"
        assert kwargs["initiator_agent"] is agent

    @pytest.mark.asyncio
    async def test_dispatch_tool_requires_team_and_task(self, teamStore, executor):
        exe, _ = executor
        assert "error" in await exe._execute_dispatch_team({"task": "任务"})
        assert "error" in await exe._execute_dispatch_team({"team_id": "team1"})


# ── ④ 沉淀提议：未经批准不写 teams_api，批准后写入 ──────────────────


class TestTeamConsolidation:
    @pytest.fixture
    def approvals(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "0")
        mgr = ApprovalManager(str(tmp_path / "approval_team"))
        assert installApprovalRelay(mgr) is True
        with patch("neurova.security.approval_manager.get_approval_manager", return_value=mgr):
            yield mgr

    @staticmethod
    def _proposalParams():
        return {
            "name": "蜂群沉淀小队",
            "description": "本次任务组合沉淀",
            "members": [
                {"userId": "agent_writer", "name": "写手", "role": "author", "prompt": "负责起草"},
                {"userId": "agent_reviewer", "name": "评审", "role": "reviewer", "prompt": "负责评审"},
            ],
            "promoted_from_run": "swarm_abc123",
        }

    @pytest.mark.asyncio
    async def test_propose_pending_does_not_write_teams(self, teamStore, executor, approvals):
        exe, _ = executor
        result = await exe._execute_propose_team(self._proposalParams())
        assert result.get("approved") is False
        assert result.get("request_id")
        assert len(teamStore) == 1, "未经批准不得写入 teams_api"
        assert "team1" in teamStore

    @pytest.mark.asyncio
    async def test_propose_approved_writes_team(self, teamStore, executor, approvals):
        exe, _ = executor
        proposal = await exe._execute_propose_team(self._proposalParams())
        assert proposal.get("approved") is False
        rid = proposal["request_id"]
        # 人批准（主代理裁决工具路径）→ 写入 teams_api
        decided = await exe._execute_decide_approval(
            {"request_id": rid, "decision": "approve", "note": "同意沉淀"})
        assert decided.get("success") is True, decided
        newTeams = [t for tid, t in teamStore.items() if tid != "team1"]
        assert len(newTeams) == 1, "批准后应写入一条新团队"
        team = newTeams[0]
        assert team["name"] == "蜂群沉淀小队"
        assert team["origin"] == "agent_proposed"
        assert team["approved_by"]
        assert team["promoted_from_run"] == "swarm_abc123"
        assert {m["user_id"] for m in team["members_detail"]} == {"agent_writer", "agent_reviewer"}

    @pytest.mark.asyncio
    async def test_propose_rejected_does_not_write_teams(self, teamStore, executor, approvals):
        exe, _ = executor
        proposal = await exe._execute_propose_team(self._proposalParams())
        decided = await exe._execute_decide_approval(
            {"request_id": proposal["request_id"], "decision": "reject"})
        assert decided.get("success") is True
        assert len(teamStore) == 1, "驳回后不得写入 teams_api"

    @pytest.mark.asyncio
    async def test_propose_requires_name_and_members(self, teamStore, executor, approvals):
        exe, _ = executor
        assert "error" in await exe._execute_propose_team({"name": "x", "members": []})
        assert "error" in await exe._execute_propose_team({"name": "", "members": [{"userId": "a"}]})

    @pytest.mark.asyncio
    async def test_room_decide_path_also_writes_team(self, teamStore, executor, approvals):
        """房间裁决路径同样触发沉淀写入（判定回灌单源，两入口同效）。"""
        exe, _ = executor
        proposal = await exe._execute_propose_team(self._proposalParams())
        from neurova.agent.approval_chain import decideSwarmApproval
        from neurova.api.endpoints import collaboration_room_api as roomApi

        outcome = decideSwarmApproval(
            proposal["request_id"], "approve", decidedBy="owner_u", decidedByChannel="room")
        assert outcome.get("success") is True, outcome
        applied = teamsApi.applyTeamProposalDecision(
            proposal["request_id"], "approve", decidedBy="owner_u")
        assert applied.get("applied") is True
        newTeams = [t for tid, t in teamStore.items() if tid != "team1"]
        assert len(newTeams) == 1
        assert newTeams[0]["origin"] == "agent_proposed"


# ── ⑤ 三工具对成员不可见（allowlist 剔除） ──────────────────────────


class TestTeamToolsHiddenFromMembers:
    def test_member_allowlist_excludes_team_tools(self):
        allow = computeSubagentToolAllowlist("general")
        for name in ("list_teams", "dispatch_team", "propose_team"):
            assert name not in allow, f"{name} 必须从成员工具面剔除（主 agent 专属）"

    def test_explore_allowlist_excludes_team_tools(self):
        allow = computeSubagentToolAllowlist("explore")
        for name in ("list_teams", "dispatch_team", "propose_team"):
            assert name not in allow

    def test_spawn_still_excluded(self):
        allow = computeSubagentToolAllowlist("general")
        assert "spawn_subagent" not in allow
        assert "cancel_subagent" not in allow
