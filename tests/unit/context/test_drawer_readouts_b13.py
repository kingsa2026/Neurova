# -*- coding: utf-8 -*-
"""B13（billion-context 对照 · 改进项 B13）：取水质量持续读数。

契约：`SemanticMatchDrawer` 的每轮 draw 累计可观测计数，并经
`ContextPool.get_retention_stats()["drawer"]` 曝光——0.65 相关性门槛
目前只做过一次性两点校准，没有持续读数就无法发现漂移（泄漏/漏召）。

钉住的读数（全部累计计数，线程安全，无 per-key 增长）：
- draws_total           ：draw 调用次数
- offered_total         ：入参池条目累计（粗筛前）
- candidates_total      ：词法粗筛后进入打分的候选累计
- threshold_pass_total  ：相关性门槛通过累计（仅 need 非空的轮计）
- threshold_miss_total  ：相关性门槛拦下累计（仅 need 非空的轮计）
- injected_total        ：实际选中注入视图的条目累计
- injected_tokens_total ：选中条目 token 累计
- degraded_total        ：语义编码失败降级关键词刻度的轮次累计
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer


class ControlledVectorStore:
    """真契约替身：need 向量固定 e0，条目向量按内容前缀路由。

    - content 以 "HIT" 开头 → 与 need 同向（matchScore=1.0，过 0.65 门槛）
    - 其余 → 与 need 正交（matchScore=0.5，被门槛拦下）
    非 MagicMock：行为确定、可复现，断言咬合真实刻度。
    """

    def __init__(self, dim: int = 4):
        self._dim = dim

    def _vec(self, text: str):
        v = [0.0] * self._dim
        if text.startswith("HIT"):
            v[0] = 1.0
        else:
            v[1 % self._dim] = 1.0
        return v

    def encode(self, text: str):
        return self._vec(text)

    def encode_batch(self, texts):
        return [self._vec(t) for t in texts]


def _drops(count: int, hit: bool = True, source=ContextSource.MEMORY):
    prefix = "HIT" if hit else "MISS"
    return [
        ContextInput(
            source=source,
            content=f"{prefix} 条目 {i}：固件升级失败回滚记录",
            priority=60,
            tokens=10,
        )
        for i in range(count)
    ]


def _drawer(**kwargs) -> SemanticMatchDrawer:
    drawer = SemanticMatchDrawer(**kwargs)
    drawer._vector_store = ControlledVectorStore()
    return drawer


class TestDrawerReadouts:
    def test_readouts_start_at_zero(self):
        readouts = _drawer().readouts()
        assert readouts["draws_total"] == 0
        assert readouts["injected_total"] == 0
        assert readouts["degraded_total"] == 0

    def test_draw_counters_count_offered_candidates_injected(self):
        drawer = _drawer(max_tokens=10 ** 9)
        drops = _drops(5)  # 全部与 need 同向 → 全过门槛
        selected = drawer.draw(drops, need="HIT 固件升级")
        r = drawer.readouts()
        assert r["draws_total"] == 1
        assert r["offered_total"] == 5
        assert r["candidates_total"] == 5
        assert r["threshold_pass_total"] == 5
        assert r["threshold_miss_total"] == 0
        assert r["injected_total"] == len(selected)
        assert r["injected_total"] > 0
        assert r["injected_tokens_total"] == sum(d.tokens or 0 for d in selected)
        assert r["degraded_total"] == 0

    def test_threshold_misses_counted(self):
        drawer = _drawer(max_tokens=10 ** 9)
        drops = _drops(4, hit=False)  # 与 need 正交 → matchScore 0.5 < 0.65
        selected = drawer.draw(drops, need="HIT 固件升级")
        assert selected == []
        r = drawer.readouts()
        assert r["threshold_miss_total"] == 4
        assert r["threshold_pass_total"] == 0
        assert r["injected_total"] == 0

    def test_no_need_does_not_count_threshold(self):
        drawer = _drawer(max_tokens=10 ** 9)
        drawer.draw(_drops(3), need=None)  # 无 need：门槛不参与
        r = drawer.readouts()
        assert r["threshold_pass_total"] == 0
        assert r["threshold_miss_total"] == 0
        assert r["injected_total"] > 0

    def test_degraded_counted_when_vector_store_unavailable(self):
        drawer = SemanticMatchDrawer(max_tokens=10 ** 9)
        drawer._vector_store = False  # 向量面缺件 → 关键词刻度降级
        drawer.draw(_drops(2), need="HIT 固件升级")
        assert drawer.readouts()["degraded_total"] == 1

    def test_counters_accumulate_across_draws(self):
        drawer = _drawer(max_tokens=10 ** 9)
        drawer.draw(_drops(2), need="HIT 固件升级")
        drawer.draw(_drops(3), need="HIT 固件升级")
        r = drawer.readouts()
        assert r["draws_total"] == 2
        assert r["offered_total"] == 5
        assert r["injected_total"] == 5

    def test_reset_readouts(self):
        drawer = _drawer(max_tokens=10 ** 9)
        drawer.draw(_drops(2), need="HIT 固件升级")
        drawer.resetReadouts()
        assert drawer.readouts()["draws_total"] == 0


class TestPoolExposesDrawerReadouts:
    def test_retention_stats_include_drawer(self):
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1", max_tokens=10 ** 9)
        for drop in _drops(3):
            pool.add_context(drop)
        pool.draw(need="HIT 固件升级", budget_tokens=10 ** 6)
        drawer_stats = pool.get_retention_stats().get("drawer")
        assert drawer_stats, "get_retention_stats 缺 drawer 读数"
        assert drawer_stats["draws_total"] == 1
        assert drawer_stats["injected_total"] > 0
