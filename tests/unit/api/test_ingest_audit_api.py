# -*- coding: utf-8 -*-
"""入站审计端点：只报进程内真实计数，且仅管理员可见。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "t1"}
USER = {"user_id": "1", "username": "alice", "role": "user", "tenant_id": "t1"}


class _Bridge:
    def __init__(self):
        self.drained = 0

    def stats(self):
        return {"accepted": 2, "duplicate": 1, "failed": 0, "skipped": 3,
                "queue": {"pending": 0},
                "topics": {"kb/ingest/wecom": 1, "kb/ingest/result": 0}}

    async def drainPending(self, limit=20):
        self.drained += 1
        return [{"status": "accepted"}]


class _Repo:
    def documentStats(self, tenantId="default"):
        return {"document_count": 2, "ocr_document_count": 1, "ocr_coverage": 0.5,
                "page_count": 3, "chunk_count": 4, "ocr_confidence_avg": 0.9,
                "missing_reason": ""}


@pytest.fixture()
def api(monkeypatch):
    stub = _Bridge()
    monkeypatch.setattr(
        "neurova.api.endpoints.knowledge_core.get_repository", lambda: _Repo()
    )
    monkeypatch.setattr(
        "neurova.knowledge.ingest_bridge.get_ingest_bridge", lambda: stub
    )
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix="/v1/knowledge")
    holder = {"user": dict(ADMIN)}
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service
    ] = lambda: holder["user"]
    return TestClient(app), holder, stub


def testAdminSeesProcessCounts(api):
    client, _holder, _stub = api

    resp = client.get("/v1/knowledge/audit/ingest")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["accepted"] == 2 and data["duplicate"] == 1
    assert data["topics"]["kb/ingest/wecom"] == 1
    assert "backlog" not in data


def testNonAdmin403(api):
    client, holder, _stub = api
    holder["user"] = dict(USER)

    assert client.get("/v1/knowledge/audit/ingest").status_code == 403


def testAdminResumesPendingJobs(api):
    client, _holder, stub = api

    resp = client.post("/v1/knowledge/audit/ingest/resume?limit=5")

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["processed"] == 1
    assert stub.drained == 1
