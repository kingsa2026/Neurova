"""RES-P2-1 / RES-P2-4 回归测试。

- ContextPool hash 索引：add 去重与 mark_hashes_seen 由全池 O(n) 线性扫
  改为索引直取；整体重排（clear/dedup/compress/cleanup）后索引同步重建。
- ContextOrchestrator.set_session_id：切换会话时裁剪 _window_compaction_cache
  （旧实现按 session_id 记账永不清理，随历史会话数无界增长）。

B6-10：`mark_turn_seen` 与其配套 turn 索引（`_by_turn`）生产零消费，已删净；
本文件的 TestTurnIndex 一并退役（契约搬到了 `test_ack_set.py` 的抽屉分层用例）。
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

    def test_cache_slots_are_bounded_by_class_limit(self):
        """D2：裁剪职责已从 set_session_id 收口到槽位上限（旧出口零生产调用点）。

        原用例锁定"切换 session 时只保留当前槽"——那是缓存无界增长的唯一出口，
        但 `set_session_id` 在全 neurova/ 内零调用点，等于闸口不存在。现在改锁
        `_window_cache_slot` 的**上限**语义：这才是真正能生效的那道闸。
        """
        orch = self._make_orch()
        for i in range(orch._WINDOW_CACHE_SLOTS + 4):
            orch._window_cache_slot(f"room{i}")
        assert len(orch._window_compaction_cache) == orch._WINDOW_CACHE_SLOTS
        # 最近插入的槽必须在（淘汰的是最老插入的）
        assert f"room{orch._WINDOW_CACHE_SLOTS + 3}" in orch._window_compaction_cache

    def test_set_session_id_only_assigns(self):
        """set_session_id 只赋值，不再承担缓存治理（D2 职责收口）。"""
        orch = self._make_orch()
        orch._window_compaction_cache = {"s1": {"summary": "keep", "covered": set()}}
        orch.set_session_id("s9")
        assert orch._session_id == "s9"
        assert orch._window_compaction_cache == {"s1": {"summary": "keep", "covered": set()}}

    def test_slot_creation_is_idempotent(self):
        orch = self._make_orch()
        orch._window_compaction_cache = {}
        a = orch._window_cache_slot("s1")
        a["summary"] = "kept"
        b = orch._window_cache_slot("s1")
        assert b is a and b["summary"] == "kept"
