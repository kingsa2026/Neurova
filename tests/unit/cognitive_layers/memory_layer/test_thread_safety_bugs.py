"""线程安全 bug 修复测试 — Bug 5 + Bug 6

Bug 5: MemoryManager.update_memory / forget 缺失 RLock 保护
       - 现状：直接读写 self._memories，无锁
       - 修复：用 `with self._lock:` 包裹临界区

Bug 6: EventBus._handlers / _emit_count 无锁保护
       - 现状：on/off/emit 直接读写 _handlers dict 和 _emit_count
       - 修复：用 threading.Lock 保护所有读写操作

测试策略：
  竞态条件测试在 CPython GIL 下非确定性（简单字节码操作可能不产生可见竞态）。
  改用确定性策略 —— 验证锁被获取：
    1. 主线程持有锁
    2. 子线程调用方法应阻塞（证明方法尝试获取锁）
    3. 释放锁后子线程应完成
  这验证了"方法线程安全"的行为契约，而非实现细节。

遵循 TDD 垂直切片：一次一个测试 → 一次一个修复。
"""

import threading
import time
from unittest.mock import MagicMock

import pytest

from neurova.cognitive_layers.memory_layer.bus_event import EventBus, MemoryEvent
from neurova.cognitive_layers.memory_layer.manager import MemoryManager


# ──────────────────────────────────────────────────────────────────
# Bug 5: MemoryManager.update_memory / forget 缺失 RLock
# ──────────────────────────────────────────────────────────────────


class TestBug5MemoryManagerLockProtection:
    """Bug 5: update_memory / forget 应在 RLock 保护下执行

    确定性测试策略：主线程持有 self._lock，子线程调用方法应阻塞。
    若方法不获取锁，子线程会立即完成（测试失败）。
    """

    def _make_manager(self, agent_id="test_bug5"):
        """创建隔离的 MemoryManager"""
        import uuid

        unique_id = f"{agent_id}_{uuid.uuid4().hex[:8]}"
        return MemoryManager(db_path=":memory:", agent_id=unique_id)

    def test_forget_acquires_lock(self):
        """forget 应获取 self._lock

        根因：forget 直接读写 self._memories，无 `with self._lock:` 保护。
        修复：用 `with self._lock:` 包裹 forget 全临界区。
        """
        manager = self._make_manager()
        mem_id = manager.remember(content="锁测试", temperature=50.0)

        # 主线程持有锁
        manager._lock.acquire()
        try:
            completed = threading.Event()

            def worker():
                try:
                    manager.forget(mem_id, soft=False)
                finally:
                    completed.set()

            t = threading.Thread(target=worker)
            t.start()

            # worker 应该阻塞（等待锁）— 给 0.5s 验证未完成
            completed.wait(timeout=0.5)
            assert not completed.is_set(), (
                "forget 未获取 self._lock — worker 未阻塞，说明 forget 没有用 `with self._lock:`"
            )

            # 释放锁
            manager._lock.release()

            # worker 现在应该完成
            completed.wait(timeout=2.0)
            assert completed.is_set(), "forget 获取锁后 worker 未完成（超时）"
        finally:
            # 确保锁被释放（若上面的 assert 失败）
            try:
                manager._lock.release()
            except RuntimeError:
                pass  # already released

        t.join(timeout=1.0)

    def test_update_memory_acquires_lock(self):
        """update_memory 应获取 self._lock

        根因：update_memory 直接读写 self._memories 和 _persist_memory，无锁保护。
        修复：用 `with self._lock:` 包裹 update_memory 全临界区。
        """
        manager = self._make_manager()
        mem_id = manager.remember(content="锁测试", temperature=50.0)

        manager._lock.acquire()
        try:
            completed = threading.Event()

            def worker():
                try:
                    manager.update_memory(mem_id, temperature=30.0, content="updated")
                finally:
                    completed.set()

            t = threading.Thread(target=worker)
            t.start()

            completed.wait(timeout=0.5)
            assert not completed.is_set(), (
                "update_memory 未获取 self._lock — worker 未阻塞"
            )

            manager._lock.release()
            completed.wait(timeout=2.0)
            assert completed.is_set(), "update_memory 获取锁后 worker 未完成"
        finally:
            try:
                manager._lock.release()
            except RuntimeError:
                pass

        t.join(timeout=1.0)

    def test_lock_is_reentrant(self):
        """RLock 应可重入（update_memory 内部调用 _persist_memory 不应死锁）

        这是防御性测试：确保修复使用 RLock 而非 Lock，
        允许同一线程在持锁状态下调用其他持锁方法。
        """
        manager = self._make_manager()
        mem_id = manager.remember(content="重入测试", temperature=50.0)

        # 同一线程持锁后调用 update_memory（应不死锁）
        with manager._lock:
            # 若 update_memory 用 RLock 保护，此处可重入
            # 若用普通 Lock 保护，此处死锁
            manager.update_memory(mem_id, temperature=25.0)

        assert manager._memories[mem_id].temperature == 25.0


# ──────────────────────────────────────────────────────────────────
# Bug 6: EventBus._handlers / _emit_count 无锁保护
# ──────────────────────────────────────────────────────────────────


class TestBug6EventBusLockProtection:
    """Bug 6: EventBus 应在锁保护下读写 _handlers / _emit_count

    确定性测试策略：
      - on()/off() 用锁保护 _handlers 修改
      - emit() 用锁保护 _emit_count 修改 + 复制 handlers list 后释放锁再迭代
        （避免持锁调用 handler 导致递归死锁）
    """

    def test_on_acquires_lock(self):
        """on() 应获取锁

        根因：on() 用 `if event_type not in _handlers: _handlers[event_type] = []`
        无锁保护，存在 TOCTOU。
        修复：用 `with self._lock:` 保护 on() 全临界区。
        """
        bus = EventBus()

        # 检查 EventBus 是否有 _lock 属性（修复后应有）
        assert hasattr(bus, "_lock"), (
            "EventBus 没有 _lock 属性 — Bug 6 未修复：缺少 threading.Lock"
        )

        bus._lock.acquire()
        try:
            completed = threading.Event()

            def worker():
                try:
                    bus.on("test_event", lambda e: None)
                finally:
                    completed.set()

            t = threading.Thread(target=worker)
            t.start()

            completed.wait(timeout=0.5)
            assert not completed.is_set(), (
                "on() 未获取 _lock — worker 未阻塞，说明 on() 没有用锁保护"
            )

            bus._lock.release()
            completed.wait(timeout=2.0)
            assert completed.is_set(), "on() 获取锁后 worker 未完成"
        finally:
            try:
                bus._lock.release()
            except RuntimeError:
                pass

        t.join(timeout=1.0)

    def test_off_acquires_lock(self):
        """off() 应获取锁"""
        bus = EventBus()

        if not hasattr(bus, "_lock"):
            pytest.fail("EventBus 没有 _lock 属性 — Bug 6 未修复")

        handler = lambda e: None
        bus.on("test_event", handler)

        bus._lock.acquire()
        try:
            completed = threading.Event()

            def worker():
                try:
                    bus.off("test_event", handler)
                finally:
                    completed.set()

            t = threading.Thread(target=worker)
            t.start()

            completed.wait(timeout=0.5)
            assert not completed.is_set(), "off() 未获取 _lock — worker 未阻塞"

            bus._lock.release()
            completed.wait(timeout=2.0)
            assert completed.is_set(), "off() 获取锁后 worker 未完成"
        finally:
            try:
                bus._lock.release()
            except RuntimeError:
                pass

        t.join(timeout=1.0)

    def test_emit_acquires_lock_for_count(self):
        """emit() 应获取锁保护 _emit_count 修改"""
        bus = EventBus()
        bus.on("test_event", lambda e: None)

        if not hasattr(bus, "_lock"):
            pytest.fail("EventBus 没有 _lock 属性 — Bug 6 未修复")

        bus._lock.acquire()
        try:
            completed = threading.Event()

            event = MemoryEvent(type="test_event", source="test", payload={})

            def worker():
                try:
                    bus.emit(event)
                finally:
                    completed.set()

            t = threading.Thread(target=worker)
            t.start()

            completed.wait(timeout=0.5)
            assert not completed.is_set(), (
                "emit() 未获取 _lock 保护 _emit_count — worker 未阻塞"
            )

            bus._lock.release()
            completed.wait(timeout=2.0)
            assert completed.is_set(), "emit() 获取锁后 worker 未完成"
        finally:
            try:
                bus._lock.release()
            except RuntimeError:
                pass

        t.join(timeout=1.0)
        assert bus.emit_count == 1

    def test_emit_does_not_deadlock_with_recursive_handler(self):
        """emit() 不应在持锁状态下调用 handler（避免递归 emit 死锁）

        设计约束：emit() 应在锁内复制 handlers list，释放锁后再迭代调用 handler。
        若 handler 内部递归 emit()，不会死锁。
        """
        bus = EventBus()

        if not hasattr(bus, "_lock"):
            pytest.fail("EventBus 没有 _lock 属性 — Bug 6 未修复")

        recursive_event = MemoryEvent(type="recursive", source="test", payload={})
        call_log = []

        def recursive_handler(e):
            call_log.append("handler")
            # 第一次调用时递归 emit 一次
            if len(call_log) == 1:
                nested_event = MemoryEvent(type="nested", source="test", payload={})
                bus.emit(nested_event)

        bus.on("recursive", recursive_handler)
        bus.on("nested", lambda e: call_log.append("nested"))

        # 不应死锁
        bus.emit(recursive_event)

        # 两个 handler 都应被调用
        assert "handler" in call_log
        assert "nested" in call_log

    def test_concurrent_on_no_lost_handlers(self):
        """高并发 on() 不应丢失 handler 注册（压力测试）

        用 threading.Barrier 同步所有线程同时启动，最大化竞态窗口。
        """
        bus = EventBus()

        if not hasattr(bus, "_lock"):
            pytest.fail("EventBus 没有 _lock 属性 — Bug 6 未修复")

        event_type = "stress"
        N = 100
        barrier = threading.Barrier(N)

        def register(idx):
            barrier.wait()  # 所有线程同时启动
            bus.on(event_type, lambda e, i=idx: None)

        threads = [threading.Thread(target=register, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        actual = bus.handler_count(event_type)
        assert actual == N, (
            f"丢失 handler 注册: 期望 {N}, 实际 {actual}（丢失 {N - actual} 个）"
        )

    def test_concurrent_emit_count_accurate(self):
        """高并发 emit() 后 _emit_count 应准确（压力测试）"""
        bus = EventBus()
        bus.on("count_test", lambda e: None)

        if not hasattr(bus, "_lock"):
            pytest.fail("EventBus 没有 _lock 属性 — Bug 6 未修复")

        event = MemoryEvent(type="count_test", source="test", payload={})
        N_THREADS = 20
        N_EMITS_PER_THREAD = 200
        barrier = threading.Barrier(N_THREADS)

        def emitter():
            barrier.wait()
            for _ in range(N_EMITS_PER_THREAD):
                bus.emit(event)

        threads = [threading.Thread(target=emitter) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        expected = N_THREADS * N_EMITS_PER_THREAD
        actual = bus.emit_count
        assert actual == expected, (
            f"_emit_count 不准确: 期望 {expected}, 实际 {actual}（丢失 {expected - actual} 次）"
        )
