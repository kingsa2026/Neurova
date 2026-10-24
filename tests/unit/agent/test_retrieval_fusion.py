# -*- coding: utf-8 -*-
"""链级 RRF 融合：并列检索不再只选最高 quality。"""
from __future__ import annotations

from types import SimpleNamespace

from neurova.agent.retrieval_fusion import fuseRetrievalResults


def _result(source, rows):
    return SimpleNamespace(source=source, memories=rows, quality=0.5)


def testFusionDeduplicatesAndAccumulatesRoutes():
    fused, meta = fuseRetrievalResults([
        _result("graph", [{"fact_id": "f1", "score": 0.9, "content": "甲"}]),
        _result("knowledge", [{"knowledge_id": "f1", "score": 0.8, "content": "乙"}]),
    ], limit=5)

    assert len(fused) == 1
    assert fused[0]["score"] > 0
    assert {r["source"] for r in fused[0]["routes"]} == {"graph", "knowledge"}
    assert meta["routes"] == 2


def testFusionOrdersAcrossSources():
    fused, _ = fuseRetrievalResults([
        _result("graph", [{"id": "d1"}]),
        _result("knowledge", [{"id": "d2"}]),
    ], limit=2)

    assert [row["id"] for row in fused] == ["d1", "d2"]


def testEmptyResultsAreHonest():
    fused, meta = fuseRetrievalResults([_result("empty", [])], limit=5)

    assert fused == []
    assert meta["fused"] == 0
