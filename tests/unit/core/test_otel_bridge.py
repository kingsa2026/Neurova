"""P0-5 OTel 兼容层（TDD — Dify 对标 §4 P0-5）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md）：
- TrajectoryRecorder 的 span 模型 → OTel bridge：可选依赖（opentelemetry-api
  已装 / sdk 未装时降级记账-only，不崩不阻塞业务）
- install_otel_bridge() 显式装配（增量约束：默认关）；uninstall_otel_bridge()
  可逆（摘除 recorder 观察者与 neurflow 引擎事件钩子）
- 装配后投影记账一致（trace/span/event 计数）；sdk 在位时额外产出真实 OTel span
- neurflow 引擎事件按 execution_id 建 root、按 node_id 建节点 span——
  验收标准：一个 run 在 OTel exporter 可见 1 root + N 节点 span
"""

import pytest


@pytest.fixture
def clean_bridge():
    from neurova.core.otel_bridge import uninstall_otel_bridge

    uninstall_otel_bridge()
    yield
    uninstall_otel_bridge()


class TestOptionalDependency:
    def test_api_only_degrades_gracefully(self, clean_bridge):
        """opentelemetry-api 已装、sdk 缺位 → enabled=False 但装配成功不崩"""
        from neurova.core import otel_bridge

        status = otel_bridge.install_otel_bridge()
        assert status["installed"] is True
        assert status["enabled"] is False
        assert "sdk" in status.get("reason", "")

    def test_bridge_noop_without_otel(self, clean_bridge, monkeypatch):
        """opentelemetry 完全缺席 → no-op 桥，记录器照常工作"""
        import sys

        from neurova.core import otel_bridge
        from neurova.core.trace_recorder import TrajectoryRecorder

        monkeypatch.setitem(sys.modules, "opentelemetry", None)
        monkeypatch.setitem(sys.modules, "opentelemetry.trace", None)

        status = otel_bridge.install_otel_bridge()
        assert status["enabled"] is False

        rec = TrajectoryRecorder()
        tid = rec.start_trace(session_id="s1", agent_id="a1", user_id="u1")
        rec.end_trace(tid)
        assert rec._active_traces.get(tid) is None, "轨迹结束后移出活跃表（记录器语义不变）"


class TestSpanProjection:
    def test_trace_and_spans_accounted(self, clean_bridge):
        """trace + span + event 投影记账（无 sdk 时也保持账目一致）"""
        from neurova.core import otel_bridge
        from neurova.core.trace_models import TrajectoryEventType
        from neurova.core.trace_recorder import TrajectoryRecorder

        otel_bridge.install_otel_bridge()
        rec = TrajectoryRecorder()

        tid = rec.start_trace(session_id="s1", agent_id="a1", user_id="u1")
        sid = rec.start_span(tid, "llm_call", operation_type="llm")
        rec.record_event(tid, TrajectoryEventType.LLM_CALL_END, {"tokens": 25}, span_id=sid)
        rec.end_span(sid, status="success")
        rec.end_trace(tid)

        stats = otel_bridge.bridge_stats()
        assert stats["traces_projected"] >= 1
        assert stats["spans_projected"] >= 1
        assert stats["events_projected"] >= 1

    def test_uninstall_stops_projection(self, clean_bridge):
        from neurova.core import otel_bridge
        from neurova.core.trace_recorder import TrajectoryRecorder

        otel_bridge.install_otel_bridge()
        rec = TrajectoryRecorder()
        tid1 = rec.start_trace(session_id="s2", agent_id="a1", user_id="u1")
        otel_bridge.uninstall_otel_bridge()

        tid2 = rec.start_trace(session_id="s3", agent_id="a1", user_id="u1")
        rec.end_trace(tid2)
        rec.end_trace(tid1)

        stats = otel_bridge.bridge_stats()
        assert stats["traces_projected"] == 0, "卸载后不再投影"


class TestNeurflowNodeSpans:
    def test_engine_emission_hooks_node_spans(self, clean_bridge):
        """neurflow 事件咽喉 → 按 execution 建 root、按 node 建 span（账目）"""
        from neurova.core import otel_bridge
        from neurova.collaboration.neurflow.execution_engine import ExecutionEvent, ExecutionEventType

        otel_bridge.install_otel_bridge()
        before = otel_bridge.bridge_stats()

        bridge = otel_bridge.get_neurflow_bridge()
        execution_id = "exec-otel-1"
        bridge.on_event(ExecutionEvent(
            type=ExecutionEventType.WORKFLOW_STARTED,
            workflow_id="wf1", execution_id=execution_id, data={},
        ))
        bridge.on_event(ExecutionEvent(
            type=ExecutionEventType.NODE_STARTED,
            workflow_id="wf1", execution_id=execution_id, node_id="n1",
        ))
        bridge.on_event(ExecutionEvent(
            type=ExecutionEventType.NODE_COMPLETED,
            workflow_id="wf1", execution_id=execution_id, node_id="n1",
            data={"status": "success", "output": {"x": 1}},
        ))
        bridge.on_event(ExecutionEvent(
            type=ExecutionEventType.NODE_STARTED,
            workflow_id="wf1", execution_id=execution_id, node_id="n2",
        ))
        bridge.on_event(ExecutionEvent(
            type=ExecutionEventType.WORKFLOW_COMPLETED,
            workflow_id="wf1", execution_id=execution_id,
        ))

        after = otel_bridge.bridge_stats()
        assert after["neurflow_runs"] == before.get("neurflow_runs", 0) + 1
        assert after["neurflow_node_spans"] >= before.get("neurflow_node_spans", 0) + 2

    def test_engine_execute_attaches_bridge(self, clean_bridge):
        """install 给 neurflow 执行器挂事件钩子；uninstall 摘除"""
        from neurova.core import otel_bridge
        from neurova.collaboration.neurflow.execution_engine import get_workflow_executor

        executor = get_workflow_executor()
        handlers_before = len(executor._event_handlers)

        otel_bridge.install_otel_bridge()
        assert len(executor._event_handlers) == handlers_before + 1, "装配后执行器多一个事件钩子"

        otel_bridge.uninstall_otel_bridge()
        assert len(executor._event_handlers) == handlers_before, "卸载后钩子摘除"


class TestStatusEndpoint:
    def test_otel_status_shape(self):
        from neurova.api.endpoints.neurflow_api import otel_status

        result = otel_status()
        assert result["code"] == 0
        data = result["data"]
        for key in ("installed", "enabled", "traces_projected", "spans_projected", "neurflow_runs"):
            assert key in data
