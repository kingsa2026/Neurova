"""知识库冗余审计只读端点（P0-2a）。

契约：
- 管理员可读重复内容组；非管理员 403；
- 端点是只读报告，不删除、不改条目；
- 重复组按内容身份聚合，同一内容两行 = redundant_rows 1。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}
PREFIX = "/v1/knowledge"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr("neurova.knowledge.repository.get_knowledge_repository", lambda: repo)
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": dict(ALICE)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    return TestClient(app), holder, repo


def _create(client, title, content):
    resp = client.post(PREFIX, json={"title": title, "content": content})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_admin_reads_redundancy_report(api):
    client, holder, _repo = api
    _create(client, "dup-a", "same body")
    _create(client, "dup-b", "same body")

    holder["user"] = dict(ADMIN)
    resp = client.get(PREFIX + "/audit/redundancy")

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["total_rows"] == 2
    assert data["distinct_content_keys"] == 1
    assert data["redundant_rows"] == 1
    assert data["duplicate_group_count"] == 1
    assert data["groups"][0]["count"] == 2


def test_non_admin_gets_403(api):
    client, _holder, _repo = api

    resp = client.get(PREFIX + "/audit/redundancy")

    assert resp.status_code == 403


def test_report_is_read_only(api):
    client, holder, repo = api
    item = _create(client, "only-one", "unique body")

    holder["user"] = dict(ADMIN)
    resp = client.get(PREFIX + "/audit/redundancy")
    assert resp.status_code == 200

    assert repo.get_item("default", item["knowledge_id"]) is not None
    assert repo.list_deleted() == []


def test_retrieval_metrics_admin_and_403(api, tmp_path, monkeypatch):
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
    from neurova.knowledge.retrieval_metrics import reset_retrieval_metrics

    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store
    )
    reset_retrieval_metrics()
    try:
        client, holder, _repo = api
        holder["user"] = dict(ADMIN)
        resp = client.get(PREFIX + "/audit/retrieval-metrics")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["retrieval"]["measure_state"] == "unevidenced"
        assert data["lifecycle"]["active"] >= 0
        assert data["pending_conflicts"] == 0
        assert "refusal_rate" in data["retrieval"]["uninstrumented"]
        assert "human_takeover_rate" in data["retrieval"]["uninstrumented"]
        assert data["retrieval"]["outcomes"]["model_refusal"] == 0
        assert "total" in data["token_usage"]
        assert data["knowledge_token_usage"]["events"] == 0
        assert data["knowledge_token_usage"]["attribution"] is None
        assert data["knowledge_token_usage"]["turn_totals"]["turns"] == 0

        holder["user"] = dict(ALICE)
        assert client.get(PREFIX + "/audit/retrieval-metrics").status_code == 403
    finally:
        store.close()


def test_expiry_audit_dry_run_and_apply(api):
    client, holder, _repo = api
    item = _create(client, "due-doc", "due body")
    holder["user"] = dict(ADMIN)
    resp = client.put(
        PREFIX + "/" + item["knowledge_id"],
        json={"valid_until": "2000-01-01T00:00:00+00:00"},
    )
    assert resp.status_code == 200, resp.text

    dry = client.post(PREFIX + "/audit/expiry", json={"apply": False})
    assert dry.status_code == 200, dry.text
    assert dry.json()["data"]["due"] == 1
    assert dry.json()["data"]["archived"] == 0

    applied = client.post(PREFIX + "/audit/expiry", json={"apply": True})
    assert applied.status_code == 200, applied.text
    assert applied.json()["data"]["archived"] == 1

    detail = client.get(PREFIX + "/" + item["knowledge_id"])
    assert detail.status_code == 200
    assert detail.json()["lifecycle_status"] == "archived"

    holder["user"] = dict(ALICE)
    assert client.post(PREFIX + "/audit/expiry", json={"apply": False}).status_code == 403


def test_reindex_admin_and_403(api, tmp_path, monkeypatch):
    from neurova.knowledge.vector_index import KnowledgeVectorIndex

    idx = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=None)
    monkeypatch.setattr(
        "neurova.knowledge.vector_index.get_knowledge_vector_index", lambda: idx
    )
    client, holder, _repo = api

    holder["user"] = dict(ADMIN)
    resp = client.post(PREFIX + "/audit/reindex", json={"force": False})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "repository" in data and "vector" in data

    holder["user"] = dict(ALICE)
    assert client.post(PREFIX + "/audit/reindex", json={"force": False}).status_code == 403


def test_index_health_admin_and_403(api, tmp_path, monkeypatch):
    from neurova.knowledge.vector_index import KnowledgeVectorIndex

    idx = KnowledgeVectorIndex(str(tmp_path / "vec"), engine=None)
    monkeypatch.setattr(
        "neurova.knowledge.vector_index.get_knowledge_vector_index", lambda: idx
    )
    client, holder, _repo = api

    holder["user"] = dict(ADMIN)
    resp = client.get(PREFIX + "/audit/index-health")
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["vector"]["files"] == 0
    assert "docs" in resp.json()["data"]["fts"]

    holder["user"] = dict(ALICE)
    assert client.get(PREFIX + "/audit/index-health").status_code == 403


def test_lifecycle_audit_admin_and_403(api):
    client, holder, _repo = api
    item = _create(client, "to-archive", "archive body")
    holder["user"] = dict(ALICE)
    resp = client.put(
        PREFIX + "/" + item["knowledge_id"],
        json={"lifecycle_status": "archived"},
    )
    assert resp.status_code == 200, resp.text

    holder["user"] = dict(ADMIN)
    resp = client.get(PREFIX + "/audit/lifecycle")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["counts"]["archived"] >= 1

    holder["user"] = dict(ALICE)
    assert client.get(PREFIX + "/audit/lifecycle").status_code == 403
