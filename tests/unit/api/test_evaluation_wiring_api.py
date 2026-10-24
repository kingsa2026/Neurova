# -*- coding: utf-8 -*-
"""评测入口接线：变体对照与带标签冲突度量端点。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module

ADMIN = {"user_id": "9", "username": "a", "role": "admin", "tenant_id": "t1"}
USER = {"user_id": "1", "username": "u", "role": "user", "tenant_id": "t1"}


class _Bench:
    def runById(self, runId):
        return {
            "run_id": runId,
            "case_count": 40,
            "recall_at_k": 0.8 if runId == "b" else 0.5,
            "mrr": 0.7,
            "ndcg_at_k": 0.7 if runId == "b" else 0.5,
            "unhit_rate": 0.2,
            "variant": runId,
        }

    def compareVariants(self, runA, runB, minCases=30):
        return {"verdict": "improved", "deltas": {"recall_at_k": 0.3}}


@pytest.fixture()
def api(monkeypatch):
    records = [
        {"conflict_id": "c1", "decision": "similar"},
        {"conflict_id": "c2", "decision": "conflict"},
    ]
    repo = SimpleNamespace(conflictRecords=lambda tenantId=None: records)
    monkeypatch.setattr("neurova.api.endpoints.knowledge_core.get_repository", lambda: repo)
    monkeypatch.setattr(
        "neurova.knowledge.evaluation.retrieval_benchmark.get_retrieval_benchmark",
        lambda: _Bench(),
    )
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix="/v1/knowledge")
    holder = {"user": dict(ADMIN)}
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service
    ] = lambda: holder["user"]
    return TestClient(app), holder


def testCompareRunsEndpoint(api):
    client, _holder = api

    resp = client.post("/v1/knowledge/audit/evaluation/compare",
                       json={"run_a": "a", "run_b": "b"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["verdict"] == "improved"


def testLabeledConflictMetricsEndpoint(api):
    client, _holder = api

    resp = client.post("/v1/knowledge/audit/conflict-metrics", json={
        "labels": {"c1": "conflict", "c2": "conflict"},
    })

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["labeled_count"] == 2
    assert data["false_merge_rate"] == 1.0


def testNonAdmin403(api):
    client, holder = api
    holder["user"] = dict(USER)

    assert client.post("/v1/knowledge/audit/evaluation/compare",
                       json={"run_a": "a", "run_b": "b"}).status_code == 403
    assert client.post("/v1/knowledge/audit/conflict-metrics",
                       json={"labels": {}}).status_code == 403
