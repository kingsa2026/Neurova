"""
Stats 端点真实统计测试（防回归）

背景：stats.py 曾为部分 stub——GET /stats 的 total_conversations/total_memories
等字段恒 0、GET /stats/usage 是 TODO 空体、GET /stats/agents 依赖不存在的
agent.get_stats()（字段与前端 AgentStats 错位）、GET /stats/export 不存在。

本测试锁定新契约（与前端 stats.ts 对齐）：
1. GET /stats：overview（agent/会话/记忆/token/调用/错误，全部真实）+ trends 按天
2. GET /stats/agents：每 agent id/name/status/conversations/messages 真实；
   tokens/api_calls/errors 无 agent 粒度源 → 0（诚实，不伪造）
3. GET /stats/export：真实汇总导出（overview + trends + agents + token 快照）
4. GET /stats/usage：daily_requests 按天会话、total_requests/avg_response_time/error_rate 真实
"""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import stats as stats_endpoint
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
    def __init__(self, sessions):
        self._sessions = sessions

    def list_sessions(self, agent_id: str = "", user_id: str = ""):
        if agent_id:
            return [s for s in self._sessions if s.get("agent_id") == agent_id]
        return self._sessions


class FakeAgent:
    def __init__(self, name="Nova", status="active"):
        self.name = name
        self.status = status


def _sessions(days=7):
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return [
        {"session_id": "a1", "agent_id": "default", "created_at": f"{today}T10:00:00", "total_messages": 5},
        {"session_id": "a2", "agent_id": "default", "created_at": f"{today}T11:00:00", "total_messages": 3},
        {"session_id": "a3", "agent_id": "alt", "created_at": f"{yesterday}T09:00:00", "total_messages": 1},
    ]


def _patch_sources(monkeypatch):
    monkeypatch.setattr(
        "neurova.session_repository.get_session_repository",
        lambda: FakeSessionRepo(_sessions()),
    )
    monkeypatch.setattr(
        "neurova.api.endpoints.stats.get_app_state",
        lambda: {"agents": {"default": FakeAgent("Nova", "active"), "alt": FakeAgent("Alto", "idle")},
                 "start_time": time.time() - 100},
    )
    monkeypatch.setattr("neurova.api.endpoints.home._real_token_stats", lambda: {"calls": 7, "tokens": 900})
    monkeypatch.setattr("neurova.api.endpoints.home._sum_agent_persist_counts", lambda: 65)
    monkeypatch.setattr(
        "neurova.api.endpoints.analytics._read_llm_metrics",
        lambda: {"total_calls": 4, "failed_calls": 1, "avg_latency_ms": 200.0,
                 "p95_latency_ms": 300.0, "by_model": []},
    )


class TestSystemStatsReal:
    """/stats overview 必须全部来自真实源。"""

    @pytest.mark.asyncio
    async def test_overview_from_real_sources(self, monkeypatch):
        _patch_sources(monkeypatch)

        res = await stats_endpoint.get_system_stats(MagicMock())

        assert res["overview"]["agents"] == 2
        assert res["overview"]["conversations"] == 3
        assert res["overview"]["memories"] == 65
        assert res["overview"]["tokens"] == 900
        assert res["overview"]["api_calls"] == 7
        assert res["overview"]["errors"] == 1  # LLM 失败次数（真实失败计数）
        assert res["overview"]["uptime"] > 0

        # trends：7 天序列，最后一天 2 条会话
        labels = [t["label"] for t in res["trends"]]
        values = [t["value"] for t in res["trends"]]
        assert len(labels) == 7
        assert values[-1] == 2
        assert values[-2] == 1

    @pytest.mark.asyncio
    async def test_source_failure_degrades_to_zero(self, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("down")

        monkeypatch.setattr("neurova.session_repository.get_session_repository", boom)
        monkeypatch.setattr("neurova.api.endpoints.stats.get_app_state", boom)
        monkeypatch.setattr("neurova.api.endpoints.home._real_token_stats", boom)
        monkeypatch.setattr("neurova.api.endpoints.home._sum_agent_persist_counts", boom)

        res = await stats_endpoint.get_system_stats(MagicMock())

        assert res["overview"]["conversations"] == 0
        assert res["overview"]["memories"] == 0
        assert res["overview"]["tokens"] == 0


class TestAgentStatsReal:
    """/stats/agents 按 agent 真实聚合会话；无粒度源字段诚实为 0。"""

    @pytest.mark.asyncio
    async def test_agents_aggregate_sessions_per_agent(self, monkeypatch):
        _patch_sources(monkeypatch)

        res = await stats_endpoint.get_agents_stats(MagicMock())

        by_id = {a["id"]: a for a in res}
        assert set(by_id) == {"default", "alt"}
        assert by_id["default"]["conversations"] == 2
        assert by_id["default"]["messages"] == 8
        assert by_id["default"]["status"] == "active"
        assert by_id["alt"]["conversations"] == 1
        assert by_id["alt"]["messages"] == 1
        assert by_id["alt"]["status"] == "idle"
        # 无 agent 粒度 token/调用/错误源 → 诚实 0
        assert by_id["default"]["tokens"] == 0
        assert by_id["default"]["api_calls"] == 0
        assert by_id["default"]["errors"] == 0


class TestExportEndpoint:
    """/stats/export 返回真实汇总（前端导出 blob 契约）。"""

    @pytest.mark.asyncio
    async def test_export_contains_real_aggregates(self, monkeypatch):
        _patch_sources(monkeypatch)

        res = await stats_endpoint.export_stats(MagicMock())

        assert res["overview"]["conversations"] == 3
        assert res["overview"]["memories"] == 65
        assert len(res["trends"]) == 7
        assert len(res["agents"]) == 2
        assert "token_usage" in res


class TestUsageEndpointReal:
    """/stats/usage 去掉 TODO：daily_requests 真实按天、错误率/响应时间来自 prometheus。"""

    @pytest.mark.asyncio
    async def test_usage_is_real(self, monkeypatch):
        _patch_sources(monkeypatch)

        res = await stats_endpoint.get_usage_stats(MagicMock())

        assert res["total_requests"] == 4  # LLM 调用总数（prometheus）
        assert res["error_rate"] == 25.0  # 1/4
        assert res["avg_response_time"] == 200.0
        today = datetime.now().strftime("%m-%d")  # 短标签与 /home/trends 一致
        assert res["daily_requests"][today] == 2
