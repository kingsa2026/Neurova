import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from neurova.execution_engine.execution_monitor import (
    ExecutionMonitor,
    AlertLevel,
    MetricType,
)


def _fresh():
    return ExecutionMonitor()


class TestExecutionMonitorInit:
    def test_empty_metrics(self):
        m = _fresh()
        assert m._metrics.__class__.__name__ == "defaultdict"
        assert len(m._metrics) == 0
        assert len(m._alerts) == 0
        assert len(m._traces) == 0
        assert len(m._execution_history) == 0


class TestRecordMetric:
    def test_record_and_retrieve(self):
        m = _fresh()
        m.record_metric("cpu", 42.0, MetricType.GAUGE)
        records = m.get_metrics("cpu")
        assert len(records) == 1
        assert records[0].name == "cpu"
        assert records[0].value == 42.0

    def test_record_multiple(self):
        m = _fresh()
        for i in range(5):
            m.record_metric("latency", float(i))
        records = m.get_metrics("latency")
        assert len(records) == 5


class TestCreateAlert:
    def test_create_and_acknowledge(self):
        m = _fresh()
        alert = m.create_alert(AlertLevel.WARNING, "slow", "took 5s")
        assert alert.level == AlertLevel.WARNING
        assert not alert.acknowledged
        ok = m.acknowledge_alert(alert.alert_id)
        assert ok is True
        alerts = m.get_alerts(level=AlertLevel.WARNING, acknowledged=True)
        assert len(alerts) == 1

    def test_alert_limit(self):
        m = _fresh()
        for _ in range(1500):
            m.create_alert(AlertLevel.INFO, "t", "msg")
        assert len(m._alerts) <= 1000


class TestTraceLifecycle:
    def test_start_end_trace(self):
        m = _fresh()
        trace = m.start_trace("exec-1", task_name="summarize")
        assert trace.execution_id == "exec-1"
        completed = m.complete_execution("exec-1")
        assert completed.status == "completed"
        assert completed.duration is not None
        assert completed.duration >= 0

    def test_fail_execution(self):
        m = _fresh()
        m.start_trace("exec-2")
        failed = m.fail_execution("exec-2", error="timeout")
        assert failed.status == "failed"
        assert "timeout" in failed.errors


class TestGetStatistics:
    def test_statistics(self):
        m = _fresh()
        m.start_trace("e1")
        m.complete_execution("e1")
        m.start_trace("e2")
        m.fail_execution("e2")
        stats = m.get_statistics()
        assert stats["total_traces"] == 2
        assert stats["completed"] == 1
        assert stats["failed"] == 1


class TestExecutionMetrics:
    def test_execution_metrics(self):
        m = _fresh()
        m.start_trace("e3")
        m.record_tool_call("e3", "web_search", duration=0.5)
        m.record_tool_call("e3", "web_search", duration=0.3, error="timeout")
        metrics = m.get_execution_metrics("e3")
        assert metrics.total_calls == 2
        assert metrics.successful_calls == 1
        assert metrics.failed_calls == 1
        assert metrics.tool_calls["web_search"] == 2


class TestReport:
    def test_generate_report(self):
        m = _fresh()
        report = m.generate_statistics_report()
        assert "执行监控报告" in report
        assert "总执行次数" in report
