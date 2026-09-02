"""
轨迹记录器测试（2026-09-02 重建：原文件在预存失败修复中被清空后按现行
TrajectoryRecorder API 重写，保留原用例名与语义断言）。

原失败根因：start_trace 增加必填 user_id 参数（隔离三元组），测试桩
停留在旧三参签名——A 类签名漂移（test-debt 台账）。
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from neurova.core.trace_recorder import (
    TrajectoryRecorder,
    get_trajectory_recorder,
)
from neurova.core.trace_models import TrajectoryEventType


class TestTrajectoryRecorder:
    """测试轨迹记录器"""

    @pytest.fixture
    def recorder(self, tmp_path):
        """创建轨迹记录器实例"""
        recorder = TrajectoryRecorder()
        recorder.set_storage_dir(str(tmp_path / "trajectories"))
        recorder._enabled = True
        recorder._auto_save = False
        return recorder

    # ── 基础 ──

    def test_init(self, recorder):
        assert recorder is not None
        assert recorder._enabled is True
        assert recorder._storage_dir.exists()

    def test_singleton(self):
        recorder1 = get_trajectory_recorder()
        recorder2 = get_trajectory_recorder()
        assert recorder1 is recorder2

    # ── start_trace ──

    def test_start_trace(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        assert trace_id is not None
        assert trace_id != ""
        assert trace_id in recorder._active_traces

    def test_start_trace_disabled(self, recorder):
        recorder._enabled = False
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        assert trace_id == ""

    def test_start_trace_without_user_id(self, recorder):
        """user_id 缺失（隔离三元组必填）——缺失应抛 TypeError 防静默落错作用域"""
        with pytest.raises(TypeError):
            recorder.start_trace(session_id="session1", agent_id="agent1")

    # ── end_trace ──

    def test_end_trace(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        recorder.end_trace(trace_id)
        assert trace_id not in recorder._active_traces

    # ── span ──

    def test_start_span(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        span_id = recorder.start_span(trace_id, "op1", "tool")
        assert span_id is not None
        assert span_id in recorder._active_spans

    def test_start_span_with_parent(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        parent_id = recorder.start_span(trace_id, "parent", "session")
        child_id = recorder.start_span(trace_id, "child", "tool", parent_span_id=parent_id)
        assert child_id is not None
        trace = recorder._active_traces[trace_id]
        assert trace.spans[child_id].parent_span_id == parent_id

    def test_end_span(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        span_id = recorder.start_span(trace_id, "op1", "tool")
        recorder.end_span(span_id, status="completed")
        assert recorder._active_spans[span_id].status == "completed"

    def test_end_span_with_error(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        span_id = recorder.start_span(trace_id, "op1", "tool")
        recorder.end_span(span_id, status="error", error_message="boom")
        assert recorder._active_spans[span_id].status == "error"

    def test_start_span_for_nonexistent_trace(self, recorder):
        result = recorder.start_span("no-such-trace", "op1", "tool")
        assert not result

    def test_multiple_spans_in_trace(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        s1 = recorder.start_span(trace_id, "op1", "tool")
        s2 = recorder.start_span(trace_id, "op2", "tool")
        trace = recorder._active_traces[trace_id]
        assert s1 in trace.spans and s2 in trace.spans

    def test_nested_spans(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        parent = recorder.start_span(trace_id, "parent", "session")
        child = recorder.start_span(trace_id, "child", "tool", parent_span_id=parent)
        trace = recorder._active_traces[trace_id]
        assert trace.spans[child].parent_span_id == parent

    # ── 事件/LLM/工具记录 ──

    def test_record_event(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        span_id = recorder.start_span(trace_id, "root", "session")
        recorder.record_event(trace_id, TrajectoryEventType.USER_INPUT, {"text": "hi"}, span_id=span_id)
        span = recorder._active_spans[span_id]
        assert span.events, "事件应存入 span.events"

    def test_record_event_with_span(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        span_id = recorder.start_span(trace_id, "op1", "tool")
        recorder.record_event(
            trace_id, TrajectoryEventType.TOOL_CALL_START, {"tool": "x"}, span_id=span_id
        )
        span = recorder._active_spans[span_id]
        assert span.events, "事件应存入指定 span"

    def test_record_llm_call(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        span_id = recorder.start_span(trace_id, "llm", "llm")
        recorder.record_llm_call(
            trace_id, model_name="gpt-x", input_tokens=10, output_tokens=20
        )
        span = recorder._active_spans[span_id]
        assert span.events and span.events[-1].data["model_name"] == "gpt-x"

    def test_record_tool_call(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        span_id = recorder.start_span(trace_id, "tool", "tool")
        recorder.record_tool_call(
            trace_id,
            tool_name="shell",
            tool_source="builtin",
            parameters={"cmd": "ls"},
            execution_time=0.1,
            success=True,
        )
        span = recorder._active_spans[span_id]
        assert span.events

    # ── 持久化 ──

    def test_save_trace(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        path = recorder.save_trace(trace_id)
        assert path is not None

    def test_load_trace(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        # save 在 end 之前（save_trace 只认 active_traces，end_trace 已 pop）
        recorder.save_trace(trace_id)
        recorder.end_trace(trace_id)
        loaded = recorder.load_trace(trace_id, user_id="user1")
        assert loaded is not None
        assert loaded.trace_id == trace_id

    def test_list_traces(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        recorder.save_trace(trace_id)
        recorder.end_trace(trace_id)
        traces = recorder.list_traces(user_id="user1")
        assert any(t.get("trace_id") == trace_id for t in traces)

    def test_list_traces_with_filter(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        recorder.save_trace(trace_id)
        recorder.end_trace(trace_id)
        traces = recorder.list_traces(user_id="user1", agent_id="agent1")
        assert any(t.get("trace_id") == trace_id for t in traces)
        other = recorder.list_traces(user_id="user1", agent_id="agent-other")
        assert not any(t.get("trace_id") == trace_id for t in other)

    def test_replay_trace(self, recorder):
        trace_id = recorder.start_trace(
            session_id="session1", agent_id="agent1", user_id="user1"
        )
        recorder.record_event(trace_id, TrajectoryEventType.USER_INPUT, {"text": "hi"})
        recorder.save_trace(trace_id)
        recorder.end_trace(trace_id)

        seen = []
        recorder.replay_trace(trace_id, speed=0, callback=lambda ev: seen.append(ev))
        assert seen