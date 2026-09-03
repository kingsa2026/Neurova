"""
TDD 红绿灯测试: mem_core 模块 8 个 bug 修复验证

工作流: 先写全部测试(RED 阶段),再逐个修复源码(GREEN 阶段)。
每个测试对应一个 bug,验证具体行为而非实现细节。

Bug 列表:
- BUG 1 (HIGH): flush_to_long_term_memory 方法不存在 (mem_core.py:590,641)
- BUG 2 (MEDIUM): memory_agent.py 空壳文件, ImportError
- BUG 3 (MEDIUM): flush_to_storage 返回 int 被当 dict (mem_core.py:597-599)
- BUG 4 (MEDIUM): BufferModule._buffer 类型契约违反 (mem_core.py:372)
- BUG 5 (LOW): ConversationBuffer.is_full() 无锁读取
- BUG 6 (LOW): ConversationBuffer.get_stats() 无锁读取
- BUG 7 (LOW): run_async_safely 协程泄漏风险 (mem_core.py:38-56)
- BUG 8 (LOW): 重复导入 MemoryWriteQueue (mem_core.py:284,373)
"""

import asyncio
import os
import re
import threading
from unittest.mock import MagicMock, Mock, patch

import pytest

from neurova.mem_core import MemCore, run_async_safely
from neurova.cognitive_layers.memory_layer.conversation_buffer import (
    ConversationBuffer,
    MemoryWriteQueue,
)
from neurova.cognitive_layers.memory_layer.modules.buffer_module import BufferModule


# ============================================================
# 测试辅助
# ============================================================

def make_memcore(buffer=None, buffer_module=None, memory_manager=None):
    """构造一个最小可用的 MemCore, 仅注入必要依赖。

    MemCore 通过 agent_ref 代理所有属性, 所以我们把依赖挂在 mock agent 上。
    """
    agent = MagicMock()
    agent.conversation_buffer = buffer
    agent.buffer_module = buffer_module
    agent.memory_manager = memory_manager
    return MemCore(agent)


# ============================================================
# BUG 1 (HIGH): flush_to_long_term_memory 方法不存在
# ============================================================

class TestBug1FlushToLongTermMemory:
    """BUG 1: ConversationBuffer 只有 flush() 方法, 调用 flush_to_long_term_memory()
    会抛 AttributeError, 被 except 吞掉, 导致缓冲区永不刷新。"""

    def test_flush_before_retrieve_calls_flush_when_full(self):
        """flush_before_retrieve 在 buffer 满时应调用 flush() 而非不存在的 flush_to_long_term_memory()"""
        # turn_limit=1, 添加一轮后即满
        cb = ConversationBuffer(turn_limit=1)
        cb.add_user_message("hello")
        cb.add_agent_message("world")
        assert cb.is_full(), "前置条件: buffer 应已满"

        # spy flush
        original_flush = cb.flush
        flush_calls = []

        def spy_flush():
            flush_calls.append(True)
            return original_flush()

        cb.flush = spy_flush

        # mock buffer_module._write_queue 返回 int 0 (避免 BUG 3 干扰本测试)
        mock_queue = MagicMock()
        mock_queue.flush_to_storage.return_value = 0
        bm = BufferModule()
        bm._write_queue = mock_queue

        mc = make_memcore(buffer=cb, buffer_module=bm)

        # 修复前: flush_to_long_term_memory 抛 AttributeError 被 except 吞掉, flush() 永不被调用
        # 修复后: flush() 被调用
        mc.flush_before_retrieve()
        assert len(flush_calls) == 1, "BUG 1 未修复: flush() 未被调用"

    def test_save_conversation_memory_flushes_when_full(self):
        """save_conversation_memory 在 buffer 满时应调用 flush()"""
        cb = ConversationBuffer(turn_limit=1)
        cb.add_user_message("hello")
        cb.add_agent_message("world")

        original_flush = cb.flush
        flush_calls = []

        def spy_flush():
            flush_calls.append(True)
            return original_flush()

        cb.flush = spy_flush

        mc = make_memcore(buffer=cb, memory_manager=MagicMock())

        # 再存一轮触发 is_full
        mc.save_conversation_memory("new user", "new agent")
        assert len(flush_calls) == 1, "BUG 1 未修复: 满缓冲时 flush() 未被调用"


# ============================================================
# BUG 2 (MEDIUM): memory_agent.py 空壳文件
# ============================================================

class TestBug2MemoryAgentCompatImport:
    """BUG 2: memory_agent.py 仅有 docstring 无 import, 导致
    `from neurova.memory_agent import MemoryAgent` 抛 ImportError。"""

    def test_import_memory_agent_succeeds(self):
        """from neurova.memory_agent import MemoryAgent 必须成功"""
        from neurova.memory_agent import MemoryAgent
        assert MemoryAgent is not None

    def test_memory_agent_is_mem_core(self):
        """MemoryAgent 应为 MemCore 的别名(向后兼容)"""
        from neurova.memory_agent import MemoryAgent
        assert MemoryAgent is MemCore

    def test_memory_agent_all_exported(self):
        """__all__ 应导出 MemoryAgent"""
        import neurova.memory_agent as ma
        assert hasattr(ma, "__all__")
        assert "MemoryAgent" in ma.__all__


# ============================================================
# BUG 3 (MEDIUM): flush_to_storage 返回 int 被当 dict
# ============================================================

class TestBug3FlushToStorageIntHandling:
    """BUG 3: MemoryWriteQueue.flush_to_storage() 返回 int(written 计数),
    但代码用 result.get("written", 0) 把 int 当 dict, 抛 AttributeError 被 except 吞掉。"""

    def test_flush_to_storage_returns_int_contract(self):
        """契约测试: flush_to_storage() 必须返回 int"""
        q = MemoryWriteQueue()
        result = q.flush_to_storage()
        assert isinstance(result, int), f"flush_to_storage 应返回 int, 实际: {type(result)}"

    def test_flush_before_retrieve_handles_int_return_without_warning(self):
        """flush_before_retrieve 应正确处理 int 返回值, 不触发 'flush 失败' 警告"""
        # buffer 不满, 跳过 BUG 1 路径, 专注测试 BUG 3
        cb = ConversationBuffer()

        mock_queue = MagicMock()
        mock_queue.flush_to_storage.return_value = 5  # int, 不是 dict

        bm = BufferModule()
        bm._write_queue = mock_queue

        mc = make_memcore(buffer=cb, buffer_module=bm)

        with patch("neurova.mem_core.logger") as mock_logger:
            mc.flush_before_retrieve()
            # 修复前: result.get() 抛 AttributeError → 触发 "检索前 flush 失败" 警告
            # 修复后: 正常处理 int, 无警告
            warning_calls = mock_logger.warning.call_args_list
            flush_fail_warnings = [
                c for c in warning_calls
                if c.args and "检索前 flush 失败" in str(c.args[0])
            ]
            assert len(flush_fail_warnings) == 0, "BUG 3 未修复: int 被当 dict 触发了 flush 失败警告"

            # 修复后应记录 debug "写入队列已 flush: %s 条" 带参数 5
            debug_calls = mock_logger.debug.call_args_list
            flush_debug_calls = [
                c for c in debug_calls
                if c.args and "写入队列已 flush" in str(c.args[0])
            ]
            assert len(flush_debug_calls) == 1, "BUG 3 未修复: 未记录 flush debug 消息"


# ============================================================
# BUG 4 (MEDIUM): BufferModule._buffer 类型契约违反
# ============================================================

class TestBug4BufferModuleBufferContract:
    """BUG 4: mem_core.py:372 把 BufferModule._buffer(List[Dict]) 覆盖为
    ConversationBuffer 实例, 破坏 add_turn/append 等方法的类型契约。"""

    def test_init_memory_modules_keeps_buffer_as_list(self):
        """init_memory_modules 后, buffer_module._buffer 必须仍是 list[dict],
        ConversationBuffer 应被单独持有在 _conv_buffer"""
        with patch("neurova.cognitive_layers.memory_layer.conversation_buffer.ConversationMemoryBuffer") as MockCB, \
             patch("neurova.cognitive_layers.memory_layer.conversation_buffer.MemoryWriteQueue") as MockWQ, \
             patch("neurova.cognitive_layers.memory_layer.manager.MemoryManager") as MockMM, \
             patch("neurova.cognitive_layers.memory_layer.modules.buffer_module.BufferModule") as MockBM, \
             patch("neurova.cognitive_layers.memory_layer.temperature.TemperatureEngine"), \
             patch("neurova.cognitive_layers.memory_layer.working_memory.WorkingMemoryAugmenter"), \
             patch("neurova.cognitive_layers.meta_cognition_layer.growth_log.GrowthLogManager"), \
             patch("neurova.cognitive_layers.meta_cognition_layer.question_queue.QuestionQueueManager"), \
             patch("neurova.cognitive_layers.memory_layer.attachment_manager.AttachmentManager"), \
             patch("neurova.cognitive_layers.memory_layer.muscle_memory.MuscleMemory"), \
             patch("neurova.cognitive_layers.memory_layer.tool_memory_integration.ToolMemoryIntegration"):

            # BufferModule 返回真实实例以检查其属性
            real_bm = BufferModule()
            MockBM.return_value = real_bm

            # ConversationMemoryBuffer 返回真实实例
            real_cb = ConversationBuffer()
            MockCB.return_value = real_cb

            # MemoryWriteQueue 返回 mock 避免实际写入
            MockWQ.return_value = MagicMock()

            # MemoryManager.storage = None 跳过 NeurovaRecallEngine
            mock_mm_instance = MockMM.return_value
            mock_mm_instance.storage = None

            # 构造 MemCore
            agent = MagicMock()
            agent.config.db_path = ":memory:"
            mc = MemCore(agent)

            # 不应抛
            mc.init_memory_modules()

            # 修复前: real_bm._buffer = real_cb (ConversationBuffer 实例) → 破坏契约
            # 修复后: real_bm._buffer 仍是 list, real_cb 持有在 _conv_buffer
            assert isinstance(real_bm._buffer, list), \
                f"BUG 4 未修复: _buffer 类型被破坏为 {type(real_bm._buffer).__name__}, 应为 list"
            assert getattr(real_bm, "_conv_buffer", None) is real_cb, \
                "BUG 4 未修复: _conv_buffer 未正确持有 ConversationBuffer"

    def test_buffer_module_add_turn_works_after_injection(self):
        """BufferModule.add_turn 在注入 ConversationBuffer 后仍应正常工作"""
        bm = BufferModule()
        conv_buf = ConversationBuffer()

        # 模拟修复后的注入方式: _conv_buffer 持有 ConversationBuffer, _buffer 不变
        bm._conv_buffer = conv_buf
        bm._write_queue = MagicMock()

        # add_turn 依赖 _buffer 是 list[dict]
        bm.add_turn("user", "hello")
        assert isinstance(bm._buffer, list)
        assert len(bm._buffer) == 1
        assert isinstance(bm._buffer[0], dict)
        assert bm._buffer[0]["content"] == "hello"


# ============================================================
# BUG 5 (LOW): ConversationBuffer.is_full() 无锁读取
# ============================================================

class TestBug5IsFullLockAcquisition:
    """BUG 5: is_full() 读取 _total_bytes/_turns/_last_flush_time 无锁,
    但写入方(add_user_message 等)有锁, 存在数据竞争。"""

    def test_is_full_acquires_lock(self):
        """is_full() 必须持有 _lock"""
        cb = ConversationBuffer()

        acquired = []
        original_lock = cb._lock

        class TrackingLock:
            """包装 RLock, 记录 __enter__ 调用"""

            def __enter__(self):
                acquired.append(True)
                return original_lock.__enter__()

            def __exit__(self, *args):
                return original_lock.__exit__(*args)

            def acquire(self, *a, **kw):
                return original_lock.acquire(*a, **kw)

            def release(self):
                return original_lock.release()

        cb._lock = TrackingLock()
        cb.is_full()
        assert len(acquired) == 1, "BUG 5 未修复: is_full() 未持有 _lock"


# ============================================================
# BUG 6 (LOW): ConversationBuffer.get_stats() 无锁读取
# ============================================================

class TestBug6GetStatsLockAcquisition:
    """BUG 6: get_stats() 读取 _buffer/_total_bytes/_turns/_current_turn 无锁,
    与写入方存在数据竞争。"""

    def test_get_stats_acquires_lock(self):
        """get_stats() 必须持有 _lock"""
        cb = ConversationBuffer()

        acquired = []
        original_lock = cb._lock

        class TrackingLock:
            def __enter__(self):
                acquired.append(True)
                return original_lock.__enter__()

            def __exit__(self, *args):
                return original_lock.__exit__(*args)

            def acquire(self, *a, **kw):
                return original_lock.acquire(*a, **kw)

            def release(self):
                return original_lock.release()

        cb._lock = TrackingLock()
        cb.get_stats()
        assert len(acquired) == 1, "BUG 6 未修复: get_stats() 未持有 _lock"


# ============================================================
# BUG 7 (LOW): run_async_safely 协程泄漏风险
# ============================================================

class TestBug7RunAsyncSafelyCoroLeak:
    """BUG 7: run_async_safely(moe.retrieve(...)) 在传入前已创建协程,
    若 ThreadPoolExecutor 失败, 协程未被 await 也未 close() → 泄漏。"""

    def test_coro_closed_on_executor_submit_failure(self):
        """当调度协程失败(如事件循环关闭/BrokenExecutor)时, 协程必须被 close()"""
        async def sample_coro():
            return 42

        coro = sample_coro()

        async def runner():
            # 在事件循环内调用, 进入 run_coroutine_threadsafe 调度路径。
            # 放大视角: 真实实现通过 asyncio.run_coroutine_threadsafe 提交协程,
            # 而非直接使用 ThreadPoolExecutor.submit, 故应 mock 该提交边界。
            # mock 调度本身抛异常, 模拟"提交失败"——此时协程尚未被事件循环接管, 必须关闭。
            with patch(
                "neurova.mem_core.asyncio.run_coroutine_threadsafe",
                side_effect=RuntimeError("BrokenExecutor"),
            ):
                with pytest.raises(RuntimeError):
                    run_async_safely(coro)

        asyncio.run(runner())
        # 协程被 close() 后 cr_frame 变为 None; 未关闭则仍存在(泄漏)
        leaked = coro.cr_frame is not None
        if leaked:
            coro.close()  # 清理避免 RuntimeWarning
        assert not leaked, "BUG 7 未修复: 协程未在调度失败路径被关闭, cr_frame 仍存在(泄漏)"

    def test_coro_closed_on_future_result_failure(self):
        """当 future.result() 失败时, 协程也必须被 close()"""
        async def sample_coro():
            return 42

        coro = sample_coro()

        async def runner():
            # mock run_coroutine_threadsafe 返回一个 result() 会抛异常的 future,
            # 模拟"协程执行/结果异常"路径。
            mock_future = MagicMock()
            mock_future.result.side_effect = RuntimeError("result failed")
            with patch(
                "neurova.mem_core.asyncio.run_coroutine_threadsafe",
                return_value=mock_future,
            ):
                with pytest.raises(RuntimeError):
                    run_async_safely(coro)

        asyncio.run(runner())
        leaked = coro.cr_frame is not None
        if leaked:
            coro.close()  # 清理避免 RuntimeWarning
        assert not leaked, "BUG 7 未修复: 协程未在结果异常路径被关闭, cr_frame 仍存在(泄漏)"

    def test_coro_returns_value_in_sync_context(self):
        """无事件循环时(同步上下文)应正常返回值"""
        async def sample_coro():
            return 42

        result = run_async_safely(sample_coro())
        assert result == 42


# ============================================================
# BUG 8 (LOW): 重复导入 MemoryWriteQueue
# ============================================================

class TestBug8DuplicateImport:
    """BUG 8: mem_core.py:284 已导入 MemoryWriteQueue, 行 373 重复导入。
    虽无运行时错误, 但属于代码坏味道, 应删除重复导入。"""

    def test_no_duplicate_memory_write_queue_import(self):
        """源码中 MemoryWriteQueue 应只被导入一次"""
        # 从测试文件位置定位 mem_core.py 绝对路径
        test_dir = os.path.dirname(os.path.abspath(__file__))
        mem_core_path = os.path.normpath(
            os.path.join(test_dir, "..", "..", "..", "neurova", "mem_core.py")
        )
        assert os.path.exists(mem_core_path), f"mem_core.py 不存在: {mem_core_path}"

        with open(mem_core_path, "r", encoding="utf-8") as f:
            source = f.read()

        # 匹配 from neurova.cognitive_layers.memory_layer.conversation_buffer import ...MemoryWriteQueue
        pattern = (
            r"from\s+neurova\.cognitive_layers\.memory_layer\.conversation_buffer"
            r"\s+import\s+[^\n#]*MemoryWriteQueue"
        )
        matches = re.findall(pattern, source)
        assert len(matches) == 1, \
            f"BUG 8 未修复: MemoryWriteQueue 被导入 {len(matches)} 次, 应只导入一次。匹配: {matches}"
