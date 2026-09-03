"""analytics.models 数据模型单元测试（对齐真实实现）。

真实 API（neurova/analytics/models.py）：
    枚举：MetricType / AgentStatus / TaskStatus
    数据类：TimeSeriesPoint / AgentMetrics / UserMetrics / TaskMetrics /
            DashboardStats / RealtimeMetric / TrendData / DistributionData /
            AnalyticsModels（容器）
    AgentMetrics.success_rate / error_rate 属性；TaskMetrics.complete()/fail()。

旧测试引用的 AnalyticsModels.format_duration / calculate_success_rate /
create_agent_metrics / create_user_metrics / create_task_metrics 等帮助方法
在真实实现中不存在（AnalyticsModels 是纯数据容器），相应测试移除。
字段名以真实定义为准：username（非 user_name）、metric_type（非 metric_name）、
average_response_time（非 avg_response_time）、last_active_at（非 last_active_time）。
"""

import time

import pytest

from neurova.analytics.models import (
    AgentMetrics,
    AgentStatus,
    AnalyticsModels,
    DashboardStats,
    DistributionData,
    MetricType,
    RealtimeMetric,
    TaskMetrics,
    TaskStatus,
    TimeSeriesPoint,
    TrendData,
    UserMetrics,
)


def _agent_metrics(**overrides):
    base = dict(
        agent_id="a1",
        agent_name="Agent One",
        status=AgentStatus.ACTIVE,
        uptime_seconds=100.0,
        total_requests=10,
        successful_requests=8,
        failed_requests=2,
        average_response_time=0.5,
        memory_usage_mb=128.0,
        cpu_usage_percent=20.0,
        active_tasks=2,
        queued_tasks=1,
    )
    base.update(overrides)
    return AgentMetrics(**base)


def _user_metrics(**overrides):
    base = dict(
        user_id="u1",
        username="alice",
        total_sessions=5,
        total_messages=100,
        average_session_duration=300.0,
        total_tokens_used=1000,
        total_cost=0.5,
    )
    base.update(overrides)
    return UserMetrics(**base)


def _task_metrics(**overrides):
    base = dict(
        task_id="t1",
        task_type="chat",
        status=TaskStatus.RUNNING,
        agent_id="a1",
    )
    base.update(overrides)
    return TaskMetrics(**base)


class TestEnums:
    def test_metric_type_members(self):
        assert {m.value for m in MetricType} == {
            "counter", "gauge", "histogram", "summary", "rate", "percentage",
        }

    def test_agent_status_members(self):
        assert {m.value for m in AgentStatus} == {
            "active", "idle", "busy", "error", "offline", "starting", "stopping",
        }

    def test_task_status_members(self):
        assert {m.value for m in TaskStatus} == {
            "pending", "running", "completed", "failed", "cancelled", "timeout",
        }


class TestTimeSeriesPoint:
    def test_construct_and_roundtrip(self):
        point = TimeSeriesPoint(timestamp=1.0, value=2.5, metadata={"k": "v"})
        assert point.value == 2.5
        assert TimeSeriesPoint.from_dict(point.to_dict()).value == 2.5


class TestAgentMetrics:
    def test_success_and_error_rate(self):
        m = _agent_metrics()
        assert m.success_rate == pytest.approx(0.8)
        assert m.error_rate == pytest.approx(0.2)

    def test_rates_zero_when_no_requests(self):
        m = _agent_metrics(total_requests=0, successful_requests=0, failed_requests=0)
        assert m.success_rate == 0.0
        assert m.error_rate == 0.0

    def test_to_dict_roundtrip(self):
        m = _agent_metrics()
        restored = AgentMetrics.from_dict(m.to_dict())
        assert restored.agent_id == "a1"
        assert restored.status == AgentStatus.ACTIVE


class TestUserMetrics:
    def test_construct_with_username(self):
        m = _user_metrics()
        assert m.username == "alice"
        assert m.total_sessions == 5

    def test_to_dict_roundtrip(self):
        m = _user_metrics()
        assert UserMetrics.from_dict(m.to_dict()).username == "alice"


class TestTaskMetrics:
    def test_complete_sets_status_and_duration(self):
        t = _task_metrics(start_time=time.time())
        t.complete(tokens_used=50, cost=0.1)
        assert t.status == TaskStatus.COMPLETED
        assert t.tokens_used == 50
        assert t.cost == 0.1
        assert t.duration_seconds is not None

    def test_fail_sets_status_and_error(self):
        t = _task_metrics(start_time=time.time())
        t.fail("boom")
        assert t.status == TaskStatus.FAILED
        assert t.error_message == "boom"

    def test_to_dict_roundtrip(self):
        t = _task_metrics()
        assert TaskMetrics.from_dict(t.to_dict()).task_id == "t1"


class TestDashboardStats:
    def test_construct_required_fields(self):
        stats = DashboardStats(
            total_agents=5, active_agents=3, total_users=10, active_users=7,
            total_requests=100, requests_per_minute=2.0, average_response_time=0.4,
            error_rate=0.05, total_tokens_used=5000, total_cost=1.5, uptime_seconds=999.0,
        )
        assert stats.total_agents == 5
        assert stats.error_rate == 0.05

    def test_to_dict_roundtrip(self):
        stats = DashboardStats(
            total_agents=1, active_agents=1, total_users=1, active_users=1,
            total_requests=1, requests_per_minute=1.0, average_response_time=1.0,
            error_rate=0.0, total_tokens_used=1, total_cost=0.0, uptime_seconds=1.0,
        )
        assert DashboardStats.from_dict(stats.to_dict()).total_agents == 1


class TestRealtimeMetric:
    def test_construct_with_metric_type(self):
        m = RealtimeMetric(name="cpu", value=42.0, metric_type=MetricType.GAUGE, unit="%")
        assert m.name == "cpu"
        assert m.metric_type == MetricType.GAUGE

    def test_to_dict_roundtrip(self):
        m = RealtimeMetric(name="qps", value=3.0, metric_type=MetricType.RATE)
        assert RealtimeMetric.from_dict(m.to_dict()).name == "qps"


class TestTrendData:
    def test_construct(self):
        points = [TimeSeriesPoint(timestamp=float(i), value=float(i)) for i in range(3)]
        trend = TrendData(
            metric_name="requests", time_range="24h", data_points=points,
            trend_direction="up", change_percentage=10.0,
            average_value=1.0, min_value=0.0, max_value=2.0,
        )
        assert trend.trend_direction == "up"
        assert len(trend.data_points) == 3


class TestDistributionData:
    def test_construct(self):
        dist = DistributionData(
            metric_name="latency",
            buckets=[{"label": "0-100", "count": 10}],
            total_count=10, mean=50.0, median=45.0, std_dev=5.0,
            percentiles={50: 45.0, 90: 90.0},
        )
        assert dist.total_count == 10
        assert dist.percentiles[90] == 90.0


class TestAnalyticsModelsContainer:
    def test_construct_and_aggregate(self):
        container = AnalyticsModels(
            agent_metrics=[_agent_metrics()],
            user_metrics=[_user_metrics()],
            task_metrics=[_task_metrics()],
        )
        assert len(container.agent_metrics) == 1
        assert len(container.user_metrics) == 1
        assert len(container.task_metrics) == 1

    def test_to_dict_includes_sections(self):
        container = AnalyticsModels(
            agent_metrics=[_agent_metrics()],
            user_metrics=[],
            task_metrics=[],
        )
        data = container.to_dict()
        assert "agent_metrics" in data
        assert len(data["agent_metrics"]) == 1

    def test_from_dict_roundtrip(self):
        container = AnalyticsModels(
            agent_metrics=[_agent_metrics()],
            user_metrics=[_user_metrics()],
            task_metrics=[_task_metrics()],
        )
        restored = AnalyticsModels.from_dict(container.to_dict())
        assert len(restored.agent_metrics) == 1
        assert restored.agent_metrics[0].agent_id == "a1"
