# -*- coding: utf-8 -*-
"""W8 实体消解补强（specs/2026-11-12 §9）：blocking＝nodeType＋label 首 token
倒排桶生成候选对（替代全对扫，桶内仍走既有灰区判定）；候选对 ⊆ 全对扫且规模
显著小；语义近形对入灰区；合并历史/undo 回归不动。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.resolution import (
    candidatePairsBlocking,
    candidatePairsFullScan,
)


class FakeNode:
    def __init__(self, node_id, label, node_type):
        self.node_id = node_id
        self.label = label
        self.node_type = node_type


NODES = [
    FakeNode("n1", "HighRiskOrder", "order"),
    FakeNode("n2", "high risk order", "order"),
    FakeNode("n3", "低风险订单", "order"),
    FakeNode("n4", "CustomerProfile", "person"),
    FakeNode("n5", "customer profile", "person"),
    FakeNode("n6", "设备 A1", "device"),
]


class TestBlocking:
    def test_blockingSubsetOfFullScan(self):
        full = candidatePairsFullScan(NODES)
        blocked = candidatePairsBlocking(NODES)
        assert set(blocked) <= set(full), "blocking 候选对 ⊆ 全对扫"

    def test_blockingSignificantlySmaller(self):
        full = candidatePairsFullScan(NODES)
        blocked = candidatePairsBlocking(NODES)
        assert len(blocked) < len(full) // 2, \
            "倒排桶应把跨类型/跨首 token 对切掉（%d → %d）" % (len(full), len(blocked))

    def test_nearDupePairSurvives(self):
        """同类型同首 token 的近形对必须留在候选集（灰区判定的入口）。"""
        blocked = candidatePairsBlocking(NODES)
        pair = ("n1", "n2")
        assert pair in blocked or (pair[1], pair[0]) in blocked

    def test_crossTypePairsDropped(self):
        blocked = candidatePairsBlocking(NODES)
        cross = [p for p in blocked
                 if {n.node_type for n in NODES if n.node_id in p} != 1
                 and len({n.node_type for n in NODES if n.node_id in p}) == 2]
        assert cross == [], "跨类型对不进候选（桶按 nodeType 分）"
