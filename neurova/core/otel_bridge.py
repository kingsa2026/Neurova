"""OTel 兼容层（P0-5 — Dify unified_trace 对标）。

自研 TrajectoryRecorder 已有完整 span 模型（trace/span/event/parent/
duration），本桥把它投影为 OpenTelemetry span——不改业务代码，不改
记录器语义。设计约束（docs/Neurova_Dify代码级对比_2026-09-03.md §5）：

- **可选依赖**：opentelemetry-api 缺席 → no-op 桥（只记账）；api 在位、
  sdk 缺位 → enabled=False（无 exporter 可投）；两者都在 → 真实投影。
  绝不在模块顶层强依赖 otel（避免"LogDir 双层"式反模式）。
- **显式装配**（增量约束：新扩展点默认关）：install_otel_bridge() /
  uninstall_otel_bridge() 可逆，幂等。
- **两个投影源**：
  1. TrajectoryRecorder——观察者挂 start_trace/start_span/record_event/
     end_span/end_trace（记录器零改动，桥订阅其返回值）
  2. neurflow WorkflowExecutor 事件咽喉——WORKFLOW_STARTED 建 root、
     NODE_STARTED 建节点 span、NODE_COMPLETED/FAILED 闭合、WORKFLOW_*
     收尾强制闭合泄漏 span；验收形态：1 root + N 节点 span（Langfuse/
     Opik 等 OTel 后端直接可见）

装 sdk 后接 exporter 即入 Langfuse（OTLP）——本模块不绑定具体后端。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_lock = threading.RLock()
# 观察者包装前保存的记录器原方法（install 时写入；uninstall 时还原）
_ORIG_METHODS: Dict[str, Any] = {}
_state: Dict[str, Any] = {
    "installed": False,
    "enabled": False,
    "reason": "",
    # otel 对象（enabled 时非 None）
    "tracer": None,
    # trace_id -> {"otel_span": ...}; span_id -> {"otel_span": ...}
    "traces": {},
    "spans": {},
    # neurflow: execution_id -> {"root": span, "nodes": {node_id: span}}
    "nf_runs": {},
    # 记账
    "traces_projected": 0,
    "spans_projected": 0,
    "events_projected": 0,
    "neurflow_runs": 0,
    "neurflow_node_spans": 0,
    # 观察者引用（卸载用）
    "_recorder_observer_installed": False,
    "_nf_executor_handler": None,
}


def bridge_stats() -> Dict[str, Any]:
    """投影账目（测试与 /otel/status 共用）"""
    with _lock:
        return {
            k: (dict(v) if isinstance(v, dict) and k.startswith("nf_") else v)
            for k, v in _state.items()
            if not k.startswith("_")
        }


def _otel_imports() -> tuple:
    """分层探测 otel 可用性：(api_available, sdk_available, trace_module, SpanKind, Status, StatusCode)"""
    try:
        from opentelemetry import trace as _trace

        api_ok = True
    except Exception:  # noqa: BLE001 — 可选依赖缺席
        return False, False, None, None, None, None
    try:
        from opentelemetry.sdk.trace import TracerProvider  # noqa: F401
        from opentelemetry.trace import SpanKind, Status, StatusCode

        sdk_ok = True
    except Exception:  # noqa: BLE001 — sdk 缺位（只有 api）
        sdk_ok = False
        SpanKind = Status = StatusCode = None
    return api_ok, sdk_ok, _trace, SpanKind, Status, StatusCode


# ── TrajectoryRecorder 投影 ───────────────────────────────────


def _make_recorder_observer():
    """构造记录器观察者：包装 start_trace/start_span/record_event/end_span/end_trace。

    包装式观察（而非继承/侵入）保证记录器语义零改动；sdk 缺位时只记账。
    """
    from neurova.core.trace_recorder import TrajectoryRecorder

    rec = TrajectoryRecorder()

    orig_start_trace = rec.start_trace
    orig_start_span = rec.start_span
    orig_record_event = rec.record_event
    orig_end_span = rec.end_span
    orig_end_trace = rec.end_trace

    _, sdk_ok, trace_mod, SpanKind, Status, StatusCode = _otel_imports()
    tracer = _state.get("tracer") if sdk_ok else None

    def observed_start_trace(session_id, agent_id, user_id, metadata=None):
        trace_id = orig_start_trace(session_id, agent_id, user_id, metadata)
        with _lock:
            if _state["installed"]:
                _state["traces_projected"] += 1
                if tracer is not None:
                    span = tracer.start_span(
                        f"neurova.trace.{session_id}",
                        attributes={"session_id": session_id, "agent_id": agent_id, "user_id": user_id},
                    )
                    _state["traces"][trace_id] = span
        return trace_id

    def observed_start_span(trace_id, operation_name, operation_type, parent_span_id=None):
        span_id = orig_start_span(trace_id, operation_name, operation_type, parent_span_id)
        with _lock:
            if _state["installed"] and span_id:
                _state["spans_projected"] += 1
                if tracer is not None:
                    # 上下文挂父 span（无 context 传播需求，直接 start_span 独立 span，
                    # 用属性记录父子——导出后端按 trace 时序可重建层级）
                    attrs = {"trace_id": trace_id, "operation_type": operation_type}
                    if parent_span_id:
                        attrs["parent_span_id"] = parent_span_id
                    otel_span = tracer.start_span(f"neurova.span.{operation_name}", attributes=attrs)
                    _state["spans"][span_id] = otel_span
        return span_id

    def observed_record_event(trace_id, event_type, data=None, span_id=None):
        orig_record_event(trace_id, event_type, data, span_id)
        with _lock:
            if _state["installed"]:
                _state["events_projected"] += 1
                if tracer is not None:
                    otel_span = _state["spans"].get(span_id) or _state["traces"].get(trace_id)
                    if otel_span is not None:
                        try:
                            otel_span.add_event(str(getattr(event_type, "value", event_type)), attributes={
                                k: str(v) for k, v in (data or {}).items() if isinstance(v, (str, int, float, bool))
                            })
                        except Exception as e:  # noqa: BLE001 — 观察不干扰
                            logger.debug("otel add_event 失败: %s", e)

    def observed_end_span(span_id, status="completed", error_message=None):
        orig_end_span(span_id, status, error_message)
        with _lock:
            otel_span = _state["spans"].pop(span_id, None)
            if otel_span is not None and tracer is not None:
                try:
                    if StatusCode is not None:
                        ok = status in ("success", "completed", "completed_with_errors") and not error_message
                        otel_span.set_status(
                            Status(StatusCode.OK if ok else StatusCode.ERROR, error_message or "")
                        )
                    otel_span.end()
                except Exception as e:  # noqa: BLE001
                    logger.debug("otel end_span 失败: %s", e)

    def observed_end_trace(trace_id):
        orig_end_trace(trace_id)
        with _lock:
            otel_span = _state["traces"].pop(trace_id, None)
            if otel_span is not None and tracer is not None:
                try:
                    otel_span.end()
                except Exception as e:  # noqa: BLE001
                    logger.debug("otel end_trace 失败: %s", e)

    return {
        "start_trace": observed_start_trace,
        "start_span": observed_start_span,
        "record_event": observed_record_event,
        "end_span": observed_end_span,
        "end_trace": observed_end_trace,
    }, {
        "start_trace": orig_start_trace,
        "start_span": orig_start_span,
        "record_event": orig_record_event,
        "end_span": orig_end_span,
        "end_trace": orig_end_trace,
    }


class _NeurflowOtelBridge:
    """neurflow 事件 → OTel 节点 span（1 root + N 节点）"""

    NODE_TERMINAL = {"node_completed", "node_failed", "node_skipped"}

    def on_event(self, event) -> None:
        try:
            etype = str(getattr(event.type, "value", event.type) or "")
            execution_id = getattr(event, "execution_id", "") or ""
            if not execution_id:
                return
            _, sdk_ok, trace_mod, SpanKind, Status, StatusCode = _otel_imports()
            tracer = _state.get("tracer") if sdk_ok else None

            with _lock:
                if not _state["installed"]:
                    return
                run = _state["nf_runs"].setdefault(execution_id, {"root": None, "nodes": {}})

                if etype == "workflow_started":
                    _state["neurflow_runs"] += 1
                    if tracer is not None:
                        run["root"] = tracer.start_span(
                            f"neurova.workflow.{getattr(event, 'workflow_id', '')}",
                            attributes={"execution_id": execution_id, "workflow_id": str(getattr(event, "workflow_id", ""))},
                        )
                elif etype == "node_started":
                    node_id = getattr(event, "node_id", None)
                    if node_id:
                        _state["neurflow_node_spans"] += 1
                        if tracer is not None:
                            run["nodes"][node_id] = tracer.start_span(
                                f"neurova.node.{node_id}",
                                attributes={"execution_id": execution_id, "node_id": node_id},
                            )
                elif etype in self.NODE_TERMINAL:
                    node_id = getattr(event, "node_id", None)
                    otel_span = run["nodes"].pop(node_id, None) if node_id else None
                    if otel_span is not None and tracer is not None:
                        try:
                            failed = etype == "node_failed"
                            if StatusCode is not None:
                                from opentelemetry.trace import Status, StatusCode

                                otel_span.set_status(
                                    Status(StatusCode.ERROR if failed else StatusCode.OK,
                                           str((getattr(event, "data", {}) or {}).get("error", ""))[:200])
                                )
                            otel_span.end()
                        except Exception as e:  # noqa: BLE001
                            logger.debug("otel node span end 失败: %s", e)
                elif etype in ("workflow_completed", "workflow_failed", "cancelled", "paused"):
                    # 收尾：强制闭合泄漏的节点 span + root
                    if tracer is not None:
                        for node_span in run["nodes"].values():
                            try:
                                node_span.end()
                            except Exception:  # noqa: BLE001
                                pass
                        root = run.pop("root", None)
                        if root is not None:
                            try:
                                if StatusCode is not None and etype in ("workflow_failed",):
                                    from opentelemetry.trace import Status, StatusCode

                                    root.set_status(Status(StatusCode.ERROR))
                                root.end()
                            except Exception:  # noqa: BLE001
                                pass
                    _state["nf_runs"].pop(execution_id, None)
        except Exception as e:  # noqa: BLE001 — 观察者绝不干扰执行
            logger.debug("neurflow otel bridge 处理事件失败: %s", e)


_neurflow_bridge: Optional[_NeurflowOtelBridge] = None


def get_neurflow_bridge() -> _NeurflowOtelBridge:
    """neurflow 事件桥单例（事件订阅方）"""
    global _neurflow_bridge
    if _neurflow_bridge is None:
        _neurflow_bridge = _NeurflowOtelBridge()
    return _neurflow_bridge


# ── 装配 / 卸载 ───────────────────────────────────────────────


def install_otel_bridge() -> Dict[str, Any]:
    """显式装配（幂等）：记录器观察者 + neurflow 引擎事件钩子。

    Returns:
        {"installed": bool, "enabled": bool, "reason": str}
        enabled=False 表示 otel 依赖不全（no-op 记账模式）。
    """
    with _lock:
        if _state["installed"]:
            return {"installed": True, "enabled": _state["enabled"], "reason": _state["reason"]}

        api_ok, sdk_ok, trace_mod, SpanKind, Status, StatusCode = _otel_imports()
        if not api_ok:
            _state["reason"] = "opentelemetry 未安装（no-op 记账模式；pip install opentelemetry-sdk 启用）"
        elif not sdk_ok:
            _state["reason"] = "opentelemetry-sdk 缺位（仅 api；无 exporter 可投，no-op 记账模式）"
        else:
            _state["reason"] = ""
            try:
                from opentelemetry.sdk.trace import TracerProvider

                provider = TracerProvider()
                trace_mod.set_tracer_provider(provider)
                _state["tracer"] = provider.get_tracer("neurova.otel_bridge")
            except Exception as e:  # noqa: BLE001 — provider 已被设过等场景
                logger.warning("OTel TracerProvider 装配失败（降级 no-op）: %s", e)
                _state["tracer"] = None
                _state["reason"] = f"TracerProvider 装配失败: {e}"

        # 记录器观察者（包装式；持有原方法引用供卸载还原）
        if not _state["_recorder_observer_installed"]:
            from neurova.core.trace_recorder import TrajectoryRecorder as _TR

            rec = _TR()
            wrapped, originals = _make_recorder_observer()
            _ORIG_METHODS.update(originals)
            rec.start_trace = wrapped["start_trace"]
            rec.start_span = wrapped["start_span"]
            rec.record_event = wrapped["record_event"]
            rec.end_span = wrapped["end_span"]
            rec.end_trace = wrapped["end_trace"]
            _state["_recorder_observer_installed"] = True

        # neurflow 执行器事件钩子
        try:
            from neurova.collaboration.neurflow.execution_engine import get_workflow_executor

            handler = get_neurflow_bridge().on_event
            get_workflow_executor().on_event(handler)
            _state["_nf_executor_handler"] = handler
        except Exception as e:  # noqa: BLE001 — neurflow 不可用不阻断装配
            logger.debug("neurflow otel 钩子挂载失败: %s", e)

        _state["installed"] = True
        _state["enabled"] = _state["tracer"] is not None
        return {"installed": True, "enabled": _state["enabled"], "reason": _state["reason"]}


def uninstall_otel_bridge() -> None:
    """卸载（可逆，幂等）：恢复记录器原方法、摘除引擎钩子、清空投影态"""
    with _lock:
        if not _state["installed"]:
            return

        # 还原记录器原方法（包装闭包持有的 orig 引用）
        rec = TrajectoryRecorderSingleton()
        for name, orig in _ORIG_METHODS.items():
            try:
                setattr(rec, name, orig)
            except Exception:  # noqa: BLE001
                pass
        _ORIG_METHODS.clear()
        _state["_recorder_observer_installed"] = False

        # 摘除 neurflow 引擎钩子
        if _state["_nf_executor_handler"] is not None:
            try:
                from neurova.collaboration.neurflow.execution_engine import get_workflow_executor

                handlers = get_workflow_executor()._event_handlers
                if _state["_nf_executor_handler"] in handlers:
                    handlers.remove(_state["_nf_executor_handler"])
            except Exception:  # noqa: BLE001
                pass
            _state["_nf_executor_handler"] = None

        # 强制闭合泄漏 span（防 exporter 悬挂）
        for s in list(_state["spans"].values()) + list(_state["traces"].values()):
            try:
                s.end()
            except Exception:  # noqa: BLE001
                pass
        for run in _state["nf_runs"].values():
            for s in run["nodes"].values():
                try:
                    s.end()
                except Exception:  # noqa: BLE001
                    pass
            if run.get("root") is not None:
                try:
                    run["root"].end()
                except Exception:  # noqa: BLE001
                    pass

        _state.update({
            "installed": False,
            "enabled": False,
            "reason": "",
            "tracer": None,
            "traces": {},
            "spans": {},
            "nf_runs": {},
            "traces_projected": 0,
            "spans_projected": 0,
            "events_projected": 0,
            "neurflow_runs": 0,
            "neurflow_node_spans": 0,
        })


def TrajectoryRecorderSingleton():
    from neurova.core.trace_recorder import TrajectoryRecorder

    return TrajectoryRecorder()
