# -*- coding: utf-8 -*-
"""W2 审批端点（specs/2026-10-30 §3.3）：管理员 gated、租户隔离、审批闭环。

契约：GET /v1/knowledge/alias-candidates 列表；POST .../{id}/approve|reject
人工处置；approve 后别名并入主体表并失效查询归一缓存。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}
PREFIX = "/v1/knowledge"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store
    )
    repo = object()  # 端点不触条目仓库；占位防误用
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": dict(ADMIN)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = (
        lambda: holder["user"]
    )
    client = TestClient(app)
    yield client, holder, store
    store.close()


def test_listCandidates_adminOnly(env):
    client, holder, store = env
    store.captureAliasCandidate("a1", "跑量", tenantId="default")
    store.captureAliasCandidate("a1", " churn ", tenantId="default")

    resp = client.get(PREFIX + "/alias-candidates?status=pending")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["count"] == 2
    assert {row["normalized_query"] for row in data["items"]} == {"跑量", "churn"}

    holder["user"] = dict(ALICE)
    assert client.get(PREFIX + "/alias-candidates").status_code == 403


def test_approveFlow_attachesAlias_andClosesCandidate(env):
    client, _holder, store = env
    subjectKey = store.upsertSubject("a1", "客户流失率", tenantId="default")
    candidateId = store.captureAliasCandidate("a1", "跑量", tenantId="default")

    resp = client.post(
        PREFIX + "/alias-candidates/%s/approve" % candidateId,
        json={"subject_key": subjectKey, "reason": "确认是同义"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["subject_key"] == subjectKey
    assert "跑量" in store.subjectFor(subjectKey)["aliases"]
    assert client.get(PREFIX + "/alias-candidates?status=pending").json()["data"][
        "count"
    ] == 0

    again = client.post(
        PREFIX + "/alias-candidates/%s/approve" % candidateId, json={}
    )
    assert again.status_code == 409, "已结候选不许重复处置"


def test_approveWithoutSubjectKey_usesCapturedHint(env):
    client, _holder, store = env
    subjectKey = store.upsertSubject("a1", "客户流失率", aliases=["跑量"], tenantId="default")
    store.upsertSubject("a1", "客户流失率", tenantId="default")
    candidateId = store.captureAliasCandidate("a1", "跑量怎么算", tenantId="default")
    assert store.listAliasCandidates(tenantId="default")[0][
        "proposed_subject_key"
    ] == subjectKey

    resp = client.post(
        PREFIX + "/alias-candidates/%s/approve" % candidateId, json={"reason": "按提示挂"}
    )
    assert resp.status_code == 200, resp.text
    assert "跑量怎么算" in store.subjectFor(subjectKey)["aliases"]


def test_approveWithoutSubjectOrHint_409(env):
    client, _holder, store = env
    candidateId = store.captureAliasCandidate("a1", "没人认领的词", tenantId="default")
    resp = client.post(
        PREFIX + "/alias-candidates/%s/approve" % candidateId, json={}
    )
    assert resp.status_code == 409


def test_approveUnknownCandidate_404(env):
    client, _holder, _store = env
    resp = client.post(
        PREFIX + "/alias-candidates/kbac_nope/approve",
        json={"subject_key": "subj_x"},
    )
    assert resp.status_code == 404


def test_rejectFlow(env):
    client, _holder, store = env
    subjectKey = store.upsertSubject("a1", "客户流失率", tenantId="default")
    candidateId = store.captureAliasCandidate("a1", "跑量", tenantId="default")
    resp = client.post(
        PREFIX + "/alias-candidates/%s/reject" % candidateId,
        json={"reason": "不是别名"},
    )
    assert resp.status_code == 200, resp.text
    assert store.subjectFor(subjectKey)["aliases"] == []
    assert client.get(PREFIX + "/alias-candidates?status=rejected").json()["data"][
        "count"
    ] == 1


def test_tenantScopedListing(env, monkeypatch):
    client, holder, store = env
    store.captureAliasCandidate("a1", "甲租户词", tenantId="t1")
    store.captureAliasCandidate("a1", "乙租户词", tenantId="t2")

    holder["user"] = {**ADMIN, "tenant_id": "t1"}
    data = client.get(PREFIX + "/alias-candidates").json()["data"]
    assert [row["raw_query"] for row in data["items"]] == ["甲租户词"]

    t1Candidate = data["items"][0]["candidate_id"]
    resp = client.post(
        PREFIX + "/alias-candidates/%s/approve" % t1Candidate,
        json={"subject_key": "subj_x"},
    )
    assert resp.status_code == 404, "跨租户处置按不存在处理"
