"""RES-P2-1 / RES-P2-4 回归测试。

- ContextPool hash 索引：add 去重与 mark_hashes_seen 由全池 O(n) 线性扫
  改为索引直取；整体重排（clear/dedup/compress/cleanup）后索引同步重建。
- ContextOrchestrator.set_session_id：切换会话时裁剪 _window_compaction_cache
  （旧实现按 session_id 记账永不清理，随历史会话数无界增长）。
"""

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool


def _make_pool():
    return ContextPool(user_id="u1", agent_id="a1", max_tokens=10000)


def _make_ctx(source, content, priority=50):
    return ContextInput(source=source, content=content, priority=priority)


class TestHashIndexDedup:
    def test_duplicate_hash_skipped_via_index(self):
        pool = _make_pool()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "hello", priority=50))
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "hello", priority=50))
        assert len(pool._collector._contexts) == 1
        assert len(pool._by_hash) == 1

    def test_higher_priority_replaces_entry(self):
        pool = _make_pool()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "low", priority=10))
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "low", priority=99))
        assert len(pool._collector._contexts) == 1
        assert pool._collector._contexts[0].priority == 99
        assert pool._by_hash[pool._collector._contexts[0].hash] is pool._collector._contexts[0]

    def test_index_rebuilt_after_clear_and_readd(self):
        pool = _make_pool()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "one"))
        pool.clear()
        assert pool._by_hash == {}
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "two"))
        assert len(pool._collector._contexts) == 1
        assert len(pool._by_hash) == 1


class TestMarkHashesSeen:
    def test_marks_via_index_and_is_idempotent(self):
        pool = _make_pool()
        ctx = _make_ctx(ContextSource.USER_INPUT, "hello")
        pool.add_context(ctx)
        assert pool.mark_hashes_seen([ctx.hash]) == 1
        assert pool._collector._contexts[0].seen_confirmed is True
        # 幂等：第二次不再计数
        assert pool.mark_hashes_seen([ctx.hash]) == 0

    def test_unknown_and_empty_hashes_ignored(self):
        pool = _make_pool()
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "hello"))
        assert pool.mark_hashes_seen(["nonexistent"]) == 0
        assert pool.mark_hashes_seen([None, ""]) == 0
        assert pool.mark_hashes_seen([]) == 0

    def test_no_stale_mark_after_rebuild(self):
        """clear 后索引为空——已移除条目不得被标记（索引陈旧防线）。"""
        pool = _make_pool()
        ctx = _make_ctx(ContextSource.USER_INPUT, "hello")
        pool.add_context(ctx)
        stale_hash = ctx.hash
        pool.clear()
        # 重新加入同 hash 前先标记：索引已清空，不得误标
        assert pool.mark_hashes_seen([stale_hash]) == 0
        pool.add_context(_make_ctx(ContextSource.USER_INPUT, "hello"))
        assert pool._collector._contexts[0].seen_confirmed is False

    def test_dedup_rebuild_keeps_index_accurate(self):
        """dedup() 整体重排列表后，索引必须与列表一致。"""
        pool = _make_pool()
        c1 = _make_ctx(ContextSource.USER_INPUT, "a")
        c2 = _make_ctx(ContextSource.CONVERSATION, "b")
        pool.add_context(c1)
        pool.add_context(c2)
        pool.dedup(stage="output")
        assert len(pool._by_hash) == len([c for c in pool._collector._contexts if c.hash])
        for c in pool._collector._contexts:
            assert pool._by_hash.get(c.hash) is c


class TestOrchestratorCacheTrim:
    def _make_orch(self):
        from neurova.context.orchestrator import ContextOrchestrator

        orch = object.__new__(ContextOrchestrator)
        orch.context_pool = None
        orch._session_id = "s1"
        orch._window_compaction_cache = {}
        return orch

    def test_set_session_id_keeps_only_current_session(self):
        orch = self._make_orch()
        orch._window_compaction_cache = {
            "s1": {"summary": "a", "covered": set()},
            "s2": {"summary": "b", "covered": set()},
            "s3": {"summary": "c", "covered": set()},
        }
        orch.set_session_id("s2")
        assert set(orch._window_compaction_cache) == {"s2"}
        assert orch._window_compaction_cache["s2"]["summary"] == "b"

    def test_set_session_id_preserves_current_entry(self):
        orch = self._make_orch()
        orch._window_compaction_cache = {"s1": {"summary": "keep", "covered": set()}}
        orch.set_session_id("s1")
        assert orch._window_compaction_cache["s1"]["summary"] == "keep"

    def test_empty_cache_no_error(self):
        orch = self._make_orch()
        orch.set_session_id("s9")
        assert orch._window_compaction_cache == {}
