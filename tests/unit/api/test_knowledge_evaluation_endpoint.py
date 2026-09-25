"""检索评测基线只读端点（工单 002）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user_or_service
from neurova.api.endpoints import knowledge_core
from neurova.knowledge.evaluation import retrieval_benchmark as rb_mod


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_core.router, prefix="/api/v1/knowledge")
    app.dependency_overrides[get_current_user_or_service] = lambda: {"user_id": "u1", "role": "admin"}
    return TestClient(app)


@pytest.fixture
def isolatedBenchmark(tmp_path, monkeypatch):
    db = str(tmp_path / "eval.db")
    monkeypatch.setattr(rb_mod, "_benchmark_singleton", None)
    monkeypatch.setattr(rb_mod, "DEFAULT_EVAL_DB", db)
    yield rb_mod.get_retrieval_benchmark()
    rb_mod.reset_retrieval_benchmark()


def test_baselineAbsentReportsUnevidencedNotZero(isolatedBenchmark):
    res = _client().get("/api/v1/knowledge/evaluation/baseline")

    assert res.status_code == 200
    body = res.json()
    assert body["measure_state"] == "unevidenced"
    assert body["readings"] is None, "没有基线时不得回 0 读数——0 会被读成'检索很差'"
    assert body["missing_reason"]


def test_baselineFrozenIsReadable(isolatedBenchmark, tmp_path):
    from neurova.knowledge.repository import KnowledgeRepository

    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge("e", "评测条目", "供基线读数使用的条目正文", owner_user_id="u1")
    bench = isolatedBenchmark
    bench.addCase("评测条目", [repo._items["e"][0]["knowledge_id"]])
    report = bench.run(repo, user={"user_id": "u1"}, topK=5)
    bench.freezeBaseline(report)

    body = _client().get("/api/v1/knowledge/evaluation/baseline").json()

    assert body["measure_state"] == "measured"
    assert body["run_id"] == report["run_id"]
    assert body["readings"]["mrr"] == 1.0
    assert body["frozen_at"]
