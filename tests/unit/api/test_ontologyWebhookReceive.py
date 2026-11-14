# -*- coding: utf-8 -*-
"""P2-9：企业 webhook 入站路由 POST /v1/knowledge/ontology/webhook/receive。

公开路由（无 JWT），由 WebhookReceiver 的 HMAC-SHA256 验签 fail-closed 把关：
签名对→落事实；签名错→拒收且不消耗幂等键；同幂等键重推→deduplicated
零二次写；时间戳窗口外→拒（防重放）。回执是接收器原话（HTTP 恒 200）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

SECRET = "hook-secret-api"
PREFIX = "/v1/knowledge"
URL = f"{PREFIX}/ontology/webhook/receive"


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = KnowledgeFactStore(str(tmp_path / "kb.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store)
    monkeypatch.setenv("NEUROVA_KB_WEBHOOK_ENABLED", "1")
    monkeypatch.setenv("NEUROVA_KB_WEBHOOK_SECRET", SECRET)
    registry = OntologyTermRegistry(store)
    registry.register("orders", "concept", label="订单")
    registry.register("is_a", "relation")

    from neurova.api.endpoints import knowledge_ontology

    app = FastAPI()
    app.include_router(knowledge_ontology.router, prefix=PREFIX)
    yield store, TestClient(app)
    store.close()


def _push(client: TestClient, payload: dict, *, secret: str = SECRET, ts=None,
          signature=None, source: str = "erp:main"):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ts = ts if ts is not None else int(time.time())
    sig = signature if signature is not None else hmac.new(
        secret.encode(), body + str(ts).encode(), hashlib.sha256).hexdigest()
    headers = {"X-Neurova-Signature": sig, "X-Neurova-Timestamp": str(ts),
               "X-Neurova-Source": source}
    return client.post(URL, content=body, headers=headers)


def _activeFactCount(store: KnowledgeFactStore) -> int:
    return store.queryReadOnly(
        "SELECT COUNT(*) AS n FROM knowledge_facts WHERE status = 'active'")[0]["n"]


class TestWebhookReceiveEndpoint:
    def test_validSignatureAdmitsFact(self, env):
        store, client = env
        resp = _push(client, {"subject": "订单R1", "predicate": "is_a",
                              "object": "orders", "idempotency_key": "evt-r1"})
        assert resp.status_code == 200
        receipt = resp.json()["data"]
        assert receipt.get("fact_id"), receipt
        assert _activeFactCount(store) == 1, "合法签名推送落一条事实"

    def test_badSignatureRejectedWithoutFact(self, env):
        store, client = env
        resp = _push(client, {"subject": "订单R2", "predicate": "is_a",
                              "object": "orders", "idempotency_key": "evt-r2"},
                     signature="deadbeef")
        assert resp.status_code == 200
        receipt = resp.json()["data"]
        assert receipt.get("rejected") is True and "签名" in receipt.get("detail", "")
        assert _activeFactCount(store) == 0, "坏签名不落任何事实（fail-closed）"

    def test_replaySameIdempotencyKeyZeroSecondWrite(self, env):
        store, client = env
        payload = {"subject": "订单R3", "predicate": "is_a",
                   "object": "orders", "idempotency_key": "evt-r3"}
        first = _push(client, payload).json()["data"]
        assert first.get("fact_id")
        second = _push(client, payload).json()["data"]
        assert second.get("deduplicated") is True, "重放按幂等键去重"
        assert second.get("fact_id") == first["fact_id"]
        assert _activeFactCount(store) == 1, "重放零二次写"

    def test_staleTimestampRejected(self, env):
        store, client = env
        resp = _push(client, {"subject": "订单R4", "predicate": "is_a",
                              "object": "orders", "idempotency_key": "evt-r4"},
                     ts=1)
        receipt = resp.json()["data"]
        assert receipt.get("rejected") is True, "时间戳窗口外拒收（防重放）"
        assert _activeFactCount(store) == 0

    def test_badSignatureDoesNotConsumeIdempotencyKey(self, env):
        """签名错拒→不消耗幂等键；随后合法重推同键可正常落（与 receiver 契约一致）。"""
        store, client = env
        payload = {"subject": "订单R5", "predicate": "is_a",
                   "object": "orders", "idempotency_key": "evt-r5"}
        bad = _push(client, payload, signature="0" * 64)
        assert bad.json()["data"].get("rejected") is True
        good = _push(client, payload).json()["data"]
        assert good.get("fact_id"), good
        assert _activeFactCount(store) == 1

    def test_disabledFaceRejected(self, env, monkeypatch):
        store, client = env
        monkeypatch.setenv("NEUROVA_KB_WEBHOOK_ENABLED", "0")
        resp = _push(client, {"subject": "订单R6", "predicate": "is_a",
                              "object": "orders", "idempotency_key": "evt-r6"})
        receipt = resp.json()["data"]
        assert receipt.get("rejected") is True and "off" in receipt.get("detail", "")
        assert _activeFactCount(store) == 0
