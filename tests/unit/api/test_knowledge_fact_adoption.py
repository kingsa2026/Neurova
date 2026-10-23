"""知识事实采纳结果显式写回（管理端）。

不把聊天 like/dislike 猜成某条事实的 success/failure；调用方必须显式给 fact_id。
"""
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
def api(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store
    )
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": dict(ADMIN)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    fact_id = store.upsertFact(
        "default", "subject", "predicate", "object", "statement",
        recordKind="narrative",
    )
    yield TestClient(app), holder, store, fact_id
    store.close()


def test_admin_records_adoption(api):
    client, _holder, store, fact_id = api

    resp = client.post(
        PREFIX + "/facts/%s/adoption" % fact_id, json={"outcome": "success"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["outcome"] == "success"
    assert store.fact(fact_id)["adoption_outcome"] == "success"


def test_non_admin_gets_403(api):
    client, holder, store, fact_id = api
    holder["user"] = dict(ALICE)

    resp = client.post(
        PREFIX + "/facts/%s/adoption" % fact_id, json={"outcome": "failure"}
    )

    assert resp.status_code == 403
    assert store.fact(fact_id)["adoption_outcome"] is None


def test_unknown_fact_404(api):
    client, _holder, _store, _fact_id = api

    resp = client.post(
        PREFIX + "/facts/does-not-exist/adoption", json={"outcome": "success"}
    )

    assert resp.status_code == 404


def test_invalid_outcome_422(api):
    client, _holder, _store, fact_id = api

    resp = client.post(
        PREFIX + "/facts/%s/adoption" % fact_id, json={"outcome": "probably_fine"}
    )

    assert resp.status_code == 422
