"""
Analytics 端点真实统计测试（防回归）

背景：analytics.py 曾为内存 stub（record_request 零调用点，端点恒 0/空）
+ 模拟数据（get_behavior_stats 固定会话时长 300s、跳出率 0.1、留存 0.85），
且字段契约与前端 analytics.ts 类型四组全错位。

本测试锁定新契约（与前端 analytics.ts 对齐）：
1. /analytics/usage：total_requests/total_tokens 来自记账器、by_agent 每 agent 会话、
   by_model 记账器、daily_trend 会话/消息按天真实聚合
2. /analytics/performance：延迟/错误率来自 prometheus 埋点（llm 调用计数+直方图）
3. /analytics/behavior：top_tools 来自工具执行计数、peak_hours 来自会话小时分布；
   无真实源的 top_skills/conversation_patterns 恒空数组（不伪造）
4. /analytics/errors：总错误数=LLM 失败次数；无明细源 recent_errors 恒空数组
"""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import analytics
from neurova.core.usage_accounting import get_usage_accounting, reset_usage_accounting
from neurova.session_repository import reset_session_repository


@pytest.fixture(autouse=True)
def _clean_globals():
    reset_usage_accounting()
    reset_session_repository()
    yield
    reset_usage_accounting()
    reset_session_repository()


class FakeSessionRepo:
    """可控会话仓库桩：list_sessions 返回固定摘要列表，支持 agent 过滤。"""

    def __init__(self, sessions):
        self._sessions = sessions

    def list_sessions(self, agent_id: str = "", user_id: str = ""):
        if agent_id:
            return [s for s in self._sessions if s.get("agent_id") == agent_id]
        return self._sessions


def _sessions(days=7):
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return [
        {"session_id": "a1", "agent_id": "default", "created_at": f"{today}T10:00:00", "total_messages": 5},
        {"session_id": "a2", "agent_id": "alt", "created_at": f"{today}T11:00:00", "total_messages": 3},
        {"session_id": "a3", "agent_id": "default", "created_at": f"{yesterday}T09:00:00", "total_messages": 1},
    ]


def _seed_usage_accounting():
    acc = get_usage_accounting()
    acc.record(model="gpt-4o", provider="openai", prompt_tokens=100, completion_tokens=50)
    return acc.snapshot()


def _patch_home_sources(monkeypatch):
    """会话仓库走桩；聚合辅助保持真实实现（读同一桩仓库）。"""
    monkeypatch.setattr(
        "neurova.session_repository.get_session_repository",
        lambda: FakeSessionRepo(_sessions()),
    )
    monkeypatch.setattr("neurova.api.endpoints.home._sum_agent_persist_counts", lambda: 65)


class TestUsageRealStats:
    """/analytics/usage 必须来自真实源（记账器 + 会话仓库按天聚合）。"""

    @pytest.mark.asyncio
    async def test_usage_contract_and_values(self, monkeypatch):
        _patch_home_sources(monkeypatch)
        snap = _seed_usage_accounting()

        res = await analytics.get_usage_stats(MagicMock(), period="week", current_user={"user_id": "1"})

        assert res["period"] == "week"
        assert res["total_requests"] == snap["total"]["calls"] == 1
        assert res["total_tokens"] == snap["total"]["total_tokens"] == 150
        assert res["avg_latency_ms"] == 0  # 无延迟记录源，诚实 0

        # by_agent：default 2 会话 / alt 1 会话
        by_agent = {a["agent_id"]: a["requests"] for a in res["by_agent"]}
        assert by_agent == {"default": 2, "alt": 1}

        # by_model：来自记账器
        by_model = {m["model"]: (m["requests"], m["tokens"]) for m in res["by_model"]}
        assert by_model.get("gpt-4o") == (1, 150)

        # daily_trend：最后一天 2 条会话 / 8 条消息，倒数第二天 1 / 1
        # （date 为 MM-DD 短标签，与 /home/trends 一致）
        trend = res["daily_trend"]
        assert len(trend) == 7
        assert trend[-1]["date"] == datetime.now().strftime("%m-%d")
        assert (trend[-1]["requests"], trend[-1]["tokens"]) == (2, 8)
        assert (trend[-2]["requests"], trend[-2]["tokens"]) == (1, 1)

    @pytest.mark.asyncio
    async def test_source_failure_degrades_to_empty(self, monkeypatch):
        """数据源异常时端点不炸，回退 0/空数组。"""
        def boom(*a, **kw):
            raise RuntimeError("repo down")

        monkeypatch.setattr("neurova.session_repository.get_session_repository", boom)
        monkeypatch.setattr("neurova.api.endpoints.home._sum_agent_persist_counts", boom)

        res = await analytics.get_usage_stats(MagicMock(), period="day", current_user={"user_id": "1"})

        assert res["total_requests"] == 0
        assert res["total_tokens"] == 0
        assert res["by_agent"] == []
        assert res["daily_trend"] == []


class TestPerformanceRealStats:
    """/analytics/performance 必须来自 prometheus 埋点（llm 调用计数 + 直方图）。"""

    SEED = {
        "total_calls": 4,
        "failed_calls": 1,
        "avg_latency_ms": 200.0,
        "p95_latency_ms": 300.0,
        "by_model": [
            {"model": "m-a", "provider": "p-openai", "calls": 3, "failed_calls": 0, "avg_ms": 200.0},
            {"model": "m-b", "provider": "p-openai", "calls": 1, "failed_calls": 1, "avg_ms": 150.0},
        ],
    }

    @pytest.mark.asyncio
    async def test_performance_from_llm_metrics(self, monkeypatch):
        monkeypatch.setattr(
            "neurova.api.endpoints.analytics._read_llm_metrics", lambda: dict(self.SEED)
        )
        # 固定 uptime 保证吞吐断言确定性（真实进程 uptime 不可控）
        monkeypatch.setattr("neurova.api.endpoints.analytics._uptime", lambda: 100.0)

        res = await analytics.get_performance_stats(MagicMock(), period="day", current_user={"user_id": "1"})

        assert res["period"] == "day"
        assert res["avg_latency_ms"] == 200.0
        assert res["p95_latency_ms"] == 300.0
        assert res["error_rate"] == 25.0  # 1/4 失败
        assert res["throughput_rps"] == 0.04  # 4 calls / 100s
        assert res["error_rate"] >= 0

        by_endpoint = {e["endpoint"]: e for e in res["by_endpoint"]}
        assert by_endpoint["p-openai:m-a"]["count"] == 3
        assert by_endpoint["p-openai:m-a"]["avg_ms"] == 200.0

    @pytest.mark.asyncio
    async def test_no_metrics_is_zero(self, monkeypatch):
        monkeypatch.setattr(
            "neurova.api.endpoints.analytics._read_llm_metrics",
            lambda: {"total_calls": 0, "failed_calls": 0, "avg_latency_ms": 0.0,
                     "p95_latency_ms": 0.0, "by_model": []},
        )

        res = await analytics.get_performance_stats(MagicMock(), period="week", current_user={"user_id": "1"})

        assert res["avg_latency_ms"] == 0
        assert res["error_rate"] == 0
        assert res["by_endpoint"] == []
        assert res["throughput_rps"] == 0


class TestBehaviorRealStats:
    """/analytics/behavior：top_tools 真实计数、peak_hours 真实小时分布；无源项恒空。"""

    @pytest.mark.asyncio
    async def test_behavior_top_tools_and_peak_hours(self, monkeypatch):
        _patch_home_sources(monkeypatch)
        monkeypatch.setattr(
            "neurova.api.endpoints.analytics._read_tool_metrics",
            lambda: [{"name": "web_search", "usage_count": 5, "success_count": 4, "avg_duration_ms": 120.0}],
        )

        res = await analytics.get_behavior_stats(MagicMock(), period="week", current_user={"user_id": "1"})

        assert res["top_tools"] == [{"name": "web_search", "usage_count": 5, "success_count": 4, "avg_duration_ms": 120.0}]
        # 无真实源的项严格空数组
        assert res["top_skills"] == []
        assert res["conversation_patterns"] == []

        # peak_hours：今天 10/11 点各 1、昨天 09 点 1
        peak = {p["hour"]: p["requests"] for p in res["peak_hours"]}
        hour_today_10 = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0).hour
        assert peak.get(10, 0) == 1
        assert peak.get(11, 0) == 1


class TestErrorsRealStats:
    """/analytics/errors：总错误数=LLM 失败次数，按 provider 聚合；无明细源恒空。"""

    @pytest.mark.asyncio
    async def test_errors_from_llm_failures(self, monkeypatch):
        monkeypatch.setattr(
            "neurova.api.endpoints.analytics._read_llm_metrics",
            lambda: dict(TestPerformanceRealStats.SEED, failed_calls=2),
        )

        res = await analytics.get_error_stats(MagicMock(), period="day", current_user={"user_id": "1"})

        assert res["period"] == "day"
        assert res["total_errors"] == 2
        assert res["error_rate"] > 0
        assert res["recent_errors"] == []  # 无结构化明细源，诚实空数组
        assert any(t["type"] == "p-openai" and t["count"] >= 1 for t in res["by_type"])

    @pytest.mark.asyncio
    async def test_no_errors_is_zero(self, monkeypatch):
        monkeypatch.setattr(
            "neurova.api.endpoints.analytics._read_llm_metrics",
            lambda: {"total_calls": 0, "failed_calls": 0, "avg_latency_ms": 0.0,
                     "p95_latency_ms": 0.0, "by_model": []},
        )

        res = await analytics.get_error_stats(MagicMock(), period="week", current_user={"user_id": "1"})

        assert res["total_errors"] == 0
        assert res["by_type"] == []
        assert res["by_endpoint"] == []
