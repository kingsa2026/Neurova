"""对话缓冲区线程安全测试 — 断点 M-2 + 断点 M-3

断点 M-2 (HIGH): MemoryWriteQueue 锁未初始化
  - 位置: conversation_buffer.py 第 224 行 `self._lock = None`
  - 根因: 锁从未初始化为 threading.RLock(), 所有 enqueue/flush 操作无同步
  - 修复: `self._lock = threading.RLock()`

断点 M-3 (HIGH): ConversationBuffer 无锁保护
  - 位置: conversation_buffer.py 第 65-69 行
  - 根因: _buffer(deque) 和 _turns(List) 无 RLock 保护, 多线程并发 add/flush 会 race
  - 修复: __init__ 加 `self._lock = threading.RLock()`, 所有修改 _buffer/_turns 的方法用锁保护

测试策略:
  1. 确定性测试: 验证 _lock 属性存在且为 threading.RLock 实例(不是 None)
     —— 这是 RED 阶段的关键断言, 当前代码 _lock = None 会直接失败
  2. 并发压力测试: 用 threading.Barrier 同步多线程同时启动, 最大化竞态窗口
     验证不丢数据、不抛异常
  注: CPython GIL 下简单 list.append 是原子的, 故并发测试主要验证
      "锁被正确初始化且方法不会因锁状态异常而抛错", 真正的 race 检测
      依赖 _lock_is_rlock 断言。
"""

import threading
from datetime import datetime

from neurova.cognitive_layers.memory_layer.conversation_buffer import (
    ConversationBuffer,
    MemoryItem,
    MemoryWriteQueue,
)


# ──────────────────────────────────────────────────────────────────
# 断点 M-2: MemoryWriteQueue 锁未初始化
# ──────────────────────────────────────────────────────────────────


class TestMemoryWriteQueueLockInitialized:
    """断点 M-2: MemoryWriteQueue._lock 应为 threading.RLock 实例

    当前代码 `self._lock = None` 导致所有 enqueue/flush 操作无同步。
    """

    def test_write_queue_lock_is_rlock(self):
        """_lock 应为 threading.RLock 实例, 而非 None

        根因: 第 224 行 `self._lock = None`, 锁从未初始化。
        修复: `self._lock = threading.RLock()`。
        """
        queue = MemoryWriteQueue()

        # _lock 必须存在且不为 None
        assert hasattr(queue, "_lock"), "MemoryWriteQueue 缺少 _lock 属性"
        assert queue._lock is not None, (
            "MemoryWriteQueue._lock 为 None — 断点 M-2 未修复: 锁未初始化为 RLock"
        )

        # _lock 必须是 RLock 类型(可重入锁)
        expected_rlock_type = type(threading.RLock())
        assert isinstance(queue._lock, expected_rlock_type), (
            f"MemoryWriteQueue._lock 类型错误: 期望 RLock, 实际 {type(queue._lock).__name__}"
        )

    def test_write_queue_lock_is_reentrant(self):
        """RLock 应可重入 — 同一线程可多次 acquire 不死锁

        防御性测试: 确保修复使用 RLock 而非 Lock,
        允许同一线程在持锁状态下调用其他持锁方法。
        """
        queue = MemoryWriteQueue()

        # 若 _lock 是 None, 此处会抛 AttributeError — RED 阶段失败
        queue._lock.acquire()
        try:
            # 再次 acquire 应成功(RLock 可重入), 普通 Lock 会死锁
            queue._lock.acquire()
            queue._lock.release()
        finally:
            queue._lock.release()

    def test_write_queue_concurrent_enqueue_safe(self):
        """并发 enqueue 不丢数据、不抛异常

        策略: 10 线程各 enqueue 100 条, 用 Barrier 同步启动最大化竞态。
        修复后所有 1000 条应完整保留在队列中。
        """
        queue = MemoryWriteQueue()
        n_threads = 10
        n_per_thread = 100
        expected_total = n_threads * n_per_thread
        barrier = threading.Barrier(n_threads)
        errors = []

        def worker(tid):
            try:
                barrier.wait()  # 所有线程同时启动
                for i in range(n_per_thread):
                    item = MemoryItem(
                        id=f"t{tid}_{i}",
                        content=f"thread-{tid}-item-{i}",
                        timestamp=datetime.now(),
                        classification="conversation",
                    )
                    queue.enqueue(item)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        # 不应有任何线程抛异常
        assert not errors, f"并发 enqueue 抛出异常: {errors}"

        # 应无数据丢失
        actual = queue.get_queue_size()
        assert actual == expected_total, (
            f"并发 enqueue 数据丢失: 期望 {expected_total}, 实际 {actual} "
            f"(丢失 {expected_total - actual} 条)"
        )


# ──────────────────────────────────────────────────────────────────
# 断点 M-3: ConversationBuffer 无锁保护
# ──────────────────────────────────────────────────────────────────


class TestConversationBufferLockInitialized:
    """断点 M-3: ConversationBuffer._lock 应为 threading.RLock 实例

    当前代码 _buffer(deque) 和 _turns(List) 无 RLock 保护。
    """

    def test_buffer_lock_is_rlock(self):
        """_lock 应为 threading.RLock 实例

        根因: __init__ 中未创建 _lock, _buffer/_turns 无同步保护。
        修复: __init__ 加 `self._lock = threading.RLock()`。
        """
        buffer = ConversationBuffer()

        # _lock 必须存在且不为 None
        assert hasattr(buffer, "_lock"), (
            "ConversationBuffer 缺少 _lock 属性 — 断点 M-3 未修复"
        )
        assert buffer._lock is not None, (
            "ConversationBuffer._lock 为 None — 断点 M-3 未修复"
        )

        # _lock 必须是 RLock 类型
        expected_rlock_type = type(threading.RLock())
        assert isinstance(buffer._lock, expected_rlock_type), (
            f"ConversationBuffer._lock 类型错误: 期望 RLock, "
            f"实际 {type(buffer._lock).__name__}"
        )

    def test_buffer_lock_is_reentrant(self):
        """RLock 应可重入 — 允许同线程持锁调用其他持锁方法"""
        buffer = ConversationBuffer()

        buffer._lock.acquire()
        try:
            buffer._lock.acquire()  # RLock 可重入
            buffer._lock.release()
        finally:
            buffer._lock.release()

    def test_buffer_concurrent_add_safe(self):
        """并发 add_user_message 不丢数据、不抛异常

        策略: 10 线程各 add_user_message 50 条, 用 Barrier 同步启动。
        修复后所有 500 条应完整保留在 _buffer 中。
        """
        buffer = ConversationBuffer()
        n_threads = 10
        n_per_thread = 50
        expected_total = n_threads * n_per_thread
        barrier = threading.Barrier(n_threads)
        errors = []

        def worker(tid):
            try:
                barrier.wait()
                for i in range(n_per_thread):
                    buffer.add_user_message(f"thread-{tid}-msg-{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        # 不应有任何线程抛异常
        assert not errors, f"并发 add_user_message 抛出异常: {errors}"

        # 应无数据丢失 —— 通过 flush 取出所有缓冲项计数
        items = buffer.flush()
        actual = len(items)
        assert actual == expected_total, (
            f"并发 add_user_message 数据丢失: 期望 {expected_total}, 实际 {actual} "
            f"(丢失 {expected_total - actual} 条)"
        )
