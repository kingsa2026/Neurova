# -*- coding: utf-8 -*-
"""W7 决策台账（specs/2026-11-12 §8，D7 必选）：决策一等对象唯一读写面。

必填缺拒/confidence ∈ [0,1] 越界显式拒/租户隔离（A 读不到 B）/身份纪律
（decision_maker 按 sender 显式带，不从 ContextVar 猜——AGENTS.md §3）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.decision_ledger import DecisionLedger


@pytest.fixture
def kb(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "kb.db"))
    yield s
    s.close()


class TestRecordDecision:
    def test_registerAndRead(self, kb):
        reg = DecisionLedger(kb)
        row = reg.recordDecision(
            tenantId="default", category="shipping", scenario="大单发货",
            reasoning="库存充足且客户为高价值", outcome="approved",
            confidence=0.9, decisionMaker="admin",
            ownerId="owner1", agentId="default", sessionId="sess1")
        assert row["decision_id"].startswith("dec_")
        assert row["category"] == "shipping"
        got = reg.get(row["decision_id"], tenantId="default")
        assert got is not None and got["confidence"] == pytest.approx(0.9)

    def test_missingRequiredRejected(self, kb):
        reg = DecisionLedger(kb)
        for missing in ({"category": ""}, {"scenario": ""}, {"reasoning": ""},
                        {"outcome": ""}):
            kwargs = dict(tenantId="default", category="c", scenario="s",
                          reasoning="r", outcome="o", confidence=0.5,
                          decisionMaker="admin")
            kwargs.update(missing)
            with pytest.raises(ValueError):
                reg.recordDecision(**kwargs)

    def test_confidenceOutOfRangeRejected(self, kb):
        reg = DecisionLedger(kb)
        for bad in (-0.1, 1.1):
            with pytest.raises(ValueError, match="confidence"):
                reg.recordDecision(
                    tenantId="default", category="c", scenario="s", reasoning="r",
                    outcome="o", confidence=bad, decisionMaker="admin")

    def test_tenantIsolation(self, kb):
        reg = DecisionLedger(kb)
        row = reg.recordDecision(
            tenantId="tenantA", category="c", scenario="s", reasoning="r",
            outcome="o", confidence=0.5, decisionMaker="admin")
        assert reg.get(row["decision_id"], tenantId="tenantB") is None, "跨租户零读"

    def test_decisionMakerExplicitNotContextVar(self, kb):
        """身份纪律：decision_maker 按调用方显式带入（sender）——不是 ContextVar 猜。"""
        reg = DecisionLedger(kb)
        row = reg.recordDecision(
            tenantId="default", category="c", scenario="s", reasoning="r",
            outcome="o", confidence=0.5, decisionMaker="alice",
            ownerId="own1")
        assert row["decision_maker"] == "alice"
        assert row["owner_id"] == "own1"
