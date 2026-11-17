# -*- coding: utf-8 -*-
"""S1 移交：swarm 轨迹生产者——工具执行路径写 span 工具事件。

背景（波1 S1 执行记录）：benchmark 侧 `_toolFactsFromTrace` 已就位，但执行链
不产 span 工具事件，swarm 轨迹暂读 0。本批在 ToolExecutor 执行咽喉落
`tool_call_start` / `tool_call_end` / `tool_call_error` 事件（P3-2 span 轨迹，
不进 H-4 事件账本）。

契约：
- swarm run 结束后，从 result["trace_id"] 聚合出 toolCalls > 0；
- 事件带工具名/耗时/成败；无活动轨迹时记录是 no-op（fail-open）。
"""

from unittest.mock import MagicMock, patch

import pytest

from neurova.core.trace_context import clear_trace_id
from neurova.core.trace_recorder import get_trajectory_recorder
from neurova.tool_executor import ToolExecutor


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    """轨迹单例指向临时目录（不污染数据根），用后清理活动轨迹。"""
    rec = get_trajectory_recorder()
    monkeypatch.setattr(rec, "_storage_dir", tmp_path / "trajectories")
    yield rec
    # 清空活动注册表，防止跨测试串号（单例进程级共享）
    rec._active_traces.clear()
    rec._active_spans.clear()
    clear_trace_id()


def _executor():
    agent = MagicMock()
    agent.current_session_id = "sess-traj"
    agent.workspace_path = ""
    return ToolExecutor(agent)


class TestToolSpanProduction:
    @pytest.mark.asyncio
    async def test_tool_call_records_span_events(self, recorder):
        """执行咽喉必须落 tool_call_start + tool_call_end（含工具名/耗时/成败）。"""
        ex = _executor()
        trace_id = recorder.start_trace("sess-traj", "a1", "u1")
        try:
            result = await ex._execute_single_tool("get_datetime", {})
            assert isinstance(result, dict)
        finally:
            recorder.end_trace(trace_id)

        trace = recorder.load_trace(trace_id)
        assert trace is not None
        starts, ends = [], []
        for span in trace.spans.values():
            for ev in span.events:
                etype = getattr(ev.event_type, "value", str(ev.event_type))
                if etype == "tool_call_start":
                    starts.append(ev)
                elif etype in ("tool_call_end", "tool_call_error"):
                    ends.append(ev)
        assert len(starts) >= 1, "工具执行必须落 tool_call_start 事件"
        assert starts[0].data.get("tool_name") == "get_datetime"
        assert len(ends) >= 1, "工具执行必须落 end/error 事件"
        end_ev = ends[0]
        assert end_ev.data.get("tool_name") == "get_datetime"
        assert "success" in end_ev.data and "execution_time_ms" in end_ev.data, \
            "end 事件必须带成败与耗时（benchmark 轨迹判据数据源）"

    @pytest.mark.asyncio
    async def test_failed_tool_records_error_event(self, recorder):
        """工具失败 → tool_call_error 事件（success=False）。"""
        ex = _executor()
        trace_id = recorder.start_trace("sess-traj", "a1", "u1")
        try:
            await ex._execute_single_tool("no_such_tool_xyz", {})
        finally:
            recorder.end_trace(trace_id)

        trace = recorder.load_trace(trace_id)
        etypes = []
        for span in trace.spans.values():
            for ev in span.events:
                etypes.append(getattr(ev.event_type, "value", str(ev.event_type)))
        assert "tool_call_start" in etypes
        assert "tool_call_error" in etypes, "失败执行必须落 tool_call_error"

    @pytest.mark.asyncio
    async def test_no_active_trace_is_noop(self, recorder):
        """无活动轨迹：工具执行照常成功，不抛（轨迹是增强面）。"""
        clear_trace_id()
        ex = _executor()
        result = await ex._execute_single_tool("get_datetime", {})
        assert isinstance(result, dict)


class TestSwarmTrajectoryAggregation:
    @pytest.mark.asyncio
    async def test_swarm_run_trace_aggregates_tool_calls(self, recorder):
        """swarm run 后：从 result["trace_id"] 聚合出 toolCalls > 0（S1 验收判据）。"""
        from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
        from neurova.benchmark.multi_agent.runner import _toolFactsFromTrace

        reset_swarm_manager()
        swarm = get_swarm_manager()
        agent = MagicMock()
        agent.config.name = "子Agent"
        memberExecutor = _executor()

        async def _chatWithTool(text, **kwargs):
            # member 管线内真实走一次工具执行咽喉（轨迹 ContextVar 在本任务内有效）
            await memberExecutor.execute_tool("get_datetime", {})
            return {"text": "任务完成报告"}

        agent.chat = _chatWithTool

        try:
            with patch(
                "neurova.api.endpoints.get_agent_instance", return_value=agent
            ):
                result = await swarm.spawn(task="做一次时间查询", agent_id="researcher")
            trace_id = str((result or {}).get("trace_id") or "")
            assert trace_id, "swarm run 必须带回 member 轨迹 id"

            calls, names = _toolFactsFromTrace(trace_id)
            assert calls > 0, (
                "swarm run 结束后必须能从 span 轨迹聚合出工具调用数（"
                "当前执行链不产 tool_call_start 事件，swarm 轨迹暂读 0）"
            )
            assert "get_datetime" in names
        finally:
            reset_swarm_manager()
