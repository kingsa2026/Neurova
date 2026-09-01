# -*- coding: utf-8 -*-
"""JSON 日志 trace_id 注入（logger↔trace_recorder 打通，补课 1.1）。

logger 只读 trace_context 的 ContextVar——禁止反向 import trace_recorder
（防循环依赖）。trace_recorder 在 start_trace 后 set、end_trace 后 clear。
"""
import json
import logging


def test_json_log_contains_trace_id_when_set():
    from neurova.core.logger import _JsonLogFormatter
    from neurova.core.trace_context import clear_trace_id, set_trace_id

    set_trace_id("tr-123")
    try:
        record = logging.LogRecord("t", logging.INFO, "p", 1, "hello %s", ("x",), None)
        payload = json.loads(_JsonLogFormatter().format(record))
        assert payload["trace_id"] == "tr-123"
    finally:
        clear_trace_id()


def test_json_log_omits_trace_id_when_unset():
    from neurova.core.logger import _JsonLogFormatter

    record = logging.LogRecord("t", logging.INFO, "p", 1, "plain", None, None)
    payload = json.loads(_JsonLogFormatter().format(record))
    assert "trace_id" not in payload


def test_trace_recorder_sets_and_clears(tmp_path, monkeypatch):
    from neurova.core import trace_context
    from neurova.core.trace_recorder import TrajectoryRecorder

    monkeypatch.setattr(TrajectoryRecorder, "_load_saved_traces_index", lambda self: None)
    monkeypatch.setattr(TrajectoryRecorder, "_save_traces_index", lambda self: None)
    monkeypatch.setattr(
        TrajectoryRecorder, "_persist_trace", lambda self, trace: None, raising=False
    )
    rec = TrajectoryRecorder()
    tid = rec.start_trace(session_id="s", agent_id="a", user_id="u")
    try:
        assert trace_context.get_trace_id() == tid
    finally:
        rec.end_trace(tid)
    assert trace_context.get_trace_id() is None
