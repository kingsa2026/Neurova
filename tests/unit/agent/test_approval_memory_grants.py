# -*- coding: utf-8 -*-
"""D1 记忆式批准（审批 grant）+ 持久化投影 单元测试（先红后绿）。

覆盖（D1 卡规格）：
- session grant：同 run 同类动作第二次免批、不同动作不命中、run 终态后失效、
  不跨会话域外溢；
- team grant：跨 run 放行、撤销即失效、数据根 JSON 持久化 round-trip
  （tmp_path 注入 NEUROVA_DATA_DIR，模拟重启后仍可读回/撤销）；
- L2 红线：L2 动作即使有同前缀 L1 grant 也必须走人工（核心断言），
  acceptForSession/acceptAlways 拒绝创建 L2 grant；
- 只降不升：L1 grant 覆盖 L0 请求，L0 grant 不覆盖 L1 请求；
- 通配匹配边界："Bash:*" 命中 "Bash:run_x"，不命中 "Bashxx:run"/裸 "Bash"；
- 房间回灌路径回归：无 grant 时群主房间裁决照旧；命中 grant 的动作不再上房间墙；
- 投影化读面：projectRunApprovals / projectTeamGrants 的字段与可撤销标记。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent import approval_chain as ac
from neurova.agent.approval_chain import (
    acceptAlways,
    acceptForSession,
    actionMatchesPattern,
    getGrant,
    grantCoversLevel,
    handleRoomSwarmReply,
    listGrants,
    matchGrant,
    projectRunApprovals,
    projectTeamGrants,
    requestRunApproval,
    revokeGrant,
)
from neurova.agent.swarm import SubAgentRun, reset_swarm_manager
from neurova.security.approval_manager import ApprovalManager
from neurova.security.approval_relay import installApprovalRelay

TEAM_A = "team_alpha"
TEAM_B = "team_beta"
ROOM = "room_grant"
OWNER = "owner_u"
MEMBER = "member_u"


@pytest.fixture(autouse=True)
def grantIsolation(tmp_path, monkeypatch):
    """grant 台账按用例隔离：数据根指进 tmp_path + 清进程内缓存，跨用例零残留。"""
    reset_swarm_manager()
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "grant_root"))
    ac._grantCache = None
    ac._grantCachePath = ""
    yield
    ac._grantCache = None
    ac._grantCachePath = ""


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    """真 ApprovalManager（临时数据根）+ 中继；WAIT_S=0 让未命中 grant 的请求立即待审。"""
    monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "0")
    mgr = ApprovalManager(str(tmp_path / "approval_grants_ws"))
    assert installApprovalRelay(mgr) is True
    with patch("neurova.security.approval_manager.get_approval_manager", return_value=mgr):
        yield mgr


@pytest.fixture
def parentMail():
    box = MagicMock()
    with patch("neurova.agent.mailbox.get_agent_mailbox", return_value=box):
        yield box


# ── 房间回灌回归的既有构造方式（同 test_swarm_room_integration） ──


class _FakeRepo:
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
    store = ac  # 占位避免误用；真正 store 在下方构造
    from neurova.collaboration.room_store import RoomStore

    real = RoomStore(repo=_FakeRepo())
    monkeypatch.setattr("neurova.collaboration.room_store.get_room_store", lambda: real)
    return real


@pytest.fixture
def roomBus(monkeypatch):
    from neurova.collaboration.room_bus import RoomBus

    mgr = MagicMock()
    mgr.broadcast_event = AsyncMock(return_value=0)
    bus = RoomBus(manager=mgr)
    monkeypatch.setattr("neurova.collaboration.room_bus.get_room_bus", lambda: bus)
    return bus


@pytest.fixture
def roomProject(monkeypatch):
    """房间群主制度桩：OWNER 是群主，MEMBER 是普通成员。"""
    project = SimpleNamespace(
        project_id=ROOM, owner_id=OWNER,
        members={OWNER: {"role": "owner"}, MEMBER: {"role": "member"}},
    )
    manager = MagicMock()
    manager.get_project.return_value = project
    monkeypatch.setattr(
        "neurova.collaboration.collaboration_isolation.get_collaboration_manager",
        lambda: manager,
    )
    return project


def makeRun(**kw) -> SubAgentRun:
    defaults = dict(
        agent_id="child", agent_name="子代理", task="整理季度数据",
        session_id="parent-session", origin="chat",
        member_session_id="swarm_member_grant", team_id=TEAM_A,
    )
    defaults.update(kw)
    return SubAgentRun(**defaults)


def roomKinds(store, kind: str):
    return [r for r in store.history(ROOM) if (r.get("meta") or {}).get("kind") == kind]


# ── session grant：同 run 同类动作免再批 ──────────────────────────────


class TestSessionGrant:
    @pytest.mark.asyncio
    async def test_same_run_same_action_second_request_free(self, approvals, parentMail):
        run = makeRun()
        first = await requestRunApproval(run, "导出审计日志", reason="第一次", level="L1")
        assert first["approved"] is False and first["pending"] is True
        assert parentMail.push.call_count == 1, "未命中 grant 时走既有弹批流程"

        grant = acceptForSession(run, "导出审计日志", level="L1", granted_by=OWNER)
        assert grant["kind"] == "session"
        assert grant["level"] == "L1"
        assert grant["run_id"] == run.subagent_id
        assert grant["granted_by"] == OWNER

        second = await requestRunApproval(run, "导出审计日志", reason="第二次", level="L1")
        assert second["approved"] is True
        assert second["auto_approved"] is True
        assert second["pending"] is False
        assert second["decision_source"] == "memory_grant"
        assert second["grant_id"] == grant["grant_id"]
        assert parentMail.push.call_count == 1, "命中 grant 的同类动作不得再弹批"

        third = await requestRunApproval(run, "导出审计日志", reason="第三次", level="L1")
        assert third["approved"] is True and third["grant_id"] == grant["grant_id"]

    @pytest.mark.asyncio
    async def test_different_action_not_covered(self, approvals, parentMail):
        run = makeRun()
        acceptForSession(run, "导出审计日志", level="L1", granted_by=OWNER)
        other = await requestRunApproval(run, "批量外发邮件", reason="另一类动作", level="L1")
        assert other["approved"] is False and other["pending"] is True, "不同动作不得被 grant 放行"

    @pytest.mark.asyncio
    async def test_grant_expires_when_run_ends(self, approvals, parentMail):
        run = makeRun()
        grant = acceptForSession(run, "导出审计日志", level="L1", granted_by=OWNER)
        assert matchGrant(run, "导出审计日志", "L1") is not None

        run.status = "completed"  # run 终态 → session grant 失效
        assert matchGrant(run, "导出审计日志", "L1") is None
        again = await requestRunApproval(run, "导出审计日志", reason="终态后再请求", level="L1")
        assert again["approved"] is False and again["pending"] is True
        assert getGrant(grant["grant_id"]) is not None, "失效≠删除，记录仍可查（审计可追溯）"

    def test_grant_scoped_to_own_session(self, approvals):
        runA = makeRun(member_session_id="sess_a")
        runB = makeRun(member_session_id="sess_b")
        acceptForSession(runA, "导出审计日志", level="L1", granted_by=OWNER)
        assert matchGrant(runA, "导出审计日志", "L1") is not None
        assert matchGrant(runB, "导出审计日志", "L1") is None, "grant 不得跨会话域外溢"


# ── team grant：跨 run 放行、可撤销、持久化 ──────────────────────────


class TestTeamGrant:
    @pytest.mark.asyncio
    async def test_team_grant_covers_across_runs(self, approvals, parentMail):
        acceptAlways(TEAM_A, "Bash:*", level="L1", granted_by=OWNER)
        run1 = makeRun(member_session_id="sess_1")
        run2 = makeRun(member_session_id="sess_2", subagent_id=run1.subagent_id + "_2")
        ok1 = await requestRunApproval(run1, "Bash:run_x", reason="跨 run 第一单", level="L1")
        ok2 = await requestRunApproval(run2, "Bash:run_y", reason="跨 run 第二单", level="L1")
        assert ok1["approved"] is True and ok1["decision_source"] == "memory_grant"
        assert ok2["approved"] is True and ok2["decision_source"] == "memory_grant"

        outsider = makeRun(team_id=TEAM_B, member_session_id="sess_3")
        denied = await requestRunApproval(outsider, "Bash:run_z", reason="他队不受益", level="L1")
        assert denied["approved"] is False and denied["pending"] is True

    def test_revoke_disables_team_grant(self, approvals):
        run = makeRun()
        grant = acceptAlways(TEAM_A, "Bash:*", level="L1", granted_by=OWNER)
        assert matchGrant(run, "Bash:run_x", "L1") is not None
        assert revokeGrant(grant["grant_id"], OWNER) is True
        assert matchGrant(run, "Bash:run_x", "L1") is None, "撤销即失效"
        assert revokeGrant(grant["grant_id"], OWNER) is False, "重复撤销幂等失败"
        assert revokeGrant("grant_not_exist", OWNER) is False

    def test_persistence_round_trip(self, tmp_path):
        grant = acceptAlways(TEAM_A, "Bash:*", level="L1", granted_by=OWNER)
        path = tmp_path / "grant_root" / "team_approval_grants.json"
        assert path.exists(), "团队 grant 必须写穿到数据根 JSON"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert [g["grant_id"] for g in payload["grants"]] == [grant["grant_id"]]
        assert payload["grants"][0]["kind"] == "team"
        assert payload["grants"][0]["level"] == "L1"

        # 模拟进程重启：清进程内缓存后从数据根读回（读一次+写穿）
        ac._grantCache = None
        ac._grantCachePath = ""
        reloaded = getGrant(grant["grant_id"])
        assert reloaded is not None and reloaded["action"] == "Bash:*"

        assert revokeGrant(grant["grant_id"], OWNER) is True
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["grants"][0]["revoked"] is True
        assert payload["grants"][0]["revoked_by"] == OWNER

        ac._grantCache = None
        ac._grantCachePath = ""
        assert matchGrant(makeRun(), "Bash:run_x", "L1") is None, "重启后撤销态仍生效"

    def test_session_grants_not_persisted(self, tmp_path):
        acceptForSession(makeRun(), "导出审计日志", level="L1", granted_by=OWNER)
        acceptAlways(TEAM_A, "Bash:*", level="L1", granted_by=OWNER)
        path = tmp_path / "grant_root" / "team_approval_grants.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        kinds = {g["kind"] for g in payload["grants"]}
        assert kinds == {"team"}, "session grant 随 run 生命周期，不落持久化文件"

    def test_list_and_get(self, approvals):
        g1 = acceptAlways(TEAM_A, "Bash:*", level="L1", granted_by=OWNER)
        g2 = acceptAlways(TEAM_B, "DB:*", level="L0", granted_by=OWNER)
        acceptForSession(makeRun(), "导出审计日志", level="L1", granted_by=OWNER)
        assert {g["grant_id"] for g in listGrants()} >= {g1["grant_id"], g2["grant_id"]}
        # team_id 过滤会带上该团队 run 名下的 session grant（team_id 是其归属元数据）；
        # 团队授权管理面（projectTeamGrants）只看团队档
        teamARows = listGrants(team_id=TEAM_A)
        assert g1["grant_id"] in {g["grant_id"] for g in teamARows}
        assert g2["grant_id"] not in {g["grant_id"] for g in teamARows}
        assert {g["kind"] for g in teamARows} == {"team", "session"}
        assert {g["grant_id"] for g in projectTeamGrants(TEAM_A)} == {g1["grant_id"]}
        assert getGrant(g2["grant_id"])["action"] == "DB:*"
        assert getGrant("missing") is None


# ── L2 红线：永不记忆式放行 ──────────────────────────────────────────


class TestL2RedLine:
    def test_acceptors_refuse_l2(self, approvals):
        with pytest.raises(ValueError):
            acceptForSession(makeRun(), "删除生产数据库表", level="L2", granted_by=OWNER)
        with pytest.raises(ValueError):
            acceptAlways(TEAM_A, "删除生产数据库表", level="L2", granted_by=OWNER)

    def test_match_grant_never_covers_l2(self, approvals):
        acceptAlways(TEAM_A, "Bash:*", level="L1", granted_by=OWNER)
        run = makeRun()
        assert matchGrant(run, "Bash:wipe_db", "L2") is None
        assert grantCoversLevel("L1", "L2") is False
        assert grantCoversLevel("L2", "L2") is False

    @pytest.mark.asyncio
    async def test_l2_request_goes_human_despite_l1_grant(self, approvals, parentMail):
        """核心断言：同前缀 L1 grant 在手，L2 请求仍必须走人工。"""
        acceptAlways(TEAM_A, "Bash:*", level="L1", granted_by=OWNER)
        run = makeRun()
        verdict = await requestRunApproval(run, "Bash:wipe_db", reason="清库", level="L2")
        assert verdict["approved"] is False
        assert verdict["pending"] is True
        assert verdict.get("decision_source") != "memory_grant"
        assert parentMail.push.call_count == 1, "L2 必须照常弹批给父/房间"


# ── 只降不升：level_covered 语义 ─────────────────────────────────────


class TestLevelCoverage:
    def test_l1_grant_covers_l0_request(self, approvals):
        run = makeRun()
        acceptForSession(run, "导出审计日志", level="L1", granted_by=OWNER)
        assert grantCoversLevel("L1", "L0") is True
        assert matchGrant(run, "导出审计日志", "L0") is not None

    @pytest.mark.asyncio
    async def test_l0_grant_does_not_cover_l1_request(self, approvals, parentMail):
        run = makeRun()
        acceptForSession(run, "导出审计日志", level="L0", granted_by=OWNER)
        assert grantCoversLevel("L0", "L1") is False
        assert matchGrant(run, "导出审计日志", "L1") is None
        verdict = await requestRunApproval(run, "导出审计日志", reason="升档请求", level="L1")
        assert verdict["approved"] is False and verdict["pending"] is True


# ── 动作匹配：精确串 / "前缀:*" 通配边界 ────────────────────────────


class TestActionMatching:
    def test_exact_and_wildcard_boundaries(self):
        assert actionMatchesPattern("Bash:run_x", "Bash:run_x") is True
        assert actionMatchesPattern("Bash:run_x", "Bash:run_y") is False
        assert actionMatchesPattern("Bash:*", "Bash:run_x") is True
        assert actionMatchesPattern("Bash:*", "Bashxx:run") is False, "通配只认冒号边界"
        assert actionMatchesPattern("Bash:*", "Bash") is False
        assert actionMatchesPattern("Bash:*", "bash:run_x") is False, "动作匹配大小写敏感"
        assert actionMatchesPattern("", "Bash:run_x") is False
        assert actionMatchesPattern("Bash:*", "") is False

    @pytest.mark.asyncio
    async def test_wildcard_team_grant_end_to_end(self, approvals, parentMail):
        acceptAlways(TEAM_A, "Bash:*", level="L1", granted_by=OWNER)
        run = makeRun()
        ok = await requestRunApproval(run, "Bash:run_x", reason="通配命中", level="L1")
        assert ok["approved"] is True and ok["decision_source"] == "memory_grant"
        miss = await requestRunApproval(run, "Bashxx:run", reason="前缀越界", level="L1")
        assert miss["approved"] is False and miss["pending"] is True


# ── 房间回灌路径回归（既有语义不破坏） ───────────────────────────────


class TestRoomRegression:
    @pytest.mark.asyncio
    async def test_room_owner_reply_still_decides(
        self, approvals, parentMail, monkeypatch, roomStore, roomBus, roomProject,
    ):
        monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "5")
        run = makeRun(room_id=ROOM)
        task = asyncio.create_task(
            requestRunApproval(run, "外发统计数据", reason="季度报表外发", level="L1")
        )
        # 等审批卡真正上墙（异步投递有窗口期，轮询避免时序偶发）
        deadline = asyncio.get_event_loop().time() + 5
        while not roomKinds(roomStore, "swarm_approval") and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
        memberReply = handleRoomSwarmReply(ROOM, MEMBER, isAdmin=False, text="同意")
        assert memberReply["matched"] == "approval"
        assert memberReply.get("recorded") == "opinion", "普通成员只记议见"
        ownerReply = handleRoomSwarmReply(ROOM, OWNER, isAdmin=False, text="同意批准")
        assert ownerReply["matched"] == "approval"
        assert ownerReply["decision_result"]["success"] is True
        result = await task
        assert result["approved"] is True
        assert result["decided_by"] == OWNER
        assert roomKinds(roomStore, "swarm_approval"), "无 grant 时审批卡照常上墙"

    @pytest.mark.asyncio
    async def test_granted_action_does_not_spam_room(
        self, approvals, parentMail, roomStore, roomBus,
    ):
        run = makeRun(room_id=ROOM)
        acceptAlways(TEAM_A, "导出审计日志", level="L1", granted_by=OWNER)
        result = await requestRunApproval(run, "导出审计日志", reason="已预授权", level="L1")
        assert result["approved"] is True and result["decision_source"] == "memory_grant"
        assert roomKinds(roomStore, "swarm_approval") == [], "命中 grant 的动作不再上房间审批墙"


# ── 投影化读面 ───────────────────────────────────────────────────────


class TestProjection:
    @pytest.mark.asyncio
    async def test_project_run_approvals_shape(self, approvals, parentMail):
        run = makeRun()
        await requestRunApproval(run, "读取只读配置", reason="低危", level="L0")
        grant = acceptForSession(run, "导出审计日志", level="L1", granted_by=OWNER)
        await requestRunApproval(run, "导出审计日志", reason="预授权", level="L1")
        await requestRunApproval(run, "批量外发邮件", reason="待审", level="L1")

        rows = projectRunApprovals(run)
        assert len(rows) == 3
        byAction = {r["action"]: r for r in rows}
        l0 = byAction["读取只读配置"]
        assert l0["effective_level"] == "L0" and l0["status"] == "approved"
        assert l0["decided_by"].startswith("auto_rule:")
        assert l0["decision_source"] == "chain" and l0["grant_id"] == ""
        granted = byAction["导出审计日志"]
        assert granted["status"] == "approved"
        assert granted["decision_source"] == "memory_grant"
        assert granted["grant_id"] == grant["grant_id"]
        assert granted["requested_at"] > 0
        pending = byAction["批量外发邮件"]
        assert pending["status"] == "pending" and pending["decided_by"] == ""

    def test_project_team_grants_revocable_flag(self, approvals):
        g1 = acceptAlways(TEAM_A, "Bash:*", level="L1", granted_by=OWNER)
        g2 = acceptAlways(TEAM_A, "DB:*", level="L0", granted_by=OWNER)
        revokeGrant(g2["grant_id"], OWNER)
        rows = projectTeamGrants(TEAM_A)
        assert len(rows) == 2
        flags = {r["grant_id"]: r for r in rows}
        assert flags[g1["grant_id"]]["revocable"] is True
        assert flags[g1["grant_id"]]["revoked"] is False
        assert flags[g2["grant_id"]]["revocable"] is False, "已撤销的 grant 不可再撤销"
        assert flags[g2["grant_id"]]["revoked_by"] == OWNER
        assert projectTeamGrants(TEAM_B) == []
