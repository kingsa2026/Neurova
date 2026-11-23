# -*- coding: utf-8 -*-
"""S12 项目协作档案：留底 + 可观测（F1 4→5）单元测试（TDD RED→GREEN）。

覆盖（方案 §S12 红灯四条 + 两条同通道验证）：
① 房间发起的 run 带项目标——room_id = 协作 project_id 既有等式，spawn 落台账行
   必须写 project_id；S10 移交的 team_id 同通道落库；
② 档案端点 GET /projects/{id}/collaboration 聚合 run/事件/候选/审批（+房间消息）
   五类记录——全部读既有持久面（台账/H-4 账本/候选板/审计单源/RoomStore），
   读时 join，不建第二本账；
③ 项目封卷（status → archived）自动从账本生成协作总结并留底项目档案；
④ 无 project 标的 run 不串入档案（按 project_id 精确归属，不按时间/会话兜底）。
另：get_project_stats 新增 runs_count 口径且既有字段向后兼容。
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def dossierEnv(tmp_path, monkeypatch):
    """数据根/台账库整体重定向到临时目录；蜂群与台账单例逐测试重置。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "agent_runs.db"))
    from neurova.core.agent_run_store import reset_agent_run_store
    from neurova.agent.swarm import reset_swarm_manager

    reset_agent_run_store()
    reset_swarm_manager()
    yield tmp_path
    reset_swarm_manager()
    reset_agent_run_store()


@pytest.fixture
def auditDb(tmp_path):
    """审计单例整体重定向到 tmp_path（S8 单源；log_audit 与查询同落这份）。"""
    import neurova.security.audit_logger as auditModule

    savedInstance = auditModule.AuditLogger._instance
    savedGlobal = auditModule._audit_logger
    auditModule.AuditLogger._instance = None
    auditModule._audit_logger = None
    try:
        auditLogger = auditModule.AuditLogger(db_path=str(tmp_path / "audit.db"))
        auditModule._audit_logger = auditLogger
        yield auditLogger
    finally:
        auditModule.AuditLogger._instance = savedInstance
        auditModule._audit_logger = savedGlobal


@pytest.fixture
def client(dossierEnv, auditDb, monkeypatch):
    from neurova.api.endpoints import projects_api
    from neurova.collaboration.collaboration_isolation import CollaborationIsolationManager
    from neurova.collaboration.room_store import RoomStore

    tmp_path = dossierEnv
    manager = CollaborationIsolationManager(data_dir=str(tmp_path / "collab"))
    monkeypatch.setattr(projects_api, "_get_iso_manager", lambda: manager)
    monkeypatch.setattr(projects_api, "_get_scheduler", lambda: MagicMock())
    # 房间消息读面用真 RoomStore（数据根已由 dossierEnv 隔离到 tmp）
    roomStore = RoomStore()
    monkeypatch.setattr(projects_api, "_get_room_store", lambda: roomStore, raising=False)

    app = FastAPI()
    app.include_router(projects_api.router, prefix="/api/v1/projects")
    from neurova.api.auth import get_current_user as _gcu

    app.dependency_overrides[_gcu] = lambda: {
        "user_id": "u1", "username": "u1", "role": "admin", "neuser_id": "u1",
    }
    testClient = TestClient(app)

    project = manager.create_project(name="档案项目", owner_id="u1")
    testClient.project_id = project.project_id  # type: ignore[attr-defined]
    testClient.manager = manager  # type: ignore[attr-defined]
    testClient.roomStore = roomStore  # type: ignore[attr-defined]
    return testClient


def _fake_agent(reply="成员最终报告"):
    agent = MagicMock()
    agent.config.name = "成员Agent"
    agent.chat = MagicMock()  # 在异步测试内再换 AsyncMock
    return agent


def _seedTaggedRun(projectId, subagentId="swarm_dos1", teamId=""):
    """经唯一写点 openSubagentRun 落一条带项目标的台账行，返回 run_id。"""
    from neurova.core.agent_run_ledger import openSubagentRun

    return openSubagentRun(
        memberSessionId=f"member_{subagentId}",
        subagentId=subagentId,
        parentSessionId="parent_s1",
        userId="u1",
        agentId="member_a",
        task="档案聚合任务",
        projectId=projectId,
        teamId=teamId,
    )


class TestRunProjectTagging:
    """① run→project 归属标签：房间发起/直发带项目上下文/team 三条通道。"""

    @pytest.mark.asyncio
    async def test_roomInitiatedRunCarriesProjectTag(self, client):
        """S11 入口二：房间发起的协作 spawn 落台账行必须带 project_id（=room_id）。"""
        from neurova.agent.swarm import get_swarm_manager
        from neurova.core.agent_run_store import get_agent_run_store

        pid = client.project_id
        agent = _fake_agent()
        agent.chat = AsyncMock(return_value={"text": "房间协作产出"})
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await get_swarm_manager().spawn(
                task="房间协作任务", agent_id="member_a",
                origin="room_collab", room_id=pid, background=False)
        assert not result.get("rejected") and not result.get("error"), result
        row = get_agent_run_store().get_run_by_subagent(result["subagent_id"])
        assert row is not None, "蜂群 run 必须落台账"
        assert row.get("project_id") == pid, (
            f"房间发起的 run 台账行必须带项目标（room_id=project_id 等式），实得 {row.get('project_id')!r}")

    @pytest.mark.asyncio
    async def test_teamDispatchRunCarriesTeamTag(self, client):
        """S10 移交闭环：team_dispatch 派生的 run 台账行带 team_id（同通道落库）。"""
        from neurova.agent.swarm import get_swarm_manager
        from neurova.core.agent_run_store import get_agent_run_store

        agent = _fake_agent()
        agent.chat = AsyncMock(return_value={"text": "团队产出"})
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await get_swarm_manager().spawn(
                task="团队派活任务", agent_id="member_a", origin="team_dispatch",
                team_id="team_fixed1", team_role="leader",
                teamMemberOverride={"user_id": "member_a", "name": "成员A",
                                    "role": "leader", "prompt": ""},
                background=False)
        assert not result.get("rejected") and not result.get("error"), result
        row = get_agent_run_store().get_run_by_subagent(result["subagent_id"])
        assert row is not None
        assert row.get("team_id") == "team_fixed1", (
            f"团队派活的 run 台账行必须带 team_id（S10 移交），实得 {row.get('team_id')!r}")

    @pytest.mark.asyncio
    async def test_directDispatchWithProjectContextCarriesProjectTag(self, client):
        """入口一：主 agent 直发带项目上下文时同样打标（spawn 显式 project_id）。"""
        from neurova.agent.swarm import get_swarm_manager
        from neurova.core.agent_run_store import get_agent_run_store

        pid = client.project_id
        agent = _fake_agent()
        agent.chat = AsyncMock(return_value={"text": "直发产出"})
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await get_swarm_manager().spawn(
                task="带项目上下文的直发任务", agent_id="member_a",
                origin="chat", project_id=pid, background=False)
        assert not result.get("rejected") and not result.get("error"), result
        row = get_agent_run_store().get_run_by_subagent(result["subagent_id"])
        assert row is not None
        assert row.get("project_id") == pid, (
            f"直发带项目上下文的 run 必须打项目标，实得 {row.get('project_id')!r}")


class TestDossierAggregation:
    """② 档案读面：聚合 run/事件/候选/审批（+房间消息），读时 join 既有持久面。"""

    def test_dossierAggregatesRunsEventsCandidatesApprovals(self, client):
        from neurova.agent.swarm import get_swarm_manager
        from neurova.agent.swarm_event_log import appendRunEvent
        from neurova.security.audit_logger import AuditEventType, AuditSeverity, log_audit

        pid = client.project_id
        assert _seedTaggedRun(pid, subagentId="swarm_dos1", teamId="team_x"), "子任务必须落台账"
        appendRunEvent("swarm_dos1", "spawned",
                       {"task": "档案聚合任务", "origin": "room_collab", "depth": 1})
        candidate = get_swarm_manager()._candidates.submitCandidate(
            "swarm_dos1", "候选报告正文", ["doc-a"])
        # S8 审批审计：请求+决定成对（单源 log_audit，resource_id=run）
        for phase, action, severity in (("request", "swarm_approval_request", AuditSeverity.MEDIUM),
                                        ("decide", "swarm_approval_decide", AuditSeverity.MEDIUM)):
            log_audit(
                AuditEventType.APPROVAL, severity, user_id="u1" if phase == "decide" else "member_a",
                action=action,
                details={"phase": phase, "request_id": "req-1", "run_id": "swarm_dos1",
                         "agent_id": "member_a", "level": "L1", "effective_level": "L1",
                         "operation": "merge_candidate:x", "decision": "approve" if phase == "decide" else "pending",
                         "decided_by": "u1" if phase == "decide" else ""},
                resource_type="swarm_approval", resource_id="swarm_dos1",
            )
        client.roomStore.append(pid, "user", "u1", "开工：整理档案")

        resp = client.get(f"/api/v1/projects/{pid}/collaboration")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        # run 列表（台账按项目标）
        runRows = data["runs"]
        assert any(r["subagent_id"] == "swarm_dos1" and r["project_id"] == pid for r in runRows), runRows
        # 事件时间线（H-4 账本按 run 归属）
        assert any(e["subagent_id"] == "swarm_dos1" and e["type"] == "spawned" for e in data["events"]), data["events"]
        # 候选记录（S4 候选板）
        assert any(c["candidate_id"] == candidate.candidateId and c["run_id"] == "swarm_dos1"
                   for c in data["candidates"]), data["candidates"]
        # 审批审计（S8 单源查询，请求+决定成对）
        approvals = [a for a in data["approvals"] if a["request_id"] == "req-1"]
        assert len(approvals) == 1, data["approvals"]
        assert approvals[0]["status"] == "decided"
        assert approvals[0]["decision"] == "approve"
        # 房间消息（RoomStore，room_id=project_id；档案投影只出摘要字段）
        assert any(m["content_summary"] == "开工：整理档案" for m in data["room_messages"]), data["room_messages"]
        # 计数口径
        assert data["counts"]["runs"] == 1
        assert data["counts"]["candidates"] == 1

    def test_dossierProjectNotFound404(self, client):
        resp = client.get("/api/v1/projects/nope/collaboration")
        assert resp.status_code == 404


class TestDossierClosure:
    """③ 封卷：项目 status 转 archived 时自动从账本生成协作总结并留底。"""

    def test_archiveProjectGeneratesDossierSummary(self, client):
        pid = client.project_id
        assert _seedTaggedRun(pid, subagentId="swarm_close1")
        resp = client.put(f"/api/v1/projects/{pid}", json={"status": "archived"})
        assert resp.status_code == 200, resp.text

        resp = client.get(f"/api/v1/projects/{pid}/collaboration")
        assert resp.status_code == 200
        summary = resp.json()["data"].get("summary")
        assert summary is not None, "封卷必须生成协作总结"
        assert summary["runs_count"] == 1, summary

        # 留底：总结落在项目档案（metadata），重启可回读
        project = client.manager.get_project(pid)
        assert (project.metadata.get("collaborationSummary") or {}).get("runs_count") == 1

    def test_summarySurvivesReopen(self, client):
        """封卷总结是留底：项目恢复 active 后档案仍可读回总结。"""
        pid = client.project_id
        assert _seedTaggedRun(pid, subagentId="swarm_close2")
        client.put(f"/api/v1/projects/{pid}", json={"status": "archived"})
        client.put(f"/api/v1/projects/{pid}", json={"status": "active"})
        resp = client.get(f"/api/v1/projects/{pid}/collaboration")
        assert resp.status_code == 200
        assert resp.json()["data"].get("summary") is not None, "封卷总结必须留底可回读"


class TestDossierIsolation:
    """④ 无 project 标的 run 不串入档案。"""

    def test_untaggedRunStaysOutOfDossier(self, client):
        from neurova.core.agent_run_ledger import openSubagentRun

        pid = client.project_id
        assert _seedTaggedRun(pid, subagentId="swarm_in")
        # 无项目标的 run（普通聊天派生）：openSubagentRun 不传 projectId
        assert openSubagentRun(
            memberSessionId="member_out", subagentId="swarm_out",
            parentSessionId="parent_s1", userId="u1", agentId="member_a",
            task="无项目标任务"), "无标 run 也应正常落台账"

        resp = client.get(f"/api/v1/projects/{pid}/collaboration")
        assert resp.status_code == 200
        data = resp.json()["data"]
        runIds = {r["subagent_id"] for r in data["runs"]}
        assert "swarm_in" in runIds
        assert "swarm_out" not in runIds, f"无项目标的 run 不得串入档案：{runIds}"
        eventSids = {e["subagent_id"] for e in data["events"]}
        assert "swarm_out" not in eventSids, "事件时间线同样不得串入无标 run"

    def test_otherProjectRunStaysOut(self, client):
        pid = client.project_id
        other = client.manager.create_project(name="别的项目", owner_id="u1")
        assert _seedTaggedRun(pid, subagentId="swarm_mine")
        assert _seedTaggedRun(other.project_id, subagentId="swarm_theirs")

        resp = client.get(f"/api/v1/projects/{pid}/collaboration")
        runIds = {r["subagent_id"] for r in resp.json()["data"]["runs"]}
        assert "swarm_mine" in runIds and "swarm_theirs" not in runIds


class TestProjectStatsBackwardCompat:
    """统计口径进 get_project_stats：新增 runs_count，既有字段全保留。"""

    def test_statsKeepsLegacyFieldsAndAddsRunsCount(self, client):
        pid = client.project_id
        assert _seedTaggedRun(pid, subagentId="swarm_stats1")
        resp = client.get(f"/api/v1/projects/{pid}/stats")
        assert resp.status_code == 200
        stats = resp.json()
        for key in ("project_id", "teams_count", "tasks_count", "completed_tasks",
                    "active_tasks", "workflows_count"):
            assert key in stats, f"既有统计字段 {key} 必须保留（向后兼容）"
        assert stats["runs_count"] == 1, stats
