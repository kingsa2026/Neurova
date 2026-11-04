# -*- coding: utf-8 -*-
"""P2-6 / P3-5（审计 2026-11-04）：观测链路的静默异常必须留痕。

- tool_engine._extract_parameters：反射失败时工具 schema 静默退化，LLM 拿到
  空/残缺参数表且现场零留痕；
- execution_monitor：metric/alert handler 与执行日志加载失败均 `except: pass`，
  指标丢失、告警未送达、坏日志被跳过都不可见。
"""
import logging

from neurova.execution_engine.execution_monitor import AlertLevel, ExecutionMonitor
from neurova.execution_engine import tool_engine as tool_engine_module


def test_toolParameterReflectionFailureIsLogged(monkeypatch, caplog):
    engine = tool_engine_module.ToolEngine()

    def _boom(func):
        raise TypeError("signature boom")

    monkeypatch.setattr(tool_engine_module.inspect, "signature", _boom)
    with caplog.at_level(logging.WARNING, logger="neurova.execution_engine.tool_engine"):
        assert engine._extract_parameters(lambda x: x) == []
    assert any("boom" in str(r.getMessage()) or "参数" in str(r.getMessage())
               for r in caplog.records), "反射失败被无痕吞掉，工具 schema 静默退化"


def test_metricHandlerFailureIsLogged(caplog):
    monitor = ExecutionMonitor()

    def _boom(record):
        raise RuntimeError("metric handler boom")

    monitor.register_metric_handler(_boom)
    with caplog.at_level(logging.DEBUG, logger="neurova.execution_engine.execution_monitor"):
        monitor.record_metric("probe.metric", 1.0)
    assert any("metric" in str(r.getMessage()).lower() or "boom" in str(r.getMessage())
               for r in caplog.records), "指标处理器异常被无痕吞掉"


def test_alertHandlerFailureIsLogged(caplog):
    monitor = ExecutionMonitor()

    def _boom(alert):
        raise RuntimeError("alert handler boom")

    monitor.register_alert_handler(_boom)
    with caplog.at_level(logging.DEBUG, logger="neurova.execution_engine.execution_monitor"):
        monitor.create_alert(AlertLevel.WARNING, "probe", "body")
    assert any("告警处理器" in str(r.getMessage()) for r in caplog.records), (
        "告警处理器异常被无痕吞掉"
    )


def test_corruptExecutionLogIsNamedInLog(tmp_path, caplog):
    (tmp_path / "broken.json").write_text("{not-json", encoding="utf-8")
    monitor = ExecutionMonitor()
    with caplog.at_level(logging.DEBUG, logger="neurova.execution_engine.execution_monitor"):
        assert monitor.load_execution_history(str(tmp_path)) == 0
    assert any("broken.json" in str(r.getMessage()) for r in caplog.records), (
        "坏执行日志被跳过却不点名，排查不知道哪份文件坏了"
    )
