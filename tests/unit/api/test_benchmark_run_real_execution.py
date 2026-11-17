# -*- coding: utf-8 -*-
"""N3：benchmark /run 真评测执行器端点集成。

契约：
- 已接任务库的 suite（reasoning-v1）→ 真执行：LLM 逐任务作答、真实 score 落库、
  simulated=False；执行形态为后台执行+状态查询（POST 即返 running，
  GET /runs/{run_id} 轮询终态）；
- simulated 语义保留：显式 config.simulated 或未接库 suite（multimodal-v1）仍模拟；
- 无 LLM 通道 → 503 诚实拒绝，不伪造回答；
- LLM 单任务异常 → 该任务失败事实入 per_task，run 仍 completed，不谎报；
- 聚合端点（/agents/{id}、/compare）对真实分数出真实均值（R3 None 安全兼容）。
LLM 通道以 monkeypatch 替身注入（可控假 LLM），判分口径与种子任务库解耦。
"""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import benchmark as benchmark_module
from neurova.benchmark.suite_eval import getSuiteTasks


@pytest.fixture(autouse=True)
def _isolatedStores():
    saved_runs = dict(benchmark_module._RUNS_STORE)
    saved_user_runs = {k: list(v) for k, v in benchmark_module._USER_RUNS.items()}
    yield
    benchmark_module._RUNS_STORE.clear()
    benchmark_module._RUNS_STORE.update(saved_runs)
    benchmark_module._USER_RUNS.clear()
    benchmark_module._USER_RUNS.update(saved_user_runs)


def _make_client():
    app = FastAPI()
    app.include_router(benchmark_module.router, prefix="/api/v1/benchmark")
    from neurova.api.auth import get_current_user as _gcu

    app.dependency_overrides[_gcu] = lambda: {
        "user_id": "n3user", "username": "n3user", "role": "admin", "neuser_id": "n3user",
    }
    return TestClient(app)


def _goldByPrompt(suiteId: str) -> dict:
    """从种子任务库提取 gold（exactAnswer 判据 details 自带），构造可控假 LLM。"""
    return {t.prompt: str(t.check("")[2].get("gold", "")) for t in getSuiteTasks(suiteId)}


def _patchLlm(monkeypatch, fn):
    monkeypatch.setattr(benchmark_module, "_rag_llm_fn", lambda agentId: fn)


def _waitForRun(client, runId: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/api/v1/benchmark/runs/{runId}")
        assert resp.status_code == 200, resp.text
        last = resp.json()["data"]
        if last.get("status") != "running":
            return last
        time.sleep(0.05)
    raise AssertionError(f"run 未在 {timeout}s 内完成: {last}")


# ── 真执行 ─────────────────────────────────────────────────────────

def testRunWiredSuiteExecutesReally(monkeypatch):
    gold = _goldByPrompt("reasoning-v1")
    _patchLlm(monkeypatch, lambda prompt: gold.get(prompt, ""))
    client = _make_client()

    resp = client.post("/api/v1/benchmark/run", json={"suite_id": "reasoning-v1", "agent_id": "agent-n3"})
    assert resp.status_code == 200, resp.text
    started = resp.json()["data"]
    # POST 返回的是运行快照：替身 LLM 极快时后台线程可能已完成，两种状态均合法
    assert started["status"] in {"running", "completed"}
    assert started["simulated"] is False
    assert started["tasks_total"] == len(getSuiteTasks("reasoning-v1"))

    run = _waitForRun(client, started["run_id"])
    assert run["status"] == "completed"
    assert run["simulated"] is False
    assert run["score"] == pytest.approx(1.0)
    assert run["tasks_correct"] == run["tasks_total"]
    assert run["avg_latency_ms"] is not None
    assert all(row["passed"] for row in run["per_task"])


def testRunPartialScoreHonest(monkeypatch):
    gold = _goldByPrompt("reasoning-v1")
    correctPrompts = set(list(gold.keys())[:2])  # 只答对前两题

    def fake(prompt: str) -> str:
        return gold[prompt] if prompt in correctPrompts else "必然错误的答案"

    _patchLlm(monkeypatch, fake)
    client = _make_client()
    resp = client.post("/api/v1/benchmark/run", json={"suite_id": "reasoning-v1", "agent_id": "agent-n3"})
    run = _waitForRun(client, resp.json()["data"]["run_id"])

    total = len(gold)
    assert run["status"] == "completed"
    assert run["tasks_total"] == total
    assert run["tasks_correct"] == 2
    assert run["score"] == pytest.approx(2 / total)


def testLlmErrorTaskFailsRunStillCompletes(monkeypatch):
    gold = _goldByPrompt("reasoning-v1")
    badPrompt = next(p for p in gold if "数列" in p)

    def fake(prompt: str) -> str:
        if prompt == badPrompt:
            raise RuntimeError("channel down")
        return gold[prompt]

    _patchLlm(monkeypatch, fake)
    client = _make_client()
    resp = client.post("/api/v1/benchmark/run", json={"suite_id": "reasoning-v1", "agent_id": "agent-n3"})
    run = _waitForRun(client, resp.json()["data"]["run_id"])

    total = len(gold)
    assert run["status"] == "completed"  # run 本身完成，失败事实如实记录
    assert run["tasks_correct"] == total - 1
    assert run["score"] == pytest.approx((total - 1) / total)
    badRows = [r for r in run["per_task"] if r["error"]]
    assert len(badRows) == 1 and "RuntimeError" in badRows[0]["error"] and "channel down" in badRows[0]["error"]


def testNoLlmChannelHonest503(monkeypatch):
    _patchLlm(monkeypatch, None)
    client = _make_client()
    resp = client.post("/api/v1/benchmark/run", json={"suite_id": "reasoning-v1", "agent_id": "agent-n3"})
    assert resp.status_code == 503, resp.text
    # 拒绝后不得留下半截运行记录
    assert benchmark_module._USER_RUNS.get("anonymous", []) == [] or all(
        benchmark_module._RUNS_STORE[rid].get("status") != "running"
        for rid in benchmark_module._USER_RUNS.get("anonymous", [])
    )


# ── simulated 语义保留 ─────────────────────────────────────────────

def testExplicitSimulatedPreserved():
    client = _make_client()
    resp = client.post(
        "/api/v1/benchmark/run",
        json={"suite_id": "reasoning-v1", "agent_id": "agent-n3", "config": {"simulated": True}},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "simulated"
    assert data["simulated"] is True
    assert data["score"] is None
    assert data["tasks_correct"] is None
    assert data["avg_latency_ms"] is None


def testUnwiredSuiteStillSimulated():
    client = _make_client()
    resp = client.post("/api/v1/benchmark/run", json={"suite_id": "multimodal-v1", "agent_id": "agent-n3"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "simulated"
    assert data["simulated"] is True
    assert data["score"] is None


def testSuitesExposeWiredStatus():
    client = _make_client()
    suites = client.get("/api/v1/benchmark/suites").json()["data"]["suites"]
    byId = {s["id"]: s for s in suites}
    assert byId["reasoning-v1"]["wired"] is True
    assert byId["reasoning-v1"]["executable_tasks"] == len(getSuiteTasks("reasoning-v1"))
    assert byId["multimodal-v1"]["wired"] is False
    assert byId["multimodal-v1"]["executable_tasks"] == 0


# ── 聚合端点吃真实分数 ─────────────────────────────────────────────

def testAggregationReflectsRealScores(monkeypatch):
    gold = _goldByPrompt("reasoning-v1")
    _patchLlm(monkeypatch, lambda prompt: gold.get(prompt, ""))
    client = _make_client()

    resp = client.post("/api/v1/benchmark/run", json={"suite_id": "reasoning-v1", "agent_id": "agent-good"})
    run = _waitForRun(client, resp.json()["data"]["run_id"])
    assert run["score"] is not None

    # 对照组：simulated 运行（score 恒 None）
    client.post(
        "/api/v1/benchmark/run",
        json={"suite_id": "reasoning-v1", "agent_id": "agent-sim", "config": {"simulated": True}},
    )

    agg = client.get("/api/v1/benchmark/agents/agent-good").json()["data"]
    assert agg["total"] == 1
    assert agg["avg_score"] == pytest.approx(run["score"])
    assert agg["best_score"] == pytest.approx(run["score"])

    comparison = client.post(
        "/api/v1/benchmark/compare", json={"agent_ids": ["agent-good", "agent-sim"]}
    ).json()["data"]["comparison"]
    assert comparison["agent-good"]["avg_score"] == pytest.approx(run["score"])
    assert comparison["agent-good"]["runs"] == 1
    assert comparison["agent-sim"]["avg_score"] is None  # simulated 不编造
    assert comparison["agent-sim"]["runs"] == 1
