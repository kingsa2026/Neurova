# -*- coding: utf-8 -*-
"""冲突标注评估端点：管理员可用，普通用户 403。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "t1"}
USER = {"user_id": "1", "username": "alice", "role": "user", "tenant_id": "t1"}


@pytest.fixture()
def api():
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix="/v1/knowledge")
    holder = {"user": dict(ADMIN)}
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service
    ] = lambda: holder["user"]
    return TestClient(app), holder


def testAdminEvaluatesLabeledCases(api):
    client, _holder = api

    resp = client.post("/v1/knowledge/audit/conflict-eval", json={"cases": [
        {"case_id": "c1", "left": "Alpha budget 100", "right": "Alpha budget 120",
         "expected": "conflict", "vector_similarity": 0.9},
        {"case_id": "c2", "left": "Alpha budget 100", "right": "Beta port 9527",
         "expected": "different", "vector_similarity": 0.9},
    ]})

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["measure_state"] == "measured"
    assert data["evaluated_count"] == 2
    assert data["accuracy"] == 1.0


def testNonAdmin403(api):
    client, holder = api
    holder["user"] = dict(USER)

    resp = client.post("/v1/knowledge/audit/conflict-eval", json={"cases": [
        {"left": "a", "right": "b", "expected": "different"},
    ]})

    assert resp.status_code == 403
