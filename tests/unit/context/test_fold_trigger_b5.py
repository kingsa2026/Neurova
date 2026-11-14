# -*- coding: utf-8 -*-
"""B5 增长门 + B2 冻结分区 —— 纯判据层（neurova/context/fold_trigger.py）。

契约见模块 docstring。这里只锁可观察判定，不锁实现形状。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.fold_trigger import (
    REASON_BELOW_FLOOR,
    REASON_BUDGET_BREACH,
    REASON_GATE_DISABLED,
    REASON_GROWTH_GATE,
    REASON_INSUFFICIENT_GROWTH,
    REASON_INSUFFICIENT_MASS,
    decideFoldTrigger,
    growthGateEnabled,
    splitFrozenCoveredPrefix,
)


def _decide(**kw):
    base = dict(
        total_tokens=6000,
        budget_tokens=10000,
        last_fold_tokens=0,
        last_fold_msgs=0,
        total_msgs=30,
        foldable_msgs=24,
        enabled=True,
    )
    base.update(kw)
    return decideFoldTrigger(**base)


class TestGrowthGate:
    def test_budget_breach_folds_regardless_of_gate(self):
        """预算击穿：安全线，门关不关都折。"""
        d = _decide(total_tokens=11000, enabled=False)
        assert d.should_fold and d.reason == REASON_BUDGET_BREACH

    def test_gate_disabled_only_folds_on_breach(self):
        """门关（默认）：未超预算不折——与改前行为逐字一致。"""
        assert growthGateEnabled() is False  # 测试环境无该 env
        d = _decide(enabled=False)
        assert not d.should_fold and d.reason == REASON_GATE_DISABLED

    def test_below_floor_no_fold(self):
        """占用低于下限：不主动折（压缩按需不按比例）。"""
        d = _decide(total_tokens=3000, budget_tokens=10000)  # 0.3 < 0.6
        assert not d.should_fold and d.reason == REASON_BELOW_FLOOR

    def test_sufficient_growth_folds_proactively(self):
        """占用过限 + 增量够：未超预算也主动折。"""
        d = _decide(
            total_tokens=7000, budget_tokens=10000,  # 0.7 ≥ 0.6
            last_fold_tokens=3000,  # 增量 4000 ≥ 2000
            last_fold_msgs=20, total_msgs=30,  # 增量 10 条 ≥ 3
        )
        assert d.should_fold and d.reason == REASON_GROWTH_GATE

    def test_insufficient_growth_no_fold(self):
        """增量不足：不折（小增量摘要不划算且打断任务）。"""
        d = _decide(
            total_tokens=7000, budget_tokens=10000,
            last_fold_tokens=6000,  # 增量 1000 < 2000
            last_fold_msgs=28, total_msgs=30,
        )
        assert not d.should_fold and d.reason == REASON_INSUFFICIENT_GROWTH

    def test_insufficient_mass_no_fold(self):
        """可折质量不足（去掉 keep_min 后没得折）：不折。"""
        d = _decide(total_msgs=30, foldable_msgs=3)  # 3 < keep_min 6
        assert not d.should_fold and d.reason == REASON_INSUFFICIENT_MASS

    def test_first_turn_growth_counts_from_zero(self):
        """首轮无折叠基线：增量按全量计（有基线字段为 0 时）。"""
        d = _decide(total_tokens=7000, budget_tokens=10000, last_fold_tokens=0)
        assert d.growth_tokens == 7000


class TestFrozenSplit:
    def _hasher(self, m):
        return "h#" + str(m["content"])

    def test_longest_covered_prefix(self):
        msgs = [{"content": "a"}, {"content": "b"}, {"content": "c"}, {"content": "d"}]
        covered = {"h#a", "h#b"}
        frozen, rest = splitFrozenCoveredPrefix(msgs, covered, self._hasher)
        assert [m["content"] for m in frozen] == ["a", "b"]
        assert [m["content"] for m in rest] == ["c", "d"]

    def test_no_covered_means_no_frozen(self):
        msgs = [{"content": "a"}, {"content": "b"}]
        frozen, rest = splitFrozenCoveredPrefix(msgs, set(), self._hasher)
        assert frozen == [] and [m["content"] for m in rest] == ["a", "b"]

    def test_all_covered(self):
        msgs = [{"content": "a"}, {"content": "b"}]
        frozen, rest = splitFrozenCoveredPrefix(msgs, {"h#a", "h#b"}, self._hasher)
        assert len(frozen) == 2 and rest == []

    def test_gap_stops_at_first_uncovered(self):
        """前缀中间断开：只取到断点（其后即使有 covered hash 也不猜）。"""
        msgs = [{"content": "a"}, {"content": "x"}, {"content": "c"}]
        covered = {"h#a", "h#c"}  # c 在 x 之后——不越过断点
        frozen, rest = splitFrozenCoveredPrefix(msgs, covered, self._hasher)
        assert [m["content"] for m in frozen] == ["a"]
        assert [m["content"] for m in rest] == ["x", "c"]
