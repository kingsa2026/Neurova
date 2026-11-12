# -*- coding: utf-8 -*-
"""W7 判例检索（specs/2026-11-12 §8）：登记后判例命中（词法混合计分——嵌入路径
接入前先以同族词法计分承载，偏差登记台账）；按租户/属主过滤；跨租户零命中。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.decision_ledger import DecisionLedger


@pytest.fixture
def reg():
    s = KnowledgeFactStore(":memory:")
    yield DecisionLedger(s)
    s.close()


def _seed(reg, decisionId, scenario, reasoning, tenantId="default", ownerId=""):
    reg.recordDecision(
        tenantId=tenantId, category="shipping", scenario=scenario,
        reasoning=reasoning, outcome="approved", confidence=0.8,
        decisionMaker="admin", ownerId=ownerId or decisionId,
        decisionId=decisionId)


class TestFindPrecedents:
    def test_keywordHit(self, reg):
        _seed(reg, "d1", "大促期间物流延迟", "大促流量激增导致时效下降，批准延迟发货")
        _seed(reg, "d2", "夜间仓库断电", "备用电源未及时切换，批准人工登记")
        hits = reg.findPrecedents("物流延迟", limit=5, tenantId="default")
        assert hits, "判例命中"
        assert hits[0]["decision_id"] == "d1", "词法命中排序"
        assert hits[0].get("score", 0) > 0

    def test_crossTenantZeroHit(self, reg):
        _seed(reg, "d3", "物流延迟特殊放行", "批准", tenantId="tenantA")
        assert reg.findPrecedents("物流延迟", limit=5, tenantId="default") == []

    def test_ownerFilter(self, reg):
        _seed(reg, "d4", "物流延迟特殊放行", "批准", ownerId="own1")
        _seed(reg, "d5", "物流延迟特殊放行二", "批准", ownerId="own2")
        hits = reg.findPrecedents("物流延迟", limit=10, tenantId="default",
                                  ownerId="own1")
        assert [h["decision_id"] for h in hits] == ["d4"], "按属主过滤"
