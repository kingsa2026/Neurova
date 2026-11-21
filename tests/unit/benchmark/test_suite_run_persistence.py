# -*- coding: utf-8 -*-
"""P1-0：suite_eval run 结果落盘持久化（补 `_RUNS_STORE` 进程内断点）。

红→绿契约（docs/04-plans/2026-11-21-recursive-self-evolution-plan.md §1.7 / §6-P1-0）：
- 完成态 run 原子落盘 `<数据根>/benchmark/suite_runs/<run_id>.json`
  （tmp + os.replace，沿 multi_agent report 同款纪律）；
- GET /runs、GET /runs/{run_id} 内存优先、未命中读盘——模拟重启（清空进程内
  台账）后历史仍可读回；
- 盘上坏文件如实跳过：列表不 500、单查如实 404；
- GET /runs 可选 `?limit=` 限制返回条数（内存+盘合并，按 started_at 倒序截断）。

测试纪律：数据根逐测试注入 tmp_path（不写会话共享盘，更不写仓库 data/）；
内存台账快照恢复，不留跨测试痕迹。
"""

import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import benchmark as benchmark_api


@pytest.fixture(autouse=True)
def _isolatedEnv(tmp_path, monkeypatch):
    """数据根逐测试隔离 + 内存台账快照恢复（模拟重启不留跨测试痕迹）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    savedRuns = dict(benchmark_api._RUNS_STORE)
    savedUserRuns = {k: list(v) for k, v in benchmark_api._USER_RUNS.items()}
    yield tmp_path
    benchmark_api._RUNS_STORE.clear()
    benchmark_api._RUNS_STORE.update(savedRuns)
    benchmark_api._USER_RUNS.clear()
    benchmark_api._USER_RUNS.update(savedUserRuns)


def _make_client(userId: str = "tuser") -> TestClient:
    app = FastAPI()
    app.include_router(benchmark_api.router, prefix="/api/v1/benchmark")
    from neurova.api.auth import get_current_user as _gcu

    app.dependency_overrides[_gcu] = lambda: {
        "user_id": userId, "username": userId, "role": "admin", "neuser_id": userId,
    }
    return TestClient(app)


# 本文件用裸 FastAPI 挂路由（沿既有 benchmark 端点测试同款）：身份门已被覆写，
# 但 `_get_user_id` 读的是 `request.state.user_id`——无人写入时回落 "anonymous"。
# 台账种子必须用这个**实际生效身份**，否则内存/盘上的 run 对请求不可见。
_REQ_USER = "anonymous"


def _runsDir() -> Path:
    from neurova.benchmark.suite_run_store import defaultSuiteRunsDir

    return defaultSuiteRunsDir()


class TestSuiteRunStore:
    """落盘件单元契约：原子写、可读回、坏文件不炸。"""

    def test_saveAndLoadRoundTrip(self):
        from neurova.benchmark.suite_run_store import loadSuiteRun, saveSuiteRun

        run = {
            "run_id": "r-roundtrip", "suite_id": "reasoning-v1", "user_id": _REQ_USER,
            "status": "completed", "score": 0.5, "started_at": "2026-11-21T10:00:00+00:00",
        }
        path = saveSuiteRun(run)
        assert Path(path).parent == _runsDir()
        assert Path(path).name == "r-roundtrip.json"
        assert loadSuiteRun("r-roundtrip") == run

    def test_saveIsAtomic_noTmpLeftovers(self):
        from neurova.benchmark.suite_run_store import saveSuiteRun

        saveSuiteRun({"run_id": "r-atomic", "user_id": _REQ_USER, "status": "completed"})
        leftovers = [p.name for p in _runsDir().iterdir() if p.name != "r-atomic.json"]
        assert leftovers == [], f"原子写不得残留临时文件: {leftovers}"

    def test_loadMissingReturnsNone(self):
        from neurova.benchmark.suite_run_store import loadSuiteRun

        assert loadSuiteRun("no-such-run") is None


class TestRunPersistenceThroughApi:
    """端到端：完成即落盘；重启（清内存）后 GET 仍可读回盘上 run。"""

    def test_simulatedRunPersisted_andReadableAfterMemoryClear(self):
        client = _make_client()
        resp = client.post("/api/v1/benchmark/run", json={
            "suite_id": "reasoning-v1", "agent_id": "agent-p10",
            "config": {"simulated": True},
        })
        assert resp.status_code == 200, resp.text
        runId = resp.json()["data"]["run_id"]

        # 完成态已原子落盘（simulated 在 POST 时即完成）
        assert (_runsDir() / f"{runId}.json").exists(), "run 完成后必须落盘"

        # 模拟重启：清空进程内台账
        benchmark_api._RUNS_STORE.clear()
        benchmark_api._USER_RUNS.clear()

        got = client.get(f"/api/v1/benchmark/runs/{runId}")
        assert got.status_code == 200, got.text
        assert got.json()["data"]["run_id"] == runId
        assert got.json()["data"]["status"] == "simulated"

        listed = client.get("/api/v1/benchmark/runs").json()["data"]
        assert [r["run_id"] for r in listed["items"]] == [runId]
        assert listed["total"] == 1

    def test_realRunPersistedOnCompletion(self, monkeypatch):
        """真执行路径：后台线程把终态写回内存的同时原子落盘。"""
        fakeReport = {
            "status": "completed", "score": 1.0, "tasks_total": 2, "tasks_correct": 2,
            "avg_latency_ms": 12.5, "per_task": [],
            "executed_at": "2026-11-21T10:00:00+00:00",
        }
        monkeypatch.setattr(
            benchmark_api, "_rag_llm_fn", lambda agentId: (lambda prompt: "答案")
        )
        import neurova.benchmark.suite_eval as suiteEval

        monkeypatch.setattr(suiteEval, "runSuite", lambda *args, **kwargs: dict(fakeReport))
        monkeypatch.setattr(suiteEval, "getSuiteTasks", lambda suiteId: [object(), object()])

        client = _make_client()
        resp = client.post("/api/v1/benchmark/run", json={
            "suite_id": "reasoning-v1", "agent_id": "agent-p10",
        })
        assert resp.status_code == 200, resp.text
        runId = resp.json()["data"]["run_id"]

        deadline = time.time() + 10
        status = None
        while time.time() < deadline:
            status = client.get(f"/api/v1/benchmark/runs/{runId}").json()["data"]["status"]
            if status != "running":
                break
            time.sleep(0.02)
        assert status == "completed", status

        # 终态落盘（落盘在工作线程内存回写之后一瞬，轮询等待文件出现）；
        # 随后清空内存，验证盘上 run 仍可读回真实分数
        deadline = time.time() + 5
        while time.time() < deadline and not (_runsDir() / f"{runId}.json").exists():
            time.sleep(0.02)
        assert (_runsDir() / f"{runId}.json").exists(), "终态 run 必须落盘"
        benchmark_api._RUNS_STORE.clear()
        benchmark_api._USER_RUNS.clear()
        got = client.get(f"/api/v1/benchmark/runs/{runId}")
        assert got.status_code == 200, got.text
        assert got.json()["data"]["score"] == 1.0

    def test_corruptDiskFileSkipped_not500(self):
        """盘上坏文件：列表如实跳过不阻断，单查如实 404，均不 500。"""
        from neurova.benchmark.suite_run_store import saveSuiteRun

        saveSuiteRun({"run_id": "r-good", "user_id": _REQ_USER, "status": "completed",
                      "started_at": "2026-11-21T10:00:00+00:00"})
        (_runsDir() / "r-broken.json").write_text("{not-json{{{", encoding="utf-8")

        client = _make_client()
        listed = client.get("/api/v1/benchmark/runs")
        assert listed.status_code == 200, listed.text
        assert [r["run_id"] for r in listed.json()["data"]["items"]] == ["r-good"]

        single = client.get("/api/v1/benchmark/runs/r-broken")
        assert single.status_code == 404, single.text

    def test_limitTruncatesMergedListNewestFirst(self):
        """?limit= 截断合并后（内存+盘、按 started_at 倒序）的返回条数。"""
        from neurova.benchmark.suite_run_store import saveSuiteRun

        for idx, ts in enumerate(
            ["2026-11-21T09:00:00+00:00", "2026-11-21T10:00:00+00:00",
             "2026-11-21T11:00:00+00:00"], start=1,
        ):
            saveSuiteRun({"run_id": f"r-disk-{idx}", "user_id": _REQ_USER,
                          "status": "completed", "started_at": ts})
        benchmark_api._RUNS_STORE["r-mem-1"] = {
            "run_id": "r-mem-1", "user_id": _REQ_USER, "status": "completed",
            "started_at": "2026-11-21T12:00:00+00:00",
        }
        benchmark_api._USER_RUNS.setdefault(_REQ_USER, []).append("r-mem-1")

        client = _make_client()
        allRuns = client.get("/api/v1/benchmark/runs").json()["data"]
        assert [r["run_id"] for r in allRuns["items"]] == [
            "r-mem-1", "r-disk-3", "r-disk-2", "r-disk-1",
        ]
        assert allRuns["total"] == 4

        limited = client.get("/api/v1/benchmark/runs", params={"limit": 2}).json()["data"]
        assert [r["run_id"] for r in limited["items"]] == ["r-mem-1", "r-disk-3"]
        assert limited["total"] == 2

        assert client.get("/api/v1/benchmark/runs", params={"limit": 0}).status_code == 422
        assert client.get("/api/v1/benchmark/runs", params={"limit": -3}).status_code == 422

    def test_otherUsersDiskRunHiddenAndForbidden(self):
        """盘上台账同样按 user 隔离：他人 run 不进列表，单查 403。"""
        from neurova.benchmark.suite_run_store import saveSuiteRun

        saveSuiteRun({"run_id": "r-alien", "user_id": "someone-else",
                      "status": "completed", "started_at": "2026-11-21T10:00:00+00:00"})
        client = _make_client("tuser")
        listed = client.get("/api/v1/benchmark/runs").json()["data"]
        assert listed["items"] == []

        resp = client.get("/api/v1/benchmark/runs/r-alien")
        assert resp.status_code == 403, resp.text

    def test_memoryEntryWinsOverStaleDiskCopy(self):
        """同一 run_id 内存与盘并存时以内存为准（内存是最新态）。"""
        from neurova.benchmark.suite_run_store import saveSuiteRun

        saveSuiteRun({"run_id": "r-both", "user_id": _REQ_USER, "status": "running",
                      "started_at": "2026-11-21T10:00:00+00:00"})
        benchmark_api._RUNS_STORE["r-both"] = {
            "run_id": "r-both", "user_id": _REQ_USER, "status": "completed", "score": 0.9,
            "started_at": "2026-11-21T10:00:00+00:00",
        }
        benchmark_api._USER_RUNS.setdefault(_REQ_USER, []).append("r-both")

        client = _make_client()
        listed = client.get("/api/v1/benchmark/runs").json()["data"]
        assert [r["run_id"] for r in listed["items"]] == ["r-both"], "合并须按 run_id 去重"
        got = client.get("/api/v1/benchmark/runs/r-both").json()["data"]
        assert got["status"] == "completed" and got["score"] == 0.9
