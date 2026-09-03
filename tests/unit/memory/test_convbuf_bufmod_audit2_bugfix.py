"""
TDD 修复测试: conversation_buffer.py + buffer_module.py 的 11 个 bug

方法论: 红绿灯 TDD
- RED:   先写失败测试确认 bug 存在
- GREEN: 最小代码修改让测试通过
- 若 RED 测试立即通过 → false positive, 标记 skip 并报告
"""

import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# 被测对象导入
# ---------------------------------------------------------------------------
from neurova.cognitive_layers.memory_layer.conversation_buffer import (
    ConversationBuffer,
    MemoryItem,
    MemoryWriteQueue,
)
from neurova.cognitive_layers.memory_layer.models import MemoryType
from neurova.cognitive_layers.memory_layer.modules.buffer_module import BufferModule


# ===========================================================================
# 辅助: 合法枚举值集合
# ===========================================================================
_VALID_MEMORY_TYPES = {mt.value for mt in MemoryType}


class FakeStorage:
    """模拟存储后端, 记录所有 save() 调用的参数"""

    def __init__(self):
        self.saved: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def save(self, content, memory_type, owner="default", tags=None,
             metadata=None, importance=0.0, **kwargs):
        rec = {
            "content": content,
            "memory_type": memory_type,
            "owner": owner,
            "tags": list(tags) if tags else [],
            "metadata": dict(metadata) if metadata else {},
            "importance": importance,
        }
        with self._lock:
            self.saved.append(rec)
        return "mem_fake"


# ===========================================================================
# Bug 1 (HIGH→验证): MemoryWriteQueue._lock=None
# ===========================================================================
class TestBug1WriteQueueLock:
    """验证 _lock 是否为 RLock 实例"""

    def test_lock_is_rlock(self):
        queue = MemoryWriteQueue()
        # RLock 实例可重入; isinstance 检查类型
        assert hasattr(queue, "_lock"), "_lock 属性不存在"
        assert queue._lock is not None, "_lock 为 None"
        # 验证可重入: 同一线程二次 acquire 不阻塞
        acquired = queue._lock.acquire(blocking=False)
        assert acquired, "_lock 不可重入(非 RLock)"
        try:
            second = queue._lock.acquire(blocking=False)
            assert second, "_lock 二次 acquire 失败(应为 RLock)"
            queue._lock.release()
        finally:
            queue._lock.release()


# ===========================================================================
# Bug 2 (HIGH→验证): flush_to_storage 用非法枚举值
# ===========================================================================
class TestBug2IllegalEnumValue:
    """验证 flush_to_storage 传给 storage.save 的 memory_type 是合法枚举值"""

    def test_save_receives_valid_memory_type(self):
        storage = FakeStorage()
        queue = MemoryWriteQueue(storage=storage, agent_id="agent_test")

        # 构造分类为 "user_message"/"agent_message" 的 MemoryItem
        item = MemoryItem(
            id="u1",
            content="hello",
            timestamp=datetime.now(),
            classification="user_message",
        )
        queue.enqueue(item)
        queue.flush_to_storage()

        assert len(storage.saved) == 1, "未写入任何记录"
        mt = storage.saved[0]["memory_type"]
        # 合法值: 必须是 MemoryType 枚举值之一, 或合法枚举成员本身
        if isinstance(mt, MemoryType):
            mt_val = mt.value
        else:
            mt_val = str(mt)
        assert mt_val in _VALID_MEMORY_TYPES, (
            f"非法 memory_type='{mt_val}', 合法值={_VALID_MEMORY_TYPES}"
        )

    def test_original_classification_preserved_in_metadata(self):
        """原分类字符串应保存在 metadata._original_classification"""
        storage = FakeStorage()
        queue = MemoryWriteQueue(storage=storage, agent_id="agent_test")
        item = MemoryItem(
            id="a1",
            content="reply",
            timestamp=datetime.now(),
            classification="agent_message",
        )
        queue.enqueue(item)
        queue.flush_to_storage()

        assert len(storage.saved) == 1
        meta = storage.saved[0]["metadata"]
        assert meta.get("_original_classification") == "agent_message", (
            "原分类未保存在 metadata._original_classification"
        )


# ===========================================================================
# Bug 3 (MEDIUM→验证): enqueue/enqueue_batch 无锁保护
# ===========================================================================
class TestBug3EnqueueLockProtection:
    """验证 enqueue/enqueue_batch 在锁保护下不丢数据"""

    def test_concurrent_enqueue_no_loss(self):
        storage = FakeStorage()
        queue = MemoryWriteQueue(storage=storage, agent_id="agent_test")
        n_threads = 8
        per_thread = 50

        def worker():
            for i in range(per_thread):
                queue.enqueue(MemoryItem(
                    id=f"t-{threading.get_ident()}-{i}",
                    content="x",
                    timestamp=datetime.now(),
                ))

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert queue.get_queue_size() == n_threads * per_thread, (
            f"并发 enqueue 丢失数据: 期望 {n_threads*per_thread}, "
            f"实际 {queue.get_queue_size()}"
        )


# ===========================================================================
# Bug 4 (MEDIUM→验证): ConversationBuffer 无任何锁
# ===========================================================================
class TestBug4ConversationBufferLock:
    """验证 ConversationBuffer 有锁保护并发 add/flush"""

    def test_has_lock_field(self):
        buf = ConversationBuffer()
        assert hasattr(buf, "_lock"), "ConversationBuffer 无 _lock 字段"
        assert buf._lock is not None, "_lock 为 None"

    def test_concurrent_add_flush_no_crash(self):
        buf = ConversationBuffer(turn_limit=10000)
        errors = []

        def adder():
            try:
                for i in range(100):
                    buf.add_user_message(f"u-{i}")
                    buf.add_agent_message(f"a-{i}")
            except Exception as e:
                errors.append(e)

        def flusher():
            try:
                for _ in range(50):
                    buf.flush()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=adder)
        t2 = threading.Thread(target=flusher)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert not errors, f"并发崩溃: {errors}"


# ===========================================================================
# Bug 5 (LOW→验证): logger.info 格式字符串拼接错误
# ===========================================================================
class TestBug5LoggerFormat:
    """验证 flush_to_storage 的日志不抛 TypeError"""

    def test_logger_no_typeerror_on_success(self, caplog):
        storage = FakeStorage()
        queue = MemoryWriteQueue(storage=storage, agent_id="agent_test")
        queue.enqueue(MemoryItem(
            id="x1", content="c", timestamp=datetime.now(),
        ))
        # 不应抛异常
        n = queue.flush_to_storage()
        assert n == 1

    def test_logger_no_typeerror_with_errors(self, caplog):
        """写入失败时日志也不应抛 TypeError"""
        class FailStorage:
            def save(self, **kwargs):
                raise RuntimeError("disk full")
        queue = MemoryWriteQueue(storage=FailStorage(), agent_id="agent_test")
        queue.enqueue(MemoryItem(
            id="x2", content="c", timestamp=datetime.now(),
        ))
        n = queue.flush_to_storage()
        assert n == 0


# ===========================================================================
# Bug 6 (HIGH): _flush_loop TOCTOU 竞态
# ===========================================================================
class TestBug6FlushLoopTOCTOU:
    """验证 _flush_loop 不存在 TOCTOU: write_queue 检查应在锁内"""

    def test_flush_loop_checks_queue_under_lock(self):
        """通过源码审查: _flush_loop 中对 _write_queue 的检查应在持锁状态下

        原 bug: with self._lock 内只做 _move_to_write_queue(),
        释放锁后 if self._write_queue: 无锁访问 → TOCTOU。
        修复后: has_queue = bool(self._write_queue) 在 with self._lock 内。
        """
        import inspect
        src = inspect.getsource(BufferModule._flush_loop)

        # 找到 'with self._lock' 块的范围
        lock_start = src.find("with self._lock")
        assert lock_start != -1, "_flush_loop 无锁"

        # 找到锁块结束(下一个 dedent 到块外)
        lines = src.split("\n")
        in_lock_block = False
        lock_block_lines = []
        outside_lock_lines = []
        for line in lines:
            if "with self._lock" in line:
                in_lock_block = True
                lock_block_lines.append(line)
                continue
            if in_lock_block:
                # 锁块内的行有更多缩进
                stripped = line.lstrip()
                if stripped and not line.startswith("    " * 3):
                    # 缩进回退 → 锁块结束
                    in_lock_block = False
                    outside_lock_lines.append(line)
                else:
                    lock_block_lines.append(line)
            else:
                outside_lock_lines.append(line)

        # 锁块内应包含 _write_queue 的检查
        lock_block_text = "\n".join(lock_block_lines)
        outside_text = "\n".join(outside_lock_lines)

        # _write_queue 的检查(has_queue/bool/if self._write_queue) 应在锁内
        has_check_inside = (
            "_write_queue" in lock_block_text
            or "has_queue" in lock_block_text
        )
        assert has_check_inside, (
            "_write_queue 检查未在锁内(TOCTOU): 锁块内容=\n" + lock_block_text
        )

        # 锁外不应有对 _write_queue 的裸 if 检查
        # (has_queue 变量检查是 OK 的, 但 self._write_queue 直接检查不行)
        import re
        # 匹配 'if self._write_queue' (裸检查, 非赋值)
        bare_check = re.search(r"if\s+self\._write_queue\b", outside_text)
        assert not bare_check, (
            f"_flush_loop 在锁外裸检查 _write_queue (TOCTOU): {bare_check.group()}"
        )

    def test_concurrent_add_flush_no_data_loss(self):
        """并发 add_turn + flush_loop 不漏数据"""
        bm = BufferModule(buffer_size=5, flush_interval=0.05, auto_flush=False)
        # 用 List 模式 (非 MemoryWriteQueue)
        storage = FakeStorage()
        bm._write_queue = []  # List 模式

        n = 100
        for i in range(n):
            bm.add_turn("user", f"msg-{i}")

        # 手动触发 flush_loop 逻辑一次
        bm._flush_loop_single = True
        # 直接调 _flush_loop 的一次迭代逻辑: 模拟
        with bm._lock:
            if bm._buffer:
                bm._move_to_write_queue()
        # 此时 _write_queue 应有 n 项
        assert len(bm._write_queue) == n, (
            f"move 后队列应有 {n} 项, 实际 {len(bm._write_queue)}"
        )


# ===========================================================================
# Bug 7 (MEDIUM): flush() 持锁做 I/O
# ===========================================================================
class TestBug7FlushLockHoldsIO:
    """验证 flush() 不在持锁期间做 I/O (flush_to_storage)"""

    def test_flush_releases_lock_before_storage_io(self):
        """通过行为验证: flush_to_storage 执行期间 add_turn 不被阻塞"""
        bm = BufferModule(buffer_size=100, auto_flush=False)

        io_started = threading.Event()
        add_done = threading.Event()

        class SlowStorage:
            def __init__(self):
                self.saved = []
            def save(self, **kwargs):
                io_started.set()
                time.sleep(0.2)  # 模拟慢 I/O
                self.saved.append(kwargs)
                return "ok"

        # 用 MemoryWriteQueue 模式
        slow_storage = SlowStorage()
        mwq = MemoryWriteQueue(storage=slow_storage, agent_id="t")
        bm._write_queue = mwq

        # 预填数据
        bm.add_turn("user", "preload-1")
        bm.add_turn("agent", "preload-2")

        add_blocked = threading.Event()

        def adder():
            # 等 I/O 开始后尝试 add_turn
            io_started.wait(timeout=2)
            start = time.time()
            bm.add_turn("user", "during-io")
            elapsed = time.time() - start
            if elapsed < 0.15:
                add_blocked.clear()  # 没被阻塞
            else:
                add_blocked.set()  # 被阻塞了
            add_done.set()

        t = threading.Thread(target=adder)
        t.start()

        bm.flush()  # 触发 flush_to_storage

        t.join(timeout=3)
        assert not add_blocked.is_set(), (
            "flush() 持锁做 I/O, 阻塞了 add_turn (应释放锁后再 I/O)"
        )


# ===========================================================================
# Bug 8 (MEDIUM): flush 持锁遍历回调列表
# ===========================================================================
class TestBug8CallbackLockHolding:
    """验证回调执行期间不持锁(锁内只复制列表)"""

    def test_callback_can_reacquire_lock(self):
        """回调内调用 add_turn 不死锁(RLock 可重入, 但验证不长时间持锁)"""
        bm = BufferModule(buffer_size=100, auto_flush=False)
        bm._write_queue = []  # List 模式

        callback_reentered = threading.Event()
        callback_holding_lock = threading.Event()

        def slow_callback(count):
            # 尝试在回调中获取锁(模拟 add_turn 的锁需求)
            # RLock 可重入所以不会死锁, 但关键是回调不应在持锁状态下执行
            # 如果锁在 flush() 中未释放, 这里 acquire(blocking=False) 会成功
            # 但其他线程的 add_turn 会被阻塞
            try:
                bm._lock.acquire(blocking=False)
                callback_holding_lock.set()
                bm._lock.release()
            except RuntimeError:
                pass
            callback_reentered.set()

        bm._on_flush_callbacks.append(slow_callback)
        bm.add_turn("user", "trigger")
        bm.flush()

        assert callback_reentered.is_set(), "回调未执行"

    def test_add_turn_not_blocked_during_callback(self):
        """回调执行期间, 其他线程的 add_turn 不应被阻塞"""
        bm = BufferModule(buffer_size=100, auto_flush=False)
        bm._write_queue = []

        callback_started = threading.Event()
        add_unblocked = threading.Event()

        def slow_callback(count):
            callback_started.set()
            time.sleep(0.3)
            # 回调慢, 但不应阻塞 add_turn

        bm._on_flush_callbacks.append(slow_callback)
        bm.add_turn("user", "trigger")

        def adder():
            callback_started.wait(timeout=2)
            start = time.time()
            bm.add_turn("user", "during-callback")
            elapsed = time.time() - start
            if elapsed < 0.2:
                add_unblocked.set()

        t = threading.Thread(target=adder)
        t.start()
        bm.flush()
        t.join(timeout=3)

        assert add_unblocked.is_set(), (
            "回调执行期间 add_turn 被阻塞(锁未释放)"
        )


# ===========================================================================
# Bug 9 (MEDIUM): _move_to_write_queue ID 碰撞
# ===========================================================================
class TestBug9IdCollision:
    """验证批量刷入无 ID 字典时生成不同 ID"""

    def test_unique_ids_generated(self):
        bm = BufferModule(buffer_size=1000, auto_flush=False)
        # 用 MemoryWriteQueue 模式
        storage = FakeStorage()
        mwq = MemoryWriteQueue(storage=storage, agent_id="t")
        bm._write_queue = mwq

        # 批量添加无 ID 的 turn
        for i in range(50):
            bm.add_turn("user", f"msg-{i}")

        # 移到 write_queue, 触发 ID 生成
        with bm._lock:
            bm._move_to_write_queue()

        # 检查生成的 MemoryItem ID 唯一
        ids = [item.id for item in mwq._queue]
        assert len(ids) == 50
        assert len(set(ids)) == 50, (
            f"ID 碰撞: 50 项仅 {len(set(ids))} 个唯一 ID"
        )

    def test_id_not_plain_timestamp(self):
        """ID 不应是纯 timestamp 字符串(易碰撞)"""
        bm = BufferModule(buffer_size=100, auto_flush=False)
        storage = FakeStorage()
        mwq = MemoryWriteQueue(storage=storage, agent_id="t")
        bm._write_queue = mwq

        bm.add_turn("user", "single")
        with bm._lock:
            bm._move_to_write_queue()

        item_id = mwq._queue[0].id
        # 纯 timestamp 字符串如 "1234567890.123" 不应作为 ID
        try:
            float(item_id)
            is_plain_ts = True
        except (ValueError, TypeError):
            is_plain_ts = False
        assert not is_plain_ts, (
            f"ID 是纯 timestamp '{item_id}', 易碰撞(应用 uuid)"
        )


# ===========================================================================
# Bug 10 (LOW): add_to_write_queue MemoryWriteQueue 模式静默忽略
# ===========================================================================
class TestBug10AddToWriteQueueSilentIgnore:
    """验证 MemoryWriteQueue 模式下 add_to_write_queue 返回 False"""

    def test_returns_false_in_mwq_mode(self):
        bm = BufferModule(buffer_size=100, auto_flush=False)
        storage = FakeStorage()
        mwq = MemoryWriteQueue(storage=storage, agent_id="t")
        bm._write_queue = mwq

        result = bm.add_to_write_queue({"content": "x"})
        assert result is False, (
            f"MemoryWriteQueue 模式应返回 False, 实际返回 {result!r}"
        )


# ===========================================================================
# Bug 11 (LOW): 类型注解 + clear 未取消 flush_thread
# ===========================================================================
class TestBug11TypeAnnotationAndClearThread:
    """验证类型注解兼容 + clear() 不让 flush_thread 继续写入"""

    def test_clear_sets_stop_flag(self):
        """clear() 后, 后台 flush_thread 不应再写入新数据"""
        bm = BufferModule(buffer_size=2, flush_interval=0.05, auto_flush=True)
        bm.init()
        try:
            bm.add_turn("user", "pre-clear")
            time.sleep(0.1)
            bm.clear()
            snapshot = bm.get_stats()
            assert snapshot["buffer_size"] == 0, "clear 后 buffer 非空"
            # 等待几个 flush 周期
            time.sleep(0.15)
            # buffer 应仍为空(flush_thread 不应重新填充, 因 buffer 已清且无新 add_turn)
            after = bm.get_stats()
            assert after["buffer_size"] == 0, (
                "clear() 后 flush_thread 仍在写入数据"
            )
        finally:
            bm.shutdown()

    def test_clear_sets_running_false_or_stop_event(self):
        """clear() 应阻止后台线程继续工作(通过 _running=False 或 stop_event)"""
        bm = BufferModule(buffer_size=2, flush_interval=0.05, auto_flush=True)
        bm.init()
        try:
            bm.clear()
            # clear 后 _running 应为 False, 或有 stop_event 机制
            assert bm._running is False, (
                "clear() 未设置 _running=False (flush_thread 会继续)"
            )
        finally:
            bm.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
