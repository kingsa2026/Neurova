# -*- coding: utf-8 -*-
"""P3-1b 断言证据的位置锚定（对照研究 reference_y 报告 §5 血缘差距二）红灯。

对方 ClaimSpan 语义的本仓落地：assertion 可选携带 `sourceSpan`
（{"start": int, "end": int}，源文档内字符区间），随溯源账本落库、读回；
不携带时存量行为零漂移（空串列）。能力面：存储＋读回透出；生产写入方
（抽取链带位置信息）按需接线——本批先打通证据可定位的账本通道。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage import KnowledgeLineageLedger


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


def _admit(store, **overrides):
    gate = productionAdmissionGate(store)
    fields = dict(agentId="default", tenantId="default",
                  subjectLabel="客户:甲", predicateTermId="is_a",
                  objectTerm="company", content="客户:甲 is_a company",
                  assertions=[{"actorType": "pipeline", "actorId": "test",
                               "mediumRef": "test",
                               "statementText": "客户:甲 is_a company"}],
                  activityKind="admit", activityBasis="test")
    fields.update(overrides)
    return gate.admit(AdmissionRequest(**fields))


class TestAssertionSourceSpan:

    def test_spanStoredAndReadBack(self, store):
        receipt = _admit(store, assertions=[
            {"actorType": "pipeline", "actorId": "test", "mediumRef": "doc:1",
             "statementText": "客户:甲 is_a company",
             "sourceSpan": {"start": 10, "end": 42}}])
        ledger = KnowledgeLineageLedger(store)
        rows = ledger.traceLineage(receipt.factId)
        assert rows, "溯源读面应有断言行"
        assert rows[0]["source_span"] == {"start": 10, "end": 42}

    def test_spanAbsentStaysEmpty(self, store):
        receipt = _admit(store)
        ledger = KnowledgeLineageLedger(store)
        rows = ledger.traceLineage(receipt.factId)
        assert rows[0]["source_span"] == {}

    def test_spanViaDirectAttach(self, store):
        receipt = _admit(store)
        ledger = KnowledgeLineageLedger(store)
        attached = ledger.attach(receipt.factId, [{
            "actorType": "pipeline", "actorId": "extractor",
            "mediumRef": "doc:2", "statementText": "补充断言",
            "sourceSpan": {"start": 0, "end": 9}}])
        assert attached == 1
        spans = [a.get("source_span") for a in store.assertions(receipt.factId)]
        assert {"start": 0, "end": 9} in spans
