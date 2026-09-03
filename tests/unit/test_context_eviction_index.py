"""Scroll Context 式被驱逐轮次索引单元测试。

对齐升级方案 P1-2.2：对话轮次持久化 + 被驱逐轮次索引、按需召回。
现状：ContextPool 驱逐（FIFO pop / TTL 过期）直接丢弃条目，不可恢复；
升级后被驱逐条目进入有界「驱逐台账」，可按内容关键词召回。
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

    def test_overflow_archives_evicted_entry(self):
        pool = _make_pool(max_size=2)
        pool.add_context(_ctx("第一轮：讨论项目目标"))
        pool.add_context(_ctx("第二轮：确定技术选型"))
        pool.add_context(_ctx("第三轮：分配任务"))

        # 池内只剩最新 2 条
        active = [c.content for c in pool.get_contexts()]
        self.assertNotIn("第一轮：讨论项目目标", active)
        # 但被驱逐条目可召回
        recalled = pool.recall_evicted("项目目标")
        self.assertEqual(len(recalled), 1)
        self.assertIn("项目目标", recalled[0].content)

    def test_recall_without_query_returns_latest_first(self):
        pool = _make_pool(max_size=1)
        pool.add_context(_ctx("旧轮次A"))
        pool.add_context(_ctx("旧轮次B"))
        pool.add_context(_ctx("活跃轮次C"))
        recalled = pool.recall_evicted(limit=10)
        contents = [c.content for c in recalled]
        # max_size=1: C 仍在活动池；台账=[A,B]，按驱逐时间倒序 → B 在前
        self.assertEqual(contents, ["旧轮次B", "旧轮次A"])
        self.assertNotIn("活跃轮次C", contents)

    def test_recall_no_match_returns_empty(self):
        pool = _make_pool(max_size=1)
        pool.add_context(_ctx("关于晚餐的讨论"))
        pool.add_context(_ctx("关于天气的讨论"))
        self.assertEqual(pool.recall_evicted("量子物理"), [])

    def test_ledger_is_bounded(self):
        pool = _make_pool(max_size=1)
        pool._max_eviction_ledger = 5  # 收紧台账上限便于测试
        for i in range(20):
            pool.add_context(_ctx(f"轮次-{i}"))
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
        pool.add_context(_ctx("x1"))
        pool.add_context(_ctx("x2"))
        stats = pool.get_eviction_stats()
        self.assertIn("evicted_total", stats)
        self.assertIn("ledger_size", stats)
        self.assertGreaterEqual(stats["evicted_total"], 1)

    def test_recall_respects_limit(self):
        pool = _make_pool(max_size=1)
        for i in range(6):
            pool.add_context(_ctx(f"公共词-{i}"))
        self.assertEqual(len(pool.recall_evicted("公共词", limit=3)), 3)


if __name__ == "__main__":
    unittest.main()
