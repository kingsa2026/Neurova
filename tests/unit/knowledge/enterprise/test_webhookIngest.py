# -*- coding: utf-8 -*-
"""W10 入站 webhook 接收器（specs/2026-11-12 §11）：签名校验（HMAC）＋时间戳
窗口拒重放＋幂等键去重（enterprise_webhook_dedup v49）＋事件→descriptor→
admission admit（身份显式带）＋admit 拒记审计不重试风暴（fail-closed）＋缺省 off。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from neurova.knowledge.enterprise.webhook_receiver import (
    WebhookReceiver,
    computeSignature,
)
from neurova.knowledge.foundation.admission import productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    registry = OntologyTermRegistry(s)
    registry.register("orders", "concept", label="订单")
    registry.register("is_a", "relation")
    registry.register("reports", "relation")
    yield s
    s.close()


SECRET = "hook-secret-1"


def _signedBody(payload, secret=SECRET, ts=None):
    ts = ts if ts is not None else int(time.time())
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sig = hmac.new(secret.encode(), body + str(ts).encode(), hashlib.sha256).hexdigest()
    return body, ts, sig


class TestWebhookReceiver:
    def test_offRejectsEverything(self, kb, monkeypatch):
        monkeypatch.setenv("NEUROVA_KB_WEBHOOK_ENABLED", "0")
        receiver = WebhookReceiver(kb, secret=SECRET)
        body, ts, sig = _signedBody({"subject": "订单W1", "object": "orders"})
        result = receiver.handle(body, ts, sig)
        assert result["rejected"] and "off" in result["detail"], "缺省 off 拒"

    def test_badSignatureRejected(self, kb, monkeypatch):
        monkeypatch.setenv("NEUROVA_KB_WEBHOOK_ENABLED", "1")
        receiver = WebhookReceiver(kb, secret=SECRET)
        body, ts, _sig = _signedBody({"subject": "订单W2", "object": "orders"})
        result = receiver.handle(body, ts, "deadbeef")
        assert result["rejected"] and "签名" in result["detail"]

    def test_replayOutsideWindowRejected(self, kb, monkeypatch):
        monkeypatch.setenv("NEUROVA_KB_WEBHOOK_ENABLED", "1")
        receiver = WebhookReceiver(kb, secret=SECRET)
        body, ts, sig = _signedBody({"subject": "订单W3", "object": "orders"}, ts=1)
        result = receiver.handle(body, ts, sig)
        assert result["rejected"], "时间戳窗口外的重放拒"

    def test_validPayloadAdmitsFact(self, kb, monkeypatch):
        monkeypatch.setenv("NEUROVA_KB_WEBHOOK_ENABLED", "1")
        receiver = WebhookReceiver(kb, secret=SECRET, agentId="default")
        payload = {"subject": "订单W4", "predicate": "is_a", "object": "orders",
                   "idempotency_key": "evt-1"}
        body, ts, sig = _signedBody(payload)
        result = receiver.handle(body, ts, sig)
        assert result.get("fact_id"), result
        key = kb.resolveSubjectKey("default", "订单W4")
        facts = [f for f in kb.factsForSubject(key) if f["status"] == "active"]
        assert facts, "事件→admission admit 落事实"

    def test_duplicateIdempotencyKeyZeroSecondWrite(self, kb, monkeypatch):
        """幂等键去重：同一键零二次写（dedup 表 v49）。"""
        monkeypatch.setenv("NEUROVA_KB_WEBHOOK_ENABLED", "1")
        receiver = WebhookReceiver(kb, secret=SECRET, agentId="default")
        payload = {"subject": "订单W5", "predicate": "is_a", "object": "orders",
                   "idempotency_key": "evt-dup"}
        body, ts, sig = _signedBody(payload)
        first = receiver.handle(body, ts, sig)
        assert first.get("fact_id")
        second = receiver.handle(body, ts, sig)
        assert second.get("deduplicated") is True, "幂等重推零二次写"
        assert second.get("fact_id") == first["fact_id"]
        key = kb.resolveSubjectKey("default", "订单W5")
        n = len([f for f in kb.factsForSubject(key) if f["status"] == "active"])
        assert n == 1, "只落一行"

    def test_badSignatureDoesNotTouchDedup(self, kb, monkeypatch):
        """签名错拒→不消耗幂等键（后续合法重推可正常落）。"""
        monkeypatch.setenv("NEUROVA_KB_WEBHOOK_ENABLED", "1")
        receiver = WebhookReceiver(kb, secret=SECRET, agentId="default")
        payload = {"subject": "订单W6", "predicate": "is_a", "object": "orders",
                   "idempotency_key": "evt-bad"}
        body, ts, sig = _signedBody(payload)
        bad = receiver.handle(body, ts, "deadbeef")
        assert bad["rejected"]
        good = receiver.handle(body, ts, sig)
        assert good.get("fact_id"), "拒签不消耗幂等键"

    def test_computeSignatureMatches(self):
        body = b"hello"
        ts = 12345
        sig = computeSignature(body, ts, SECRET)
        assert sig == hmac.new(SECRET.encode(), body + b"12345",
                               hashlib.sha256).hexdigest()
