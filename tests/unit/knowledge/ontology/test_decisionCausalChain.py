# -*- coding: utf-8 -*-
"""W7 决策因果链（specs/2026-11-12 §8）：caused/precedent 无环硬校验（成环显式拒）；
influenced 允许环但遍历深度受限；跨租户链接拒/自环拒；trace 上溯下探带类型边、
深度上限具名常量（单源）。因果边不进 knowledge_derivation_edges（另一域，通则 6）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.decision_ledger import (
    LINK_KINDS,
    MAX_DECISION_TRACE_DEPTH,
    DecisionLedger,
)


@pytest.fixture
def reg():
    s = KnowledgeFactStore(":memory:")
    yield DecisionLedger(s)
    s.close()


def _dec(reg, decisionId, tenantId="default"):
    reg._store._lock  # noqa: B018 - 占位（直接 SQL 播种带 id 的行）
    with reg._store._lock, reg._store._conn:
        reg._store._conn.execute(
            "INSERT OR REPLACE INTO ontology_decisions"
            " (tenant_id, decision_id, owner_id, category, scenario, reasoning,"
            "  outcome, confidence, decision_maker, agent_id, session_id,"
            "  metadata_json, created_at, valid_from, valid_until)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tenantId, decisionId, "", "c", "s", "r", "o", 0.5, "admin",
             "default", "", "{}",
             "2026-11-12T00:00:00+00:00", "", ""))


class TestLinks:
    def test_linkKindsClosed(self):
        assert LINK_KINDS == ("caused", "influenced", "precedent")

    def test_selfLoopRejected(self, reg):
        _dec(reg, "d1")
        with pytest.raises(ValueError, match="自环"):
            reg.linkDecisions("d1", "d1", "caused", tenantId="default")

    def test_crossTenantRejected(self, reg):
        _dec(reg, "d1", tenantId="tenantA")
        _dec(reg, "d2", tenantId="tenantB")
        with pytest.raises(LookupError, match="跨租户"):
            reg.linkDecisions("d1", "d2", "caused", tenantId="default")

    def test_causalCycleRejected(self, reg):
        _dec(reg, "c1")
        _dec(reg, "c2")
        _dec(reg, "c3")
        reg.linkDecisions("c1", "c2", "caused", tenantId="default")
        reg.linkDecisions("c2", "c3", "caused", tenantId="default")
        with pytest.raises(ValueError, match="环"):
            reg.linkDecisions("c3", "c1", "caused", tenantId="default")

    def test_precedentCycleRejected(self, reg):
        _dec(reg, "p1")
        _dec(reg, "p2")
        reg.linkDecisions("p1", "p2", "precedent", tenantId="default")
        with pytest.raises(ValueError, match="环"):
            reg.linkDecisions("p2", "p1", "precedent", tenantId="default")

    def test_influencedAllowsCycle(self, reg):
        _dec(reg, "i1")
        _dec(reg, "i2")
        reg.linkDecisions("i1", "i2", "influenced", tenantId="default")
        reg.linkDecisions("i2", "i1", "influenced", tenantId="default"), \
            "influenced 允许环（遍历深度受限）"

    def test_unknownEndpointRejected(self, reg):
        _dec(reg, "k1")
        with pytest.raises(LookupError):
            reg.linkDecisions("k1", "ghost", "caused", tenantId="default")


class TestTrace:
    def test_traceUpAndDown(self, reg):
        for d in ("t1", "t2", "t3"):
            _dec(reg, d)
        reg.linkDecisions("t1", "t2", "caused", tenantId="default")
        reg.linkDecisions("t2", "t3", "caused", tenantId="default")
        up = reg.traceDecisionChain("t3", direction="up", tenantId="default")
        assert [node["decision_id"] for node in up] == ["t2", "t1"], "上溯"
        down = reg.traceDecisionChain("t1", direction="down", tenantId="default")
        assert [node["decision_id"] for node in down] == ["t2", "t3"], "下探"
        both = reg.traceDecisionChain("t2", direction="both", tenantId="default")
        ids = {node["decision_id"] for node in both}
        assert ids == {"t1", "t3"}

    def test_traceCarriesLinkKind(self, reg):
        _dec(reg, "w1")
        _dec(reg, "w2")
        reg.linkDecisions("w1", "w2", "influenced", tenantId="default")
        down = reg.traceDecisionChain("w1", direction="down", tenantId="default")
        assert down[0]["link_kind"] == "influenced", "类型边"

    def test_traceDepthCapConstant(self, reg):
        assert MAX_DECISION_TRACE_DEPTH == 10
        ids = ["d%d" % i for i in range(15)]
        for d in ids:
            _dec(reg, d)
        for a, b in zip(ids, ids[1:]):
            reg.linkDecisions(a, b, "caused", tenantId="default")
        down = reg.traceDecisionChain("d0", direction="down", tenantId="default")
        assert len(down) == MAX_DECISION_TRACE_DEPTH, "深度上限截断"

    def test_causalEdgesNotInDerivationLedger(self, reg):
        """因果边不进 knowledge_derivation_edges（另一域，通则 6）。"""
        _dec(reg, "x1")
        _dec(reg, "x2")
        reg.linkDecisions("x1", "x2", "caused", tenantId="default")
        with reg._store._lock:
            n = reg._store._conn.execute(
                "SELECT COUNT(*) AS n FROM knowledge_derivation_edges").fetchone()["n"]
        assert n == 0
