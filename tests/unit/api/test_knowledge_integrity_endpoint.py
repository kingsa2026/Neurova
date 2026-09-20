"""溯源链完整性巡检端点（工单 023 / G02 的用户可见面）。

巡检必须"可读"才算闭环：链只在库里算、没人看得到的话，G02 与没做无异。
"""

from __future__ import annotations

import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_integrity_0123456789")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user_or_service
from neurova.api.endpoints import knowledge_core
from neurova.knowledge.foundation import knowledge_facts as kf
from neurova.knowledge.foundation.digest_chain import ActivityDigestChain
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_core.router, prefix="/api/v1/knowledge")
    app.dependency_overrides[get_current_user_or_service] = lambda: {"user_id": "u1",
                                                                    "role": "admin"}
    return TestClient(app)


@pytest.fixture
def isolatedStore(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(kf, "get_knowledge_fact_store", lambda *a, **k: store)
    monkeypatch.setattr("neurova.knowledge.foundation.get_knowledge_fact_store",
                        lambda *a, **k: store)
    yield store
    store.close()


def _seed(store, texts=("甲说了这句", "乙说了那句")):
    key = store.upsertSubject("default", "被引用的事实")
    factId = store.upsertFact(agentId="default", subjectKey=key, predicateTermId="probe",
                              objectTerm="o", content="c")
    ledger = KnowledgeLineageLedger(store, toolVersion="api-test")
    activityId = ledger.openActivity("admit")
    for text in texts:
        ledger.attach(factId, [{"actorType": "user", "actorId": "u1",
                               "statementText": text, "mediumRef": "unit:test"}],
                     activityId=activityId)
    return activityId


def test_cleanChainReportsOk(isolatedStore):
    _seed(isolatedStore)

    body = _client().get("/api/v1/knowledge/foundation/integrity").json()

    assert body["ok"] is True
    assert body["chains"] == 1 and body["rows"] == 2 and body["break"] is None


def test_tamperedAssertionSurfacesWithItsPosition(isolatedStore):
    activityId = _seed(isolatedStore)
    with isolatedStore._lock, isolatedStore._conn:
        isolatedStore._conn.execute(
            "UPDATE knowledge_assertions SET statement_text = '事后被人改过'"
            " WHERE activity_id = ? AND seq = 2", (activityId,))

    body = _client().get("/api/v1/knowledge/foundation/integrity").json()

    assert body["ok"] is False
    assert body["break"]["activity_id"] == activityId
    assert body["break"]["seq"] == 2 and body["break"]["reason"] == "正文与哈希不符"


def test_emptyStoreIsReportedAsNothingCheckedNotBroken(isolatedStore):
    body = _client().get("/api/v1/knowledge/foundation/integrity").json()

    assert body == {"ok": True, "chains": 0, "rows": 0, "unlinked": 0, "break": None}


def test_endpointUsesTheSameReadingAsTheLedgerItself(isolatedStore):
    _seed(isolatedStore, texts=("只有这一条",))

    viaHttp = _client().get("/api/v1/knowledge/foundation/integrity").json()
    viaChain = ActivityDigestChain(isolatedStore).verify()

    assert viaHttp == viaChain, "端点不许自己算一套：两本账就是两个真源"
