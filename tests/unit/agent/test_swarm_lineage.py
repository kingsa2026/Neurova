# -*- coding: utf-8 -*-
"""F5 谱系归因 + F2 接线（线丁，设计文档 §3.5）单元测试。

覆盖：
- spawn 后 run 事件 lineage 含 tenant_id/team_id/agent_path/depth；
- 内存两条父子 run 直接 _logRunEvent，子事件 lineage.agent_path == [父id, 子id]；
- _make_emitter 的 emitter 触发后账本出现 member_chunk（带 length、seq 递增，
  正文不进账本）；
- SwarmManager.runFrames 读面往返（frame_log → 管理器统一入口，游标回放）；
- member 内递归派生：子 run.parent_subagent_id 取自当前上下文绑定的父 id，
  父 run 不在内存时 agent_path 仍不断链。
数据根隔离沿用本仓会话级 NEUROVA_DATA_DIR 兜底（tests/conftest.py 导入期生效），
与 test_swarm_event_log.py 现行做法一致。
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import (
    SubAgentRun,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.agent.swarm_event_log import readRunEvents


def make_agent(reply="任务完成报告"):
    agent = MagicMock()
    agent.config.name = "子Agent"
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


def patchTenant(monkeypatch, tenant):
    """把发起者租户钉到指定值（与 test_swarm_external_member 同法）。"""
    from neurova.core import identity_context

    monkeypatch.setattr(identity_context, "get_request_user_id", lambda: "user-a")
    import neurova.auth.user_group_model as groups

    monkeypatch.setattr(groups, "resolveUserDepartment", lambda user: {"tenant_id": tenant})


class TestSpawnLineage:
    @pytest.mark.asyncio
    async def test_spawnEventCarriesLineage(self, swarm, monkeypatch):
        """① spawn 后 run 事件 lineage 含 tenant_id/team_id/agent_path。"""
        patchTenant(monkeypatch, "tenant-d1")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_agent()):
            result = await swarm.spawn(
                task="子任务内容", agent_id="researcher",
                team_id="team-d1",
                teamMemberOverride={"user_id": "u-1", "name": "成员甲", "role": "coder"},
            )
        sid = result["subagent_id"]
        events = readRunEvents(sid)
        assert events, "spawn 后事件账本应有记录"
        spawned = events[0]
        assert spawned["type"] == "spawned"
        lineage = spawned["lineage"]
        assert lineage["tenant_id"] == "tenant-d1"
        assert lineage["team_id"] == "team-d1"
        assert lineage["agent_path"] == [sid]
        assert lineage["parent_subagent_id"] == ""
        assert lineage["depth"] == 1
        # 台账与事件同源：run.tenant_id 是 spawn 时刻读数（openSubagentRun 吃它）
        assert swarm._runs[sid].tenant_id == "tenant-d1"
        # 终态事件同样携带谱系
        assert events[-1]["type"] == "terminal"
        assert events[-1]["lineage"]["tenant_id"] == "tenant-d1"


class TestLineageAgentPath:
    def test_childEventAgentPathIsParentThenChild(self, swarm):
        """② 内存父子 run 直接落账：子事件 agent_path == [父id, 子id]。"""
        parent = SubAgentRun(subagent_id="swarm_lin_par", tenant_id="t-d2",
                             team_id="team-d2", depth=1)
        child = SubAgentRun(subagent_id="swarm_lin_child",
                            parent_subagent_id="swarm_lin_par", depth=2)
        with swarm._lock:
            swarm._runs[parent.subagent_id] = parent
            swarm._runs[child.subagent_id] = child
        swarm._logRunEvent(child, "started", {"status": "running"})
        events = readRunEvents("swarm_lin_child")
        assert events and events[0]["type"] == "started"
        lineage = events[0]["lineage"]
        assert lineage["agent_path"] == ["swarm_lin_par", "swarm_lin_child"]
        assert lineage["parent_subagent_id"] == "swarm_lin_par"
        assert lineage["depth"] == 2
        # 根 run 自身事件：agent_path 只含自己，parent 为空串
        swarm._logRunEvent(parent, "started", {"status": "running"})
        parentEvents = readRunEvents("swarm_lin_par")
        assert parentEvents[0]["lineage"]["agent_path"] == ["swarm_lin_par"]
        assert parentEvents[0]["lineage"]["parent_subagent_id"] == ""

    def test_agentPathSurvivesEvictedParent(self, swarm):
        """父 run 已被逐出内存：id 仍入路径（谱系不断链），限深内不死循环。"""
        child = SubAgentRun(subagent_id="swarm_lin_child2",
                            parent_subagent_id="swarm_lin_gone", depth=2)
        with swarm._lock:
            swarm._runs[child.subagent_id] = child
        swarm._logRunEvent(child, "started", {})
        lineage = readRunEvents("swarm_lin_child2")[0]["lineage"]
        assert lineage["agent_path"] == ["swarm_lin_gone", "swarm_lin_child2"]


class TestEmitterMirror:
    def test_emitterChunkLandsInLedgerWithSeq(self, swarm):
        """③ emitter 触发后账本出现 member_chunk（带 length、seq 递增）。"""
        run = SubAgentRun(subagent_id="swarm_emit1", tenant_id="t-d3")
        with swarm._lock:
            swarm._runs[run.subagent_id] = run
        buffer = []
        emitter = swarm._make_emitter(run, buffer)
        emitter("content", "你好")
        emitter("reasoning", "思考中")
        events = readRunEvents("swarm_emit1")
        chunks = [e for e in events if e["type"] == "member_chunk"]
        assert len(chunks) == 2
        assert chunks[0]["payload"] == {"chunk_type": "content", "length": 2}
        assert chunks[1]["payload"] == {"chunk_type": "reasoning", "length": 3}
        seqs = [e["seq"] for e in chunks]
        assert seqs == sorted(seqs), "账本文件序与 seq 序一致"
        assert len(set(seqs)) == 2, "seq 不得重复"
        # H-4 纪律：只记元数据不记正文
        assert "你好" not in json.dumps(chunks, ensure_ascii=False)
        assert "思考中" not in json.dumps(chunks, ensure_ascii=False)
        # lineage 自动携带
        assert chunks[0]["lineage"]["agent_path"] == ["swarm_emit1"]
        # contentBuffer 行为不变（失败交接原料照常累积）
        assert buffer == ["你好"]


class TestRunFrames:
    def test_runFramesRoundtripWithCursor(self, swarm):
        """④ runFrames 读面往返：全量读取 + afterSeq 游标回放。"""
        from neurova.agent.neuacp.frame_log import appendFrame

        lineage = {"tenant_id": "t-d4", "agent_path": ["swarm_fr1"]}
        first = appendFrame("swarm_fr1", "out",
                            {"jsonrpc": "2.0", "method": "initialize"}, lineage=lineage)
        second = appendFrame("swarm_fr1", "in", {"jsonrpc": "2.0", "id": 1, "result": {}})
        assert second > first
        view = swarm.runFrames("swarm_fr1")
        assert view["subagent_id"] == "swarm_fr1"
        assert view["count"] == 2
        assert view["frames"][0]["direction"] == "out"
        assert view["frames"][0]["frame"]["method"] == "initialize"
        assert view["frames"][0]["lineage"] == lineage
        assert view["frames"][1]["direction"] == "in"
        tail = swarm.runFrames("swarm_fr1", afterSeq=first)
        assert tail["count"] == 1
        assert tail["frames"][0]["seq"] == second

    def test_runFramesUnknownRunReturnsEmpty(self, swarm):
        view = swarm.runFrames("swarm_never_frames")
        assert view == {"subagent_id": "swarm_never_frames", "count": 0, "frames": []}


class TestParentSubagentId:
    @pytest.mark.asyncio
    async def test_memberRecursiveSpawnCarriesParentId(self, swarm, monkeypatch):
        """⑤ member 内递归派生：子 run.parent_subagent_id 来自上下文绑定。"""
        from neurova.agent.swarm import resetCurrentSubagentId, setCurrentSubagentId

        patchTenant(monkeypatch, "default")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_agent()):
            token = setCurrentSubagentId("swarm_anchor_parent")
            try:
                result = await swarm.spawn(task="递归子任务", agent_id="researcher")
            finally:
                resetCurrentSubagentId(token)
        sid = result["subagent_id"]
        run = swarm._runs[sid]
        assert run.parent_subagent_id == "swarm_anchor_parent"
        lineage = readRunEvents(sid)[0]["lineage"]
        assert lineage["parent_subagent_id"] == "swarm_anchor_parent"
        # 锚点父 run 不在内存——agent_path 仍为 [父id, 子id]
        assert lineage["agent_path"] == ["swarm_anchor_parent", sid]

    @pytest.mark.asyncio
    async def test_topLevelSpawnHasEmptyParent(self, swarm, monkeypatch):
        """顶层派生（上下文未绑定父 id）：parent_subagent_id 为空串。"""
        patchTenant(monkeypatch, "default")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_agent()):
            result = await swarm.spawn(task="顶层子任务", agent_id="researcher")
        sid = result["subagent_id"]
        assert swarm._runs[sid].parent_subagent_id == ""
        assert readRunEvents(sid)[0]["lineage"]["parent_subagent_id"] == ""


class TestTransitionRunLineage:
    def test_statusChangedCarriesLineage(self, swarm):
        """⑥ transitionRun（模块级）落的 status_changed 与其余 run 事件同谱系。

        红线证据（live-verify 实测）：修前 status_changed 无 lineage 键，
        事件账本里出现"有的带谱系、有的不带"的分叉。
        """
        from neurova.agent.swarm import SUBAGENT_RUNNING, transitionRun

        run = SubAgentRun(subagent_id="swarm_lineage_t1", agent_id="researcher",
                          task="迁移谱系子任务", tenant_id="tenant-d1", team_id="team-d1")
        swarm._runs[run.subagent_id] = run
        transitionRun(run, SUBAGENT_RUNNING, cause="member_started")
        status_events = [e for e in readRunEvents(run.subagent_id) if e["type"] == "status_changed"]
        assert status_events, "迁移应落 status_changed 事件"
        lineage = status_events[-1]["lineage"]
        assert lineage["tenant_id"] == "tenant-d1"
        assert lineage["team_id"] == "team-d1"
        assert lineage["agent_path"] == [run.subagent_id]
