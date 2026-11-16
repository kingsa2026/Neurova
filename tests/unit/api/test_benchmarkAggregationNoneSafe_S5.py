"""P1-8 红灯：benchmark 聚合端点对 None 分数求和必 TypeError→500。

run_benchmark（诚实化后）产出的运行 score/avg_latency_ms 恒为 None；
GET /benchmark/agents/{id} 与 POST /benchmark/compare 直接 sum/max 这些
None 必炸。修复判据：过滤 None，无可聚合值时如实返回 None（不编造 0 分）。
"""

import asyncio
import types

import pytest

from neurova.api.endpoints import benchmark as benchmark_module


def _makeRequest(user_id: str = "s5-user"):
    return types.SimpleNamespace(state=types.SimpleNamespace(user_id=user_id))


def _seedRun(agent_id: str, user_id: str = "s5-user", score=None, latency_ms=None, suite_id="reasoning-v1"):
    run_id = f"run_{agent_id}_{score}_{latency_ms}"
    benchmark_module._RUNS_STORE[run_id] = {
        "run_id": run_id,
        "suite_id": suite_id,
        "agent_id": agent_id,
        "user_id": user_id,
        "status": "simulated",
        "score": score,
        "avg_latency_ms": latency_ms,
        "started_at": "2026-11-16T00:00:00+00:00",
    }
    benchmark_module._USER_RUNS.setdefault(user_id, []).append(run_id)
    return run_id


@pytest.fixture(autouse=True)
def _isolatedStores():
    saved_runs = dict(benchmark_module._RUNS_STORE)
    saved_user_runs = {k: list(v) for k, v in benchmark_module._USER_RUNS.items()}
    yield
    benchmark_module._RUNS_STORE.clear()
    benchmark_module._RUNS_STORE.update(saved_runs)
    benchmark_module._USER_RUNS.clear()
    benchmark_module._USER_RUNS.update(saved_user_runs)


def testAgentBenchmarkAllNoneScoreReturnsHonestNone():
    """有过 simulated 运行（score 恒 None）后聚合端点不得 500，全 None 如实返回 None。"""
    _seedRun("agent-a", score=None, latency_ms=None)

    resp = asyncio.run(
        benchmark_module.get_agent_benchmarks("agent-a", _makeRequest(), page=1, size=20)
    )
    data = resp["data"]
    assert data["total"] == 1
    assert data["avg_score"] is None
    assert data["best_score"] is None


def testAgentBenchmarkMixedScoresFiltersNone():
    """部分有分部分 None 时，只对真实分数聚合。"""
    _seedRun("agent-b", score=None)
    _seedRun("agent-b", score=0.7)
    _seedRun("agent-b", score=0.9)

    resp = asyncio.run(
        benchmark_module.get_agent_benchmarks("agent-b", _makeRequest(), page=1, size=20)
    )
    data = resp["data"]
    assert data["avg_score"] == pytest.approx(0.8)
    assert data["best_score"] == pytest.approx(0.9)


def testAgentBenchmarkNoRunsReturnsNone():
    """无运行记录时不编造 0 分。"""
    resp = asyncio.run(
        benchmark_module.get_agent_benchmarks("agent-none", _makeRequest(), page=1, size=20)
    )
    assert resp["data"]["avg_score"] is None
    assert resp["data"]["best_score"] is None


def testCompareAllNoneScoreAndLatencyReturnsHonestNone():
    """POST /benchmark/compare 同款 sum/max(None) 与 avg_latency_ms 键值 None 同炸，一并收口。"""
    _seedRun("agent-c", score=None, latency_ms=None)

    resp = asyncio.run(
        benchmark_module.compare_agents(
            {"agent_ids": ["agent-c", "agent-d"]}, _makeRequest()
        )
    )
    comparison = resp["data"]["comparison"]
    assert comparison["agent-c"]["runs"] == 1
    assert comparison["agent-c"]["avg_score"] is None
    assert comparison["agent-c"]["best_score"] is None
    assert comparison["agent-c"]["avg_latency_ms"] is None
    # 无运行记录的 agent 不编造 0 分
    assert comparison["agent-d"]["runs"] == 0
    assert comparison["agent-d"]["avg_score"] is None


def testComparePartialScoresAndLatency():
    """compare 对真实分数/延迟正常聚合。"""
    _seedRun("agent-e", score=0.5, latency_ms=100.0)
    _seedRun("agent-e", score=0.9, latency_ms=None)
    _seedRun("agent-e", score=None, latency_ms=300.0)

    resp = asyncio.run(
        benchmark_module.compare_agents(
            {"agent_ids": ["agent-e", "agent-f"]}, _makeRequest()
        )
    )
    row = resp["data"]["comparison"]["agent-e"]
    assert row["avg_score"] == pytest.approx(0.7)
    assert row["best_score"] == pytest.approx(0.9)
    assert row["avg_latency_ms"] == pytest.approx(200.0)
