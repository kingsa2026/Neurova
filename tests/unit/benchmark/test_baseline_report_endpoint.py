# -*- coding: utf-8 -*-
"""S1-1E：多 agent 基线报告只读端点契约。

数据源 = runner 报告落盘（`<NEUROVA_DATA_DIR>/benchmark/multi_agent/*.json`），
端点只读不建新存储；挂在既有 /v1/benchmark 路由前缀下，不新开路由域。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.benchmark.multi_agent.report import buildReport, defaultReportPath, saveReport


def _make_client():
    from neurova.api.auth import get_current_user as _gcu
    from neurova.api.endpoints import benchmark as benchmark_api

    app = FastAPI()
    app.include_router(benchmark_api.router, prefix="/api/v1/benchmark")
    app.dependency_overrides[_gcu] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    return TestClient(app)


def _sampleResult(taskId: str, mode: str, totalTokens: int, steps: int) -> dict:
    return {
        "task_id": taskId, "suite": "t1_sim", "mode": mode, "unsolvable": False,
        "passed": True, "score": 100.0, "details": {}, "error": None, "rejected": False,
        "rejection_code": "", "subagent_id": "", "elapsed_seconds": 0.5, "tokens": totalTokens,
        "effort": "standard", "effort_source": "fallback_standard", "report_snippet": "x",
        "usage": {"promptTokens": totalTokens - 10, "completionTokens": 10,
                  "totalTokens": totalTokens, "elapsedSeconds": 0.5,
                  "steps": steps, "toolCalls": 1},
        "trajectory": {"toolsUsed": ["web_search"], "source": "tool_messages"},
    }


@pytest.fixture
def isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    return tmp_path


def _seedReport(isolatedDataRoot, reportId: str, modes=("solo", "swarm")) -> dict:
    results = [
        _sampleResult("t1-sim-evidence-digest", "solo", 200, 2),
        _sampleResult("t1-sim-evidence-digest", "swarm", 480, 5),
    ]
    from neurova.benchmark.multi_agent.metrics import aggregate, compare

    report = buildReport(results, aggregate(results), compare(results), taskIsolatedMemory=True)
    report["report_id"] = reportId
    path = defaultReportPath(reportId)
    report["report_path"] = path
    saveReport(report, path)
    return report


class TestBaselineReportEndpoints:
    def test_list_and_fetch_baseline_reports(self, isolatedDataRoot):
        _seedReport(isolatedDataRoot, "bench-20261117T100000Z-aaa111")
        _seedReport(isolatedDataRoot, "bench-20261117T110000Z-bbb222")
        client = _make_client()

        resp = client.get("/api/v1/benchmark/baseline-reports")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["total"] == 2
        ids = {item["report_id"] for item in data["items"]}
        assert ids == {"bench-20261117T100000Z-aaa111", "bench-20261117T110000Z-bbb222"}
        # 列表带 usage/轨迹聚合列（分模式 metrics 含步数/工具数总量）
        solo = next(i for i in data["items"] if i["report_id"] == "bench-20261117T110000Z-bbb222")["metrics"]["solo"]
        assert solo["total_steps"] == 2 and solo["total_tool_calls"] == 1
        assert data["items"][0]["task_isolated_memory"] is True

        detail = client.get("/api/v1/benchmark/baseline-reports/bench-20261117T110000Z-bbb222")
        assert detail.status_code == 200
        body = detail.json()["data"]
        assert body["report_id"] == "bench-20261117T110000Z-bbb222"
        assert body["metrics"]["swarm"]["total_tokens"] == 480
        usage = body["tasks"][0]["usage"]
        assert usage["promptTokens"] + usage["completionTokens"] == usage["totalTokens"]
        assert body["tasks"][0]["trajectory"]["toolsUsed"] == ["web_search"]

    def test_missing_baseline_report_404(self, isolatedDataRoot):
        client = _make_client()
        resp = client.get("/api/v1/benchmark/baseline-reports/no-such-report")
        assert resp.status_code == 404

    def test_empty_store_lists_zero(self, isolatedDataRoot):
        client = _make_client()
        resp = client.get("/api/v1/benchmark/baseline-reports")
        assert resp.status_code == 200
        assert resp.json()["data"] == {"items": [], "total": 0}
