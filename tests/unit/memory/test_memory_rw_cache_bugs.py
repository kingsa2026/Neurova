"""
MemoryReadWriteManager 缓存断点修复测试 (TDD RED)

针对两个缓存 bug:
- M-1: 跨用户缓存污染 — cache_key 不含 user_id/agent_id
- M-4: 缓存失效子串误匹配 — `if memory_id in key` 子串匹配

修复后所有测试应通过 (GREEN)。
"""
import pytest
from unittest.mock import Mock, patch

from neurova.memory_rw_manager import MemoryReadWriteManager


# ============================================================
# M-1: 跨用户缓存污染
# ============================================================
class TestCacheKeyIsolation:
    """验证 cache_key 包含用户标识,跨用户不互相污染。"""

    def test_cache_key_contains_user_id(self):
        """cache_key 应包含 user_id 和 agent_id,确保用户隔离。"""
        manager = MemoryReadWriteManager()

        # 模拟底层记忆管理器
        mock_memories = [Mock(content="A 的记忆", importance=0.9)]
        with patch.object(manager, "_memory_manager") as mock_mm:
            mock_mm.search.return_value = mock_memories
            manager.recall_memories(
                "测试查询", limit=5, user_id="userA", agent_id="agentX"
            )

        # 验证缓存 key 同时包含 user_id 和 agent_id
        cache_keys = list(manager._cache.keys())
        assert len(cache_keys) == 1, "应只有一条缓存"
        key = cache_keys[0]
        assert "userA" in key, f"cache_key 应包含 user_id,实际: {key}"
        assert "agentX" in key, f"cache_key 应包含 agent_id,实际: {key}"

    def test_cross_user_no_cache_pollution(self):
        """user A 检索后,user B 用相同 query/limit 不应命中 A 的缓存。"""
        manager = MemoryReadWriteManager()

        user_a_memories = [Mock(content="A 私有记忆", importance=0.9)]
        user_b_memories = [Mock(content="B 私有记忆", importance=0.9)]

        with patch.object(manager, "_memory_manager") as mock_mm:
            # 两次底层检索返回不同结果
            mock_mm.search.side_effect = [user_a_memories, user_b_memories]

            # user A 检索(写入缓存)
            results_a = manager.recall_memories("查询", limit=5, user_id="userA")
            # user B 用相同 query/limit 检索(不应命中 A 的缓存)
            results_b = manager.recall_memories("查询", limit=5, user_id="userB")

        # 两用户得到各自的结果,而非共享缓存
        assert results_a is user_a_memories, "user A 应得到自己的记忆"
        assert results_b is user_b_memories, "user B 应得到自己的记忆,而非 A 的缓存"
        # 底层 search 应被调用两次(B 也查了底层,未命中缓存)
        assert mock_mm.search.call_count == 2, "两用户都应触发底层检索"

    def test_different_users_get_different_cache_entries(self):
        """两用户用相同 query/limit 应产生两条独立缓存。"""
        manager = MemoryReadWriteManager()

        with patch.object(manager, "_memory_manager") as mock_mm:
            mock_mm.search.side_effect = [
                [Mock(content="A", importance=0.5)],
                [Mock(content="B", importance=0.5)],
            ]
            manager.recall_memories("查询", limit=5, user_id="userA")
            manager.recall_memories("查询", limit=5, user_id="userB")

        # 两用户应有独立的缓存条目
        assert len(manager._cache) == 2, "两用户应产生两条独立缓存"

    def test_same_user_hits_cache(self):
        """同一用户重复检索应命中缓存(回归测试,确保隔离不破坏正常缓存)。"""
        manager = MemoryReadWriteManager()

        mock_memories = [Mock(content="A 的记忆", importance=0.9)]
        with patch.object(manager, "_memory_manager") as mock_mm:
            mock_mm.search.return_value = mock_memories

            manager.recall_memories("查询", limit=5, user_id="userA")
            manager.recall_memories("查询", limit=5, user_id="userA")

        # 同一用户第二次应命中缓存,底层只调用一次
        assert mock_mm.search.call_count == 1, "同一用户应命中缓存"
        assert manager._cache_hits == 1, "应有一次缓存命中"

    def test_recall_without_user_id_backward_compat(self):
        """recall_memories 不传 user_id 时应保持向后兼容(不报错)。"""
        manager = MemoryReadWriteManager()

        mock_memories = [Mock(content="记忆", importance=0.5)]
        with patch.object(manager, "_memory_manager") as mock_mm:
            mock_mm.search.return_value = mock_memories
            # 不传 user_id/agent_id,保持向后兼容
            results = manager.recall_memories("查询", limit=5)

        assert results is mock_memories, "应正常返回结果"
        assert len(manager._cache) == 1, "应写入缓存"


# ============================================================
# M-4: 缓存失效子串误匹配
# ============================================================
class TestInvalidateCachePrecision:
    """验证 _invalidate_cache 不使用子串匹配,改为清空全部缓存。

    背景: 缓存 key 格式为 `recall:{query}:{limit}` 和 `get:{limit}:{offset}`,
    根本不含 memory_id。因此 _invalidate_cache 既无法精确关联 memory_id 到具体
    缓存条目,旧实现的子串匹配又会误伤(mem_1 误命中 mem_10)。
    正确修复: 清空全部缓存以保证一致性(过失效安全,欠失效才是 bug)。
    """

    def test_invalidate_mem_1_not_match_mem_10(self):
        """失效 mem_1 时不应通过子串匹配误删含 mem_10 的 key。

        旧 bug: `if memory_id in key` 子串匹配 — `mem_1` 会误命中 `mem_10_xxx`。
        修复: 清空全部缓存,不依赖子串匹配。
        """
        manager = MemoryReadWriteManager()
        # 预填充:一个含 "mem_10" 子串的 key,一个真实 recall key(不含 memory_id)
        manager._cache = {
            "mem_10_related": [Mock()],
            "recall:foo:5": [Mock()],
        }

        manager._invalidate_cache("mem_1")

        # 修复后应清空全部缓存
        # 旧 bug 会留下 "recall:foo:5"(因为它不含 "mem_1" 子串),导致缓存未清空
        assert (
            len(manager._cache) == 0
        ), "应清空全部缓存,而非子串选择性删除"

    def test_invalidate_clears_all_unrelated_keys(self):
        """失效缓存时,即使 memory_id 不出现在任何 key 中,也应清空全部缓存。

        旧 bug: 子串匹配永远匹配不到真实 recall/get 缓存 key,
        导致 update/delete 后缓存永不失效,返回陈旧数据。
        """
        manager = MemoryReadWriteManager()
        manager._cache = {
            "recall:foo:5": [Mock()],
            "get:10:0": [Mock()],
        }

        # memory_123 不出现在任何缓存 key 中
        manager._invalidate_cache("memory_123")

        # 应清空全部缓存,确保不返回陈旧数据
        assert len(manager._cache) == 0, "应清空全部缓存以避免陈旧数据"

    def test_invalidate_after_update_clears_recall_cache(self):
        """update_memory 后,recall 缓存应被清空,避免返回陈旧数据。"""
        manager = MemoryReadWriteManager()

        # 第一次检索填充缓存
        old_memories = [Mock(content="旧内容", importance=0.5)]
        with patch.object(manager, "_memory_manager") as mock_mm:
            mock_mm.search.return_value = old_memories
            manager.recall_memories("查询", limit=5, user_id="userA")
            # 验证缓存已填充
            assert len(manager._cache) == 1

            # 更新一条记忆
            mock_mm.update.return_value = True
            manager.update_memory("memory_X", content="新内容")

        # 缓存应被清空,避免返回陈旧数据
        assert len(manager._cache) == 0, "update 后应清空缓存"

    def test_invalidate_after_delete_clears_recall_cache(self):
        """delete_memory 后,recall 缓存应被清空。"""
        manager = MemoryReadWriteManager()

        old_memories = [Mock(content="将被删除", importance=0.5)]
        with patch.object(manager, "_memory_manager") as mock_mm:
            mock_mm.search.return_value = old_memories
            manager.recall_memories("查询", limit=5, user_id="userA")
            assert len(manager._cache) == 1

            mock_mm.delete.return_value = True
            manager.delete_memory("memory_X")

        assert len(manager._cache) == 0, "delete 后应清空缓存"
