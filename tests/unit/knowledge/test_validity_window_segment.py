"""咽喉的时效窗口段：`AdmissionRequest.validFrom/validUntil` 必须真落库。

断点的形状：入参契约里有两个窗口字段（`admission.py:53-54`），且底座表上也有
`valid_from` / `valid_until` 两列（`knowledge_facts.py:75-76`）——**只有落库那一跳没有**：
`upsertFact` 不接这两个参数，`admit()` 也从不读它们。于是生产库里两列全 NULL
（2026-09-21 审计：`supersedes` / `valid_from` / `valid_until` 全 0 行），
`conflict_judge` 的 temporal 分类与 `expireDueFacts()` 双双失去输入，
"写出去没人读"，正是设计文档 §5 要灭的断点。

判据：声明过窗口的 admit，事实行上必须读得到同一个瞬时（归一为 UTC ISO）；
窗口不是"记账装饰"——到了 `validUntil` 之后，该事实必须退出检索候选。
"""

from __future__ import annotations

import datetime

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader

_NOW = datetime.datetime(2026, 9, 21, 12, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, obj, *, validFrom=None, validUntil=None, content=None):
    gate = productionAdmissionGate(store, toolVersion="unit")
    text = content or ("成本护栏落在 %s" % obj)
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel="成本护栏", predicateTermId="governs",
        objectTerm=obj, content=text, validFrom=validFrom, validUntil=validUntil,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": text}],
    )).factId


class TestWindowIsPersisted:
    def test_declaredWindowLandsOnTheRow(self, store):
        until = _NOW + datetime.timedelta(days=10)
        factId = _admit(store, "0.8", validUntil=until.isoformat())

        row = store.fact(factId)

        assert row["valid_until"] == until.isoformat(), (
            "调用方声明了 validUntil，事实行上却是 NULL——咽喉收了字段却没落库")

    def test_validFromIsPersistedAndNormalised(self, store):
        start = _NOW - datetime.timedelta(days=1)
        factId = _admit(store, "0.9", validFrom=start.isoformat())

        assert store.fact(factId)["valid_from"] == start.isoformat()

    def test_nonUtcOffsetIsNormalisedToUtc(self, store):
        """时效比较的是瞬时：混着 +08:00 写进去，文本序会把"已到期"读成"未到期"。"""
        shifted = datetime.datetime(2026, 9, 25, 20, 0, tzinfo=datetime.timezone(
            datetime.timedelta(hours=8)))
        factId = _admit(store, "0.7", validUntil=shifted.isoformat())

        assert store.fact(factId)["valid_until"] == shifted.astimezone(
            datetime.timezone.utc).isoformat()


class TestWindowActuallyGates:
    def test_closedWindowLeavesTheRetrievalSurface(self, store):
        """窗口不是记账装饰：过期后该事实必须退出候选，否则"窗口"仍是个没人读的字段。"""
        factId = _admit(store, "0.5", validUntil=(_NOW - datetime.timedelta(days=1)).isoformat())

        hits = TemporalFactReader(store, agentId="default").forQuery("成本护栏", now=_NOW)

        assert factId not in [h["id"] for h in hits]
        assert store.fact(factId)["status"] == "active", "读面过滤与生命周期状态各按自己口径判"

    def test_openWindowStaysVisible(self, store):
        factId = _admit(store, "0.6", validUntil=(_NOW + datetime.timedelta(days=30)).isoformat())

        assert factId in [h["id"] for h in TemporalFactReader(
            store, agentId="default").forQuery("成本护栏", now=_NOW)]

    def test_validFromInTheFutureIsNotYetEffective(self, store):
        factId = _admit(store, "0.9",
                        validFrom=(_NOW + datetime.timedelta(days=5)).isoformat())

        assert factId not in [h["id"] for h in TemporalFactReader(
            store, agentId="default").forQuery("成本护栏", now=_NOW)]


class TestDedupeDoesNotDropTheWindow:
    def test_sameContentReplayBackfillsTheMissingWindow(self, store):
        """同内容重放折回旧行时，声明过窗口就要补上——否则同一句话第一次带窗口、
        第二次不带，行为随调用顺序漂移。"""
        until = (_NOW + datetime.timedelta(days=3)).isoformat()
        first = _admit(store, "0.4", content="成本护栏取同一个取值")
        second = _admit(store, "0.4", content="成本护栏取同一个取值", validUntil=until)

        assert first == second, "同内容必须折回同一行（004 口径）"
        assert store.fact(first)["valid_until"] == until
