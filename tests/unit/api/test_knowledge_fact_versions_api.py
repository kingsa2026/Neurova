# -*- coding: utf-8 -*-
"""事实历史 / 回滚 / 业务基线端点（管理员治理面）。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}
USER = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
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
        "agent-a", "Alpha", "pred.budget", "100万元", "预算金额 100 万元",
        contentKey="ck:Alpha:100万元",
    )
    store.retract(fact_id, reason="来源撤回")
    yield TestClient(app), holder, store, fact_id
    store.close()


def test_admin_readsHistory(api):
    client, _holder, _store, fact_id = api

    resp = client.get(PREFIX + "/facts/%s/history" % fact_id)

    assert resp.status_code == 200, resp.text
    versions = resp.json()["data"]["versions"]
    assert [v["change_type"] for v in versions] == ["retract", "create"]


def test_history_unknownFact_404(api):
    client, _holder, _store, _fact_id = api

    assert client.get(PREFIX + "/facts/nope/history").status_code == 404


def test_admin_rollsBack(api):
    client, _holder, store, fact_id = api

    resp = client.post(
        PREFIX + "/facts/%s/rollback" % fact_id,
        json={"version_no": 1, "reason": "来源恢复"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["fact"]["status"] == "active"
    assert store.fact(fact_id)["status"] == "active"
    assert store.history(fact_id)[0]["change_type"] == "rollback"


def test_rollback_requiresReason(api):
    client, _holder, _store, fact_id = api

    resp = client.post(
        PREFIX + "/facts/%s/rollback" % fact_id, json={"version_no": 1, "reason": ""}
    )

    assert resp.status_code == 422


def test_nonAdmin_gets403(api):
    client, holder, store, fact_id = api
    holder["user"] = dict(USER)

    assert client.get(PREFIX + "/facts/%s/history" % fact_id).status_code == 403
    assert client.post(
        PREFIX + "/facts/%s/rollback" % fact_id,
        json={"version_no": 1, "reason": "越权"},
    ).status_code == 403
    assert store.fact(fact_id)["status"] == "retracted"


def test_baselineCreateAndList(api):
    client, _holder, _store, fact_id = api

    created = client.post(
        PREFIX + "/facts/baselines",
        json={"scope": "agent", "scope_key": "agent-a", "fact_ids": [fact_id],
              "reason": "上线前冻结"},
    )
    assert created.status_code == 200, created.text
    listed = client.get(PREFIX + "/facts/baselines", params={"scope": "agent"})

    assert listed.status_code == 200, listed.text
    baselines = listed.json()["data"]["baselines"]
    assert baselines[0]["baseline_id"] == created.json()["data"]["baseline_id"]
    assert baselines[0]["fact_count"] == 1


def test_crossTenantFactIs404(api):
    client, holder, _store, fact_id = api
    holder["user"] = {"user_id": "8", "username": "other", "role": "admin",
                      "tenant_id": "t2"}

    assert client.get(PREFIX + "/facts/%s/history" % fact_id).status_code == 404
    assert client.post(
        PREFIX + "/facts/%s/rollback" % fact_id,
        json={"version_no": 1, "reason": "跨租户"},
    ).status_code == 404


def test_baselineListDoesNotCrossTenant(api):
    client, holder, _store, fact_id = api
    created = client.post(
        PREFIX + "/facts/baselines",
        json={"fact_ids": [fact_id], "reason": "t1 基线"},
    )
    assert created.status_code == 200, created.text
    holder["user"] = {"user_id": "8", "username": "other", "role": "admin",
                      "tenant_id": "t2"}

    listed = client.get(PREFIX + "/facts/baselines")

    assert listed.status_code == 200
    assert listed.json()["data"]["baselines"] == []


def testHistoryDefaultsToAllAndSupportsExplicitPaging(api):
    client, _holder, _store, fact_id = api

    full = client.get(PREFIX + "/facts/%s/history" % fact_id)
    assert full.status_code == 200
    assert full.json()["data"]["total"] == 2
    assert full.json()["data"]["returned"] == 2

    paged = client.get(PREFIX + "/facts/%s/history?limit=1&offset=1" % fact_id)
    assert paged.status_code == 200
    data = paged.json()["data"]
    assert data["total"] == 2 and data["returned"] == 1
    assert data["versions"][0]["change_type"] == "create"
