# -*- coding: utf-8 -*-
"""P3-2 蜂群 span 级 trace 单元测试（评测报告 G-12）。

覆盖：
- spawn 捕获父请求 trace_id（parent_trace_id），member 开设自己的轨迹 trace；
- span 挂到轨迹根 span（parent_span_id 非空）；
- run 终态收 span：失败 run 以 failed 收（成功 completed 由 spy 记录面验证）；
- 台账行写 trace_id（agent_runs.trace_id，v4 迁移列）——台账与 span 关联；
- to_dict / uplink 信封携带 trace_id + parent_trace_id（贯穿回流的读面）；
- kill-switch NEUROVA_SWARM_TRACE=off：不设轨迹、trace_id 留空（fail-open）。
"""

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
from neurova.core.agent_run_store import AgentRunStore
from neurova.core.trace_context import clear_trace_id, set_trace_id
from neurova.core.trace_recorder import get_trajectory_recorder


def make_agent(reply="任务完成报告"):
    agent = MagicMock()
    agent.config.name = "子Agent"
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


@pytest.fixture
def recorderSpy(monkeypatch, tmp_path):
    """给轨迹单例挂 spy（记录调用），并把落盘目录指到临时目录（不污染数据根）。"""
    rec = get_trajectory_recorder()
    monkeypatch.setattr(rec, "_storage_dir", tmp_path / "trajectories")
    calls = {}

    def wrap(name):
        orig = getattr(rec, name)

        def _spy(*args, **kwargs):
            calls.setdefault(name, []).append((args, kwargs))
            return orig(*args, **kwargs)

        monkeypatch.setattr(rec, name, _spy)

    for name in ("start_trace", "end_trace", "start_span", "end_span", "record_event"):
        wrap(name)
    return calls


async def _spawn(swarm, agent, task="子任务内容"):
    with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
        return await swarm.spawn(task=task, agent_id="researcher")


class TestSpanWiring:
    @pytest.mark.asyncio
    async def test_spawn_captures_parent_trace_and_member_trace(self, swarm, recorderSpy):
        token = set_trace_id("tr-parent-1")
        try:
            result = await _spawn(swarm, make_agent())
        finally:
            clear_trace_id()
            set_trace_id(token)  # 复位到测试前状态
            clear_trace_id()
        run = swarm.status(result["subagent_id"])
        assert run["parent_trace_id"] == "tr-parent-1"
        assert run["trace_id"] and run["trace_id"] != "tr-parent-1", \
            "member 应开设自己的轨迹，且保留父链路 id"
        assert recorderSpy["start_trace"], "member 执行期必须 start_trace"

    @pytest.mark.asyncio
    async def test_member_span_chained_to_trace_root(self, swarm, recorderSpy):
        await _spawn(swarm, make_agent())
        spanCalls = recorderSpy["start_span"]
        assert spanCalls, "必须开 member span"
        args, kwargs = spanCalls[0]
        assert args[1] == "swarm_member_run"
        assert kwargs.get("parent_span_id"), "member span 应挂到轨迹根 span（链路成树）"

    @pytest.mark.asyncio
    async def test_failed_run_ends_span_failed(self, swarm, recorderSpy):
        agent = make_agent()
        agent.chat = AsyncMock(return_value={"text": "[LLM Error] 上游崩溃"})
        result = await _spawn(swarm, agent)
        assert result["status"] == "failed"
        assert recorderSpy["end_span"], "失败 run 也必须收 span（不留悬挂 span）"
        _args, kwargs = recorderSpy["end_span"][-1]
        assert kwargs.get("status") == "failed"
        assert recorderSpy["end_trace"], "轨迹必须收口（自动落盘可查询）"

    @pytest.mark.asyncio
    async def test_terminal_event_recorded(self, swarm, recorderSpy):
        await _spawn(swarm, make_agent())
        events = []
        for args, kwargs in recorderSpy["record_event"]:
            data = args[2] if len(args) >= 3 else kwargs.get("data")
            if isinstance(data, dict):
                events.append(data.get("event"))
        assert "subagent_started" in events
        assert "subagent_terminal" in events


class TestLedgerLink:
    @pytest.mark.asyncio
    async def test_ledger_row_carries_trace_id(self, swarm, tmp_path, monkeypatch):
        db = tmp_path / "runs.db"
        store = AgentRunStore(db)
        try:
            monkeypatch.setattr("neurova.core.agent_run_store.run_gate_enabled", lambda: True)
            monkeypatch.setattr("neurova.core.agent_run_store.get_agent_run_store", lambda: store)
            result = await _spawn(swarm, make_agent())
            run = swarm.status(result["subagent_id"])
            assert run["trace_id"]
            with sqlite3.connect(db) as conn:
                row = conn.execute(
                    "SELECT trace_id FROM agent_runs WHERE subagent_id=?",
                    (result["subagent_id"],),
                ).fetchone()
            assert row is not None, "台账里找不到这条子任务行"
            assert row[0] == run["trace_id"], "台账行必须以 trace_id 与 span 树关联"
        finally:
            store.close()

    def test_v4_migration_adds_trace_id_column(self, tmp_path):
        store = AgentRunStore(tmp_path / "runs.db")
        try:
            with sqlite3.connect(tmp_path / "runs.db") as conn:
                columns = {r[1] for r in conn.execute("PRAGMA table_info(agent_runs)")}
            assert "trace_id" in columns
        finally:
            store.close()


class TestSwitchAndProjection:
    @pytest.mark.asyncio
    async def test_kill_switch_off_disables_trace(self, swarm, recorderSpy, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_TRACE", "off")
        result = await _spawn(swarm, make_agent())
        assert not recorderSpy.get("start_trace"), "kill-switch 关闭时不得开轨迹"
        assert swarm.status(result["subagent_id"])["trace_id"] == ""

    @pytest.mark.asyncio
    async def test_uplink_envelope_carries_trace_ids(self, swarm):
        token = set_trace_id("tr-parent-2")
        try:
            result = await _spawn(swarm, make_agent())
        finally:
            clear_trace_id()
            set_trace_id(token)
            clear_trace_id()
        runObj = swarm._runs[result["subagent_id"]]
        envelope = swarm._uplinkEnvelope(runObj)
        assert envelope["trace_id"] == runObj.trace_id
        assert envelope["parent_trace_id"] == "tr-parent-2"
