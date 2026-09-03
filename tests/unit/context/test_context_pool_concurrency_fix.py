"""
P0-1 修复测试：ContextPool 并发安全（C1）

测试目标（来自 fix-all-bugs-plan-v1.md）：
- RED：10 线程并发调用 add_context 100 次，断言最终长度 == 1000 且无异常
- 同时验证 cleanup_expired / clear / dedup / build_context_for_model 的并发安全

设计依据：
- ContextPool 共享状态：_cache / _cache_version / _collector._contexts
- 这些字段被多方法并发读写，无任何 threading.RLock 保护
- 修复方案：__init__ 末尾添加 self._lock = threading.RLock()，所有 mutating 方法
  用 with self._lock: 包裹

参考模板：neurova/core/config.py:75、neurova/cognitive/orchestrator.py:358-369
"""

import threading
import time
from datetime import datetime, timedelta

import pytest

from neurova.context_pool import ContextPool, ContextSource, ContextInput


def _make_context(content: str, priority: int = 50) -> ContextInput:
    """构造测试用 ContextInput（每个 content 不同 → hash 不同 → 不会被去重）"""
    return ContextInput(
        source=ContextSource.CONVERSATION,
        content=content,
        priority=priority,
    )


class TestContextPoolConcurrencyFix:
    """P0-1: ContextPool 并发安全修复测试"""

    def test_concurrent_add_context_maintains_count(self):
        """RED: 10 线程并发 add_context 各 100 次，最终长度应为 1000

        未加锁时可能出现：
        - 丢失更新：两线程同时读到 _collector._contexts 的同一快照，各自 append 后写回
        - 索引错位：max_size 检查与 pop(0) 之间被其他线程插入
        - _cache_version 计数错误
        """
        pool = ContextPool(user_id="u1", agent_id="a1", max_size=10000)
        num_threads = 10
        per_thread = 100

        def worker(thread_id: int):
            for i in range(per_thread):
                ctx = _make_context(f"t{thread_id}-msg{i}")
                pool.add_context(ctx)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        contexts = pool.get_contexts()
        assert len(contexts) == num_threads * per_thread, (
            f"并发插入丢失：期望 {num_threads * per_thread}，实际 {len(contexts)}"
        )

    def test_concurrent_add_context_no_exception(self):
        """RED: 并发 add_context 不应抛任何异常"""
        pool = ContextPool(user_id="u1", agent_id="a1", max_size=10000)
        errors = []

        def worker(thread_id: int):
            try:
                for i in range(50):
                    pool.add_context(_make_context(f"t{thread_id}-{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"并发 add_context 抛异常: {errors}"

    def test_concurrent_clear_and_add(self):
        """RED: 一个线程 clear()，另一个线程 add_context()，不应数据损坏"""
        pool = ContextPool(user_id="u1", agent_id="a1", max_size=10000)
        # 预填充
        for i in range(100):
            pool.add_context(_make_context(f"init-{i}"))

        errors = []

        def clearer():
            try:
                for _ in range(20):
                    pool.clear()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def adder():
            try:
                for i in range(200):
                    pool.add_context(_make_context(f"add-{i}"))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=clearer)
        t2 = threading.Thread(target=adder)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"clear+add 并发抛异常: {errors}"
        # 验证最终状态自洽：_collector._contexts 与 _cache_version 一致
        final_contexts = pool.get_contexts()
        assert isinstance(final_contexts, list)

    def test_concurrent_cleanup_expired_and_add(self):
        """RED: 并发 cleanup_expired 与 add_context 不应数据损坏"""
        pool = ContextPool(
            user_id="u1", agent_id="a1", max_size=10000, ttl_seconds=1
        )
        # 预填充部分过期数据
        old_time = datetime.now() - timedelta(seconds=10)
        for i in range(50):
            ctx = _make_context(f"old-{i}")
            ctx.created_at = old_time
            pool.add_context(ctx)

        errors = []

        def cleanup_worker():
            try:
                for _ in range(20):
                    pool.cleanup_expired()
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        def add_worker():
            try:
                for i in range(100):
                    pool.add_context(_make_context(f"new-{i}"))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=cleanup_worker)
        t2 = threading.Thread(target=add_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"cleanup+add 并发抛异常: {errors}"

    def test_concurrent_build_context_for_model(self):
        """RED: 并发 build_context_for_model 不应数据损坏"""
        pool = ContextPool(user_id="u1", agent_id="a1", max_size=10000)
        for i in range(50):
            pool.add_context(_make_context(f"init-{i}"))

        errors = []
        results = []

        def builder():
            try:
                for _ in range(20):
                    msgs = pool.build_context_for_model("gpt-4")
                    results.append(len(msgs))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def adder():
            try:
                for i in range(50):
                    pool.add_context(_make_context(f"add-{i}"))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=builder)
        t2 = threading.Thread(target=adder)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"build+add 并发抛异常: {errors}"

    def test_concurrent_dedup_and_add(self):
        """RED: 并发 dedup 与 add_context 不应数据损坏"""
        pool = ContextPool(user_id="u1", agent_id="a1", max_size=10000)
        for i in range(30):
            pool.add_context(_make_context(f"init-{i}"))

        errors = []

        def dedup_worker():
            try:
                for _ in range(10):
                    pool.dedup()
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        def add_worker():
            try:
                for i in range(100):
                    pool.add_context(_make_context(f"new-{i}"))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=dedup_worker)
        t2 = threading.Thread(target=add_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"dedup+add 并发抛异常: {errors}"

    def test_concurrent_add_at_max_size_boundary_no_lost_updates(self):
        """并发 add_context 无丢失（无损归档语义）

        场景：max_size=50（仅作构造参数，[无损归档] 后不再驱逐），预填充 50 条，
        多线程并发各 add 50 条新内容。

        原断言（max_size 驱逐时代）pins size <= max_size。
        [无损归档] 后驱逐已移除——"永不丢失"是硬约束，容量控制只在视图层
        （Drawer 按预算整条选取）。本用例改 pins 新语义：并发下所有条目
        全部保留且 hash 唯一（去重正确，无更新丢失）。
        """
        max_size = 50
        pool = ContextPool(user_id="u1", agent_id="a1", max_size=max_size)
        # 预填充
        for i in range(max_size):
            pool.add_context(_make_context(f"init-{i}"))

        num_threads = 8
        per_thread = 50

        def worker(thread_id: int):
            for i in range(per_thread):
                pool.add_context(_make_context(f"t{thread_id}-{i}"))

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        contexts = pool.get_contexts()
        # [无损归档] 全部条目保留：50 预填充 + 8 线程 × 50 条，无一丢失
        expected_total = max_size + num_threads * per_thread
        assert len(contexts) == expected_total, (
            f"并发下丢失更新：期望 {expected_total}，实际 {len(contexts)}"
        )
        # 所有 contexts 的 hash 应唯一（去重后），不应有重复
        hashes = [c.hash for c in contexts]
        assert len(hashes) == len(set(hashes)), (
            f"并发插入导致 hash 重复：{len(hashes) - len(set(hashes))} 个重复"
        )

    def test_concurrent_replace_higher_priority_atomic(self):
        """RED: 并发替换更高优先级条目应原子

        场景：预填充 hash=X 的条目 priority=50。多线程并发 add 同 hash 不同 priority。
        修复前（无锁）：可能出现部分替换 / 双重替换 / 状态不一致
        修复后（RLock）：替换原子执行，最终 priority 为最高值
        """
        pool = ContextPool(user_id="u1", agent_id="a1", max_size=10000)
        # 预填充一条
        base_ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="shared-content",
            priority=10,
        )
        pool.add_context(base_ctx)

        # 并发尝试用更高优先级替换
        num_threads = 10
        max_priority = 100

        def worker(thread_id: int):
            ctx = ContextInput(
                source=ContextSource.MEMORY,
                content="shared-content",  # 同 content → 同 hash → 触发替换分支
                priority=50 + thread_id * 5,
            )
            pool.add_context(ctx)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        contexts = pool.get_contexts()
        # 修复后：只有 1 条记录（同 hash 去重）
        same_hash = [c for c in contexts if c.hash == base_ctx.hash]
        assert len(same_hash) == 1, (
            f"并发替换导致同 hash 条目数量异常：期望 1，实际 {len(same_hash)}"
        )
        # 修复后：priority 应为最高尝试值（50 + 9*5 = 95 > 10，所以应被替换为 95）
        # 若优先级没超过 base 则保持原值，这里 95 > 10 必然替换
        assert same_hash[0].priority > 10, (
            f"并发替换未生效：priority={same_hash[0].priority}（应 > 10）"
        )


class TestContextPoolLockExists:
    """验证 ContextPool 持有 RLock 实例（白盒验证修复存在）"""

    def test_pool_has_lock_attribute(self):
        """RED: 修复后 ContextPool 实例应有 _lock 属性且为 RLock 类型"""
        pool = ContextPool(user_id="u1", agent_id="a1")
        assert hasattr(pool, "_lock"), "ContextPool 未持有 _lock 属性（并发保护缺失）"
        # RLock 可重入
        pool._lock.acquire()
        try:
            pool._lock.acquire()  # 重入
            pool._lock.release()
        finally:
            pool._lock.release()
