# -*- coding: utf-8 -*-
"""B11 L3 双时态查询（升级计划 §12.4）：asOf（valid time）× knownAt（transaction time）。

四象限判据：asOf 只看 valid 窗口；knownAt 只看事务时间（当时已记录且未撤销）；
两者并存取交集。数据经唯一咽喉落库。
"""

from __future__ import annotations

import datetime

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, subject, predicate, obj, validFrom=None, validUntil=None,
           recordedAt=None):
    content = "%s %s %s" % (subject, predicate, obj)
    request = AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content, validFrom=validFrom, validUntil=validUntil,
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}],
    )
    receipt = productionAdmissionGate(store).admit(request)
    if recordedAt:
        # 事务时间回拨是测试口径（真实写入 recorded_at 恒为 now）：
        # 直接 UPDATE 该行，绕不改咽喉语义——被测的是查询，不是写入。
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_facts SET recorded_at = ? WHERE fact_id = ?",
                (recordedAt, receipt.factId))
    return receipt


class TestBitemporalQuery:
    def test_asOfHonoursValidityWindow(self, store):
        _admit(store, "订单A", "assigned_to", "张三",
               validFrom="2026-01-01", validUntil="2026-06-30")
        _admit(store, "订单A", "assigned_to", "李四",
               validFrom="2026-07-01", validUntil=None)

        march = store.factsBitemporal(agentId="default", asOf="2026-03-15")
        october = store.factsBitemporal(agentId="default", asOf="2026-10-01")

        assert [f["object_term"] for f in march if f["predicate_term_id"] == "assigned_to"] \
            == ["张三"]
        assert [f["object_term"] for f in october if f["predicate_term_id"] == "assigned_to"] \
            == ["李四"]

    def test_knownAtHonoursTransactionTime(self, store):
        _admit(store, "订单B", "has_status", "open", recordedAt="2026-01-10T00:00:00")
        _admit(store, "订单B", "has_status", "closed", recordedAt="2026-02-10T00:00:00")

        jan = store.factsBitemporal(agentId="default", knownAt="2026-01-15T00:00:00")
        feb = store.factsBitemporal(agentId="default", knownAt="2026-03-01T00:00:00")

        assert [f["object_term"] for f in jan if f["predicate_term_id"] == "has_status"] \
            == ["open"], "1 月只知道 open"
        assert sorted(f["object_term"] for f in feb
                      if f["predicate_term_id"] == "has_status") == ["closed", "open"], \
            "3 月两条都知道（knownAt 不做 valid 裁剪）"

    def test_retractedFactsVanishAfterKnownAt(self, store):
        receipt = _admit(store, "订单C", "flagged", "yes",
                         recordedAt="2026-01-10T00:00:00")
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_facts SET retracted_at = '2026-02-01T00:00:00',"
                " status = 'retracted' WHERE fact_id = ?", (receipt.factId,))

        jan = store.factsBitemporal(agentId="default", knownAt="2026-01-15T00:00:00")
        mar = store.factsBitemporal(agentId="default", knownAt="2026-03-01T00:00:00")

        assert len([f for f in jan if f["predicate_term_id"] == "flagged"]) == 1, \
            "撤销前 knownAt 仍可见（当时真的知道）"
        assert len([f for f in mar if f["predicate_term_id"] == "flagged"]) == 0, \
            "撤销后 knownAt 不可见"

    def test_asOfAndKnownAtIntersect(self, store):
        _admit(store, "订单D", "assigned_to", "王五",
               validFrom="2026-01-01", validUntil="2026-12-31",
               recordedAt="2026-06-01T00:00:00")

        both = store.factsBitemporal(agentId="default", asOf="2026-03-15",
                                     knownAt="2026-01-01T00:00:00")
        neither = store.factsBitemporal(agentId="default", asOf="2026-03-15",
                                        knownAt="2026-07-01T00:00:00")

        assert len([f for f in both if f["predicate_term_id"] == "assigned_to"]) == 0, \
            "knownAt 早于 recorded_at ⇒ 当时还不知道"
        assert len([f for f in neither if f["predicate_term_id"] == "assigned_to"]) == 1, \
            "两轴同时满足才可见"
