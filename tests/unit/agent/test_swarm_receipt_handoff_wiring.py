# -*- coding: utf-8 -*-
"""批一接线集成测试：A3 命令回执（dispatchTeam/cancelRun）+ B2 续跑交接工件 + C5 续跑能力门。

- A3：同 command_id 重试按回执重放（不重复 spawn/取消），跨会话复用同 ID 报冲突；
- B2：resumeFinishedRun 的旧产出经 ContextHandoff 工件 inline 投递（登记/事件留痕），
  替代旧 report[:4000] 裸截断；
- C5：外部成员续跑由目录能力档决策——既无 session_reuse 也无 resume 的执行体诚实拒绝。
"""
import asyncio
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

import neurova.agent.swarm as swarm_module
from neurova.agent.swarm import (
    SUBAGENT_COMPLETED,
    SubAgentRun,
    get_swarm_manager,
    reset_swarm_manager,
)


class ScriptedAgent:
    """假子 Agent：立即/延时返回固定报告。"""

    def __init__(self, name="成员A", reply="团队产出完成", delay=0.0):
        self.config = type("Cfg", (), {"name": name})()
        from unittest.mock import AsyncMock as _AM

        self._reply = reply
        self._delay = delay
        self.chat = _AM(side_effect=self._chat)

    async def _chat(self, task, **kwargs):
        await asyncio.sleep(self._delay)
        return {"text": self._reply}


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


@pytest.fixture
def receipt_conn(tmp_path, monkeypatch):
    """回执库隔离到临时文件，避免污染真实数据根。"""
    conn = sqlite3.connect(str(tmp_path / "command_receipt.db"), check_same_thread=False)
    from neurova.core.command_receipt import ensureReceiptStore

    ensureReceiptStore(conn)
    monkeypatch.setattr(swarm_module, "_receiptConnection", lambda: conn)
    return conn


def _roster(members):
    return {
        "name": "测试团队",
        "members_detail": members,
    }


class TestDispatchTeamReceipt:
    @pytest.mark.asyncio
    async def test_same_command_id_retries_spawn_once(self, swarm, receipt_conn, monkeypatch):
        monkeypatch.setattr(
            "neurova.api.endpoints.teams_api.getTeamRoster",
            lambda tid: _roster([
                {"user_id": "agent-a", "name": "甲", "role": "coder", "prompt": "实现"},
            ]),
            raising=False,
        )
        agent = ScriptedAgent(name="甲")
        monkeypatch.setattr(
            "neurova.api.endpoints.get_agent_instance", lambda aid, **kw: agent
        )

        first = await swarm.dispatchTeam(
            teamId="t1", task="做一个功能", session_id="sess-1",
            background=False, command_id="cmd-d1",
        )
        runs_after_first = len(swarm._runs)
        second = await swarm.dispatchTeam(
            teamId="t1", task="做一个功能", session_id="sess-1",
            background=False, command_id="cmd-d1",
        )
        assert first.get("success") is True, first
        assert second.get("replayed") is True, second
        assert second.get("subagent_ids") == first.get("subagent_ids")
        assert len(swarm._runs) == runs_after_first, "重试不得新增 run"

    @pytest.mark.asyncio
    async def test_cross_session_same_id_rejected(self, swarm, receipt_conn, monkeypatch):
        monkeypatch.setattr(
            "neurova.api.endpoints.teams_api.getTeamRoster",
            lambda tid: _roster([
                {"user_id": "agent-a", "name": "甲", "role": "coder", "prompt": "实现"},
            ]),
            raising=False,
        )
        agent = ScriptedAgent(name="甲")
        monkeypatch.setattr(
            "neurova.api.endpoints.get_agent_instance", lambda aid, **kw: agent
        )
        ok = await swarm.dispatchTeam(
            teamId="t1", task="任务一", session_id="sess-1",
            background=False, command_id="cmd-shared",
        )
        assert ok.get("success") is True
        conflict = await swarm.dispatchTeam(
            teamId="t1", task="任务二", session_id="sess-2",
            background=False, command_id="cmd-shared",
        )
        assert conflict.get("rejection") == "COMMAND_ID_CONFLICT", conflict


class TestCancelRunReceipt:
    @pytest.mark.asyncio
    async def test_cancel_same_command_id_replays(self, swarm, receipt_conn, monkeypatch):
        agent = ScriptedAgent(name="长跑", reply="不会到这", delay=5.0)
        monkeypatch.setattr(
            "neurova.api.endpoints.get_agent_instance", lambda aid, **kw: agent
        )
        spawned = await swarm.spawn(
            task="长任务", agent_id="agent-slow", session_id="sess-c",
            background=True,
        )
        sid = spawned.get("subagent_id")
        assert sid, spawned
        first = swarm.cancelRun(sid, reason="测试叫停", command_id="cmd-cancel-1")
        assert first.get("success") is True, first
        second = swarm.cancelRun(sid, reason="测试叫停", command_id="cmd-cancel-1")
        assert second.get("replayed") is True, second


def _finishedRun(sid="run-old", team_id="", agent_id="agent-a", report="旧产出 A"):
    return SubAgentRun(
        subagent_id=sid, depth=1, agent_id=agent_id, agent_name="成员A",
        task="旧任务书内容", origin="chat", session_id="sess-old",
        subagent_type="general", team_id=team_id, report=report,
        member_session_id="msess-old", status=SUBAGENT_COMPLETED,
    )


def _spawnTask(spawnMock) -> str:
    """resumeFinishedRun 以位置参数传 task（spawn(task, agent_id=...)）。"""
    args = spawnMock.await_args.args
    if args:
        return str(args[0] or "")
    return str((spawnMock.await_args.kwargs or {}).get("task") or "")


class TestResumeHandoff:
    @pytest.mark.asyncio
    async def test_resume_builds_handoff_artifact(self, swarm, monkeypatch):
        old = _finishedRun(report="上一段产出的结论：方案甲可行，已验证三处。")
        with swarm._lock:
            swarm._runs[old.subagent_id] = old
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new", "status": "running"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续做下一步", session_id="sess-new")
        assert spawnMock.await_count == 1
        kwargs = spawnMock.await_args.kwargs
        newTask = _spawnTask(spawnMock)
        assert "上下文交接" in newTask, "续跑任务须带交接前缀"
        assert "方案甲可行" in newTask, "旧产出须完整进入交接（预算内不截断）"
        assert "继续做下一步" in newTask
        assert result.get("success") is not False
        # 事件留痕：context_transfer 入 H-4 账本
        events = swarm.runEvents(old.subagent_id).get("events", [])
        types = [e.get("type") for e in events]
        assert "context_transfer" in types, types

    @pytest.mark.asyncio
    async def test_resume_without_report_skips_handoff(self, swarm, monkeypatch):
        old = _finishedRun(report="")
        with swarm._lock:
            swarm._runs[old.subagent_id] = old
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)
        await swarm.resumeFinishedRun(old.subagent_id, "直接继续")
        newTask = _spawnTask(spawnMock)
        assert "上下文交接" not in newTask

    @pytest.mark.asyncio
    async def test_resume_budget_failure_is_honest(self, swarm, monkeypatch):
        old = _finishedRun(report="超长产出" * 100)
        with swarm._lock:
            swarm._runs[old.subagent_id] = old
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)
        # 预算压到下限以下 → computeHandoffBudget 抛错 → 诚实降级（不静默截断）
        monkeypatch.setattr(swarm_module, "_handoffTokenCap", lambda: 0)
        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")
        assert result.get("success") is False, result
        assert "上下文交接工件构建失败" in str(result.get("error", ""))
        assert spawnMock.await_count == 0, "交接失败时不得静默继续"
        events = swarm.runEvents(old.subagent_id).get("events", [])
        assert any(e.get("type") == "context_transfer_failed" for e in events)


class TestResumeCapabilityGate:
    @pytest.mark.asyncio
    async def test_external_member_without_resume_caps_rejected(self, swarm, monkeypatch):
        # 未知工具 → 目录保守档（无 session_reuse/resume）→ C5 决策 reject
        old = _finishedRun(sid="run-ext", team_id="t-ext", agent_id="ext-1",
                           report="外部成员产出")
        with swarm._lock:
            swarm._runs[old.subagent_id] = old
        monkeypatch.setattr(
            "neurova.api.endpoints.teams_api.getTeamRoster",
            lambda tid: _roster([
                {"user_id": "ext-1", "name": "外部甲", "role": "member",
                 "executor": {"kind": "acp", "tool": "unknown-agent-x",
                              "command": ["nope"], "cwd": "."}},
            ]),
            raising=False,
        )
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)
        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")
        assert result.get("success") is False, result
        assert "不支持续跑" in str(result.get("error", ""))
        assert spawnMock.await_count == 0
        events = swarm.runEvents(old.subagent_id).get("events", [])
        assert any(
            e.get("type") == "resume_decision" and e.get("payload", {}).get("decision") == "reject"
            for e in events
        )

    @pytest.mark.asyncio
    async def test_external_member_with_resume_caps_passes(self, swarm, monkeypatch):
        # zcode plugin 家 resume=True → 决策 restart_and_resume → 放行走既有续跑链
        old = _finishedRun(sid="run-ext2", team_id="t-ext2", agent_id="ext-2",
                           report="外部成员产出")
        with swarm._lock:
            swarm._runs[old.subagent_id] = old
        monkeypatch.setattr(
            "neurova.api.endpoints.teams_api.getTeamRoster",
            lambda tid: _roster([
                {"user_id": "ext-2", "name": "外部乙", "role": "member",
                 "executor": {"kind": "plugin", "tool": "zcode",
                              "command": ["zcode"], "cwd": "."}},
            ]),
            raising=False,
        )
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)
        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")
        assert spawnMock.await_count == 1, result
        events = swarm.runEvents(old.subagent_id).get("events", [])
        assert any(
            e.get("type") == "resume_decision"
            and e.get("payload", {}).get("decision") == "restart_and_resume"
            for e in events
        )
