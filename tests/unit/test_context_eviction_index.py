"""Scroll Context 式被驱逐轮次索引单元测试。

对齐升级方案 P1-2.2：对话轮次持久化 + 被驱逐轮次索引、按需召回。
契约更新（残留处理 2026-09-13）：P1-1"永久归档"决议已废除容量驱逐——
池定位=永不丢失，容量控制移到视图层（Drawer 预算整条选取）。因此
①容量溢出不再产生台账（本文件钉此新行为）；②台账语义（倒序/有界/
limit/统计）经 TTL 过期与手动 `_archive_evicted` 两条现行归档路径验证。
"""

import unittest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool


def _make_pool(max_size=3, ttl_seconds=3600) -> ContextPool:
    return ContextPool(
        user_id="u1",
        agent_id="a1",
        session_id="s1",
        max_size=max_size,
        ttl_seconds=ttl_seconds,
    )


def _ctx(content: str, source=ContextSource.CONVERSATION) -> ContextInput:
    return ContextInput(source=source, content=content)


class TestFifoEvictionArchived(unittest.TestCase):
    """容量驱逐不再丢失：进台账，可召回。"""

    def test_overflow_does_not_lose_entry(self):
        # P1-1 永久归档契约：max_size 不再驱逐，三条全部无损在池
        pool = _make_pool(max_size=2)
        pool.add_context(_ctx("第一轮：讨论项目目标"))
        pool.add_context(_ctx("第二轮：确定技术选型"))
        pool.add_context(_ctx("第三轮：分配任务"))

        active = [c.content for c in pool.get_contexts()]
        self.assertIn("第一轮：讨论项目目标", active)
        self.assertEqual(len(active), 3)
        # 容量路径不再产生台账；TTL/手动归档路径见下
        self.assertEqual(pool.recall_evicted("项目目标"), [])
        pool._archive_evicted(_ctx("第一轮：讨论项目目标"))
        recalled = pool.recall_evicted("项目目标")
        self.assertEqual(len(recalled), 1)

    def test_recall_without_query_returns_latest_first(self):
        # 台账倒序语义经手动归档路径验证（容量驱逐已废除）
        pool = _make_pool(max_size=1)
        a, b = _ctx("旧轮次A"), _ctx("旧轮次B")
        pool._archive_evicted(a)
        pool._archive_evicted(b)
        recalled = pool.recall_evicted(limit=10)
        contents = [c.content for c in recalled]
        # 台账按驱逐时间倒序 → 后驱逐的 B 在前
        self.assertEqual(contents, ["旧轮次B", "旧轮次A"])

    def test_recall_no_match_returns_empty(self):
        pool = _make_pool(max_size=1)
        pool.add_context(_ctx("关于晚餐的讨论"))
        pool.add_context(_ctx("关于天气的讨论"))
        self.assertEqual(pool.recall_evicted("量子物理"), [])

    def test_ledger_is_bounded(self):
        pool = _make_pool(max_size=1)
        pool._max_eviction_ledger = 5  # 收紧台账上限便于测试
        for i in range(20):
            pool._archive_evicted(_ctx(f"轮次-{i}"))
        stats = pool.get_eviction_stats()
        self.assertLessEqual(stats["ledger_size"], 5)

    def test_active_pool_unaffected_by_recall(self):
        pool = _make_pool(max_size=2)
        pool.add_context(_ctx("保留-1"))
        pool.add_context(_ctx("保留-2"))
        pool.add_context(_ctx("被驱逐-3"))
        # 召回不改变活动池内容
        before = [c.content for c in pool.get_contexts()]
        pool.recall_evicted("被驱逐")
        after = [c.content for c in pool.get_contexts()]
        self.assertEqual(before, after)


class TestTtlEvictionArchived(unittest.TestCase):
    """TTL 过期驱逐同样进台账。"""

    def test_cleanup_expired_archives(self):
        import datetime as dt

        pool = _make_pool(ttl_seconds=60)
        old = _ctx("过期但重要的轮次")
        old.created_at = dt.datetime.now() - dt.timedelta(seconds=120)
        fresh = _ctx("新鲜轮次")
        pool.add_context(old)
        pool.add_context(fresh)

        removed = pool.cleanup_expired()
        self.assertEqual(removed, 1)
        recalled = pool.recall_evicted("过期但重要")
        self.assertEqual(len(recalled), 1)


class TestEvictionStats(unittest.TestCase):
    """统计信息。"""

    def test_stats_shape_and_counts(self):
        pool = _make_pool(max_size=1)
        pool._archive_evicted(_ctx("x1"))
        pool._archive_evicted(_ctx("x2"))
        stats = pool.get_eviction_stats()
        self.assertIn("evicted_total", stats)
        self.assertIn("ledger_size", stats)
        self.assertGreaterEqual(stats["evicted_total"], 2)

    def test_recall_respects_limit(self):
        pool = _make_pool(max_size=1)
        for i in range(6):
            pool._archive_evicted(_ctx(f"公共词-{i}"))
        self.assertEqual(len(pool.recall_evicted("公共词", limit=3)), 3)


if __name__ == "__main__":
    unittest.main()
