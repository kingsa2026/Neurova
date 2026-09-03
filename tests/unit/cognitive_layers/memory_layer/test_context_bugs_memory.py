"""
上下文功能 Bug 修复 RED 测试 — C-1 + C-5（memory_layer 模块）

C-1: conversation_buffer.py:351 日志格式化 TypeError
    根本原因：括号位置错误，Python 解析为 str + tuple
    触发条件：每次 written > 0（成功批量写入）
    影响：logging 内部捕获 TypeError，日志静默丢失

C-5: buffer_module.py 类型契约不一致
    根本原因：_write_queue 初始化为 List，但 memory_layer.py:197 注入 MemoryWriteQueue
    MemoryWriteQueue 无 __len__/clear/append，但 BufferModule.clear/get_stats/add_to_write_queue 假设 List 接口
    崩溃路径：clear() → TypeError + AttributeError
"""
from __future__ import annotations

import logging
from datetime import datetime
from unittest.mock import MagicMock

import pytest


class TestC1MemoryWriteQueueLogTypeError:
    """C-1: flush_to_storage 日志不应抛 TypeError"""

    def test_c1_flush_to_storage_no_typeerror_on_success(self):
        """RED: written > 0 且 errors = 0 时，logger.info 不应抛 TypeError

        Bug C-1: conversation_buffer.py:351
        实际代码: logger.info("...%s..." + (f"...%s..." if errors else "", written, errors))
        Python 解析: str + (str, written, errors) → str + tuple → TypeError
        """
        from neurova.cognitive_layers.memory_layer.conversation_buffer import (
            MemoryItem,
            MemoryWriteQueue,
        )

        # mock storage，save 总是成功
        mock_storage = MagicMock()
        mock_storage.save = MagicMock(return_value="mem_id_1")

        queue = MemoryWriteQueue(storage=mock_storage, agent_id="test")
        queue.enqueue(
            MemoryItem(
                id="1",
                content="测试内容",
                timestamp=datetime.now(),
                classification="conversation",
                categories=["conversation"],
                meta_trace=None,
            )
        )

        # 启用 logging 异常抛出（默认 logging 模块会吞掉异常）
        original_raise = logging.raiseExceptions
        logging.raiseExceptions = True

        captured_errors = []
        handler = logging.Handler()
        handler.emit = lambda record: None  # 不实际处理
        # 用 handler 捕获 logger 内部异常
        logging.getLogger("neurova.cognitive_layers.memory_layer.conversation_buffer").addHandler(handler)

        try:
            # 这一行在 bug 存在时会抛 TypeError
            written = queue.flush_to_storage()
            # 验证写入成功
            assert written == 1, f"应写入 1 条，实际 {written}"
        except TypeError as e:
            pytest.fail(f"RED C-1: flush_to_storage 抛 TypeError（日志格式化 bug）: {e}")
        finally:
            logging.raiseExceptions = original_raise
            logging.getLogger("neurova.cognitive_layers.memory_layer.conversation_buffer").removeHandler(handler)

    def test_c1_flush_to_storage_log_format_correct(self):
        """RED: 成功写入时日志应正确格式化（errors=0 分支）"""
        from neurova.cognitive_layers.memory_layer.conversation_buffer import (
            MemoryItem,
            MemoryWriteQueue,
        )
        import neurova.cognitive_layers.memory_layer.conversation_buffer as cb_module

        mock_storage = MagicMock()
        mock_storage.save = MagicMock(return_value="mem_id_1")

        queue = MemoryWriteQueue(storage=mock_storage, agent_id="test")
        queue.enqueue(
            MemoryItem(
                id="1",
                content="测试",
                timestamp=datetime.now(),
                classification="conversation",
                categories=["conversation"],
                meta_trace=None,
            )
        )

        # 捕获日志
        records = []
        orig_info = cb_module.logger.info

        def capture_info(msg, *args, **kwargs):
            # 触发实际格式化以暴露 bug
            try:
                if args:
                    msg % args
            except TypeError as e:
                records.append(("TypeError", str(e)))
                return
            records.append(("ok", msg))
            orig_info(msg, *args, **kwargs)

        cb_module.logger.info = capture_info
        try:
            queue.flush_to_storage()
        finally:
            cb_module.logger.info = orig_info

        # 验证无 TypeError
        type_errors = [r for r in records if r[0] == "TypeError"]
        assert not type_errors, f"RED C-1: 日志格式化抛 TypeError: {type_errors[0][1]}"


class TestC5BufferModuleTypeContractInconsistency:
    """C-5: BufferModule 注入 MemoryWriteQueue 后 clear/get_stats/add_to_write_queue 不应崩溃"""

    def test_c5_clear_with_memory_write_queue(self):
        """RED: BufferModule._write_queue 为 MemoryWriteQueue 时 clear() 不应抛 AttributeError

        Bug C-5: buffer_module.py:182-184
        实际代码: self._write_queue.clear() → MemoryWriteQueue 无 clear 方法
        """
        from neurova.cognitive_layers.memory_layer.conversation_buffer import MemoryWriteQueue
        from neurova.cognitive_layers.memory_layer.modules.buffer_module import BufferModule

        bm = BufferModule()
        # 注入 MemoryWriteQueue（模拟 memory_layer.py:197 的行为）
        bm._write_queue = MemoryWriteQueue()

        # bug 存在时抛 AttributeError: 'MemoryWriteQueue' object has no attribute 'clear'
        try:
            count = bm.clear()
            # clear 应返回清除的条目数（int）
            assert isinstance(count, int), f"clear() 应返回 int，实际 {type(count)}"
        except (AttributeError, TypeError) as e:
            pytest.fail(f"RED C-5: BufferModule.clear() 注入 MemoryWriteQueue 后崩溃: {e}")

    def test_c5_get_stats_with_memory_write_queue(self):
        """RED: BufferModule._write_queue 为 MemoryWriteQueue 时 get_stats() 不应抛 TypeError"""
        from neurova.cognitive_layers.memory_layer.conversation_buffer import MemoryWriteQueue
        from neurova.cognitive_layers.memory_layer.modules.buffer_module import BufferModule

        bm = BufferModule()
        bm._write_queue = MemoryWriteQueue()

        try:
            stats = bm.get_stats()
            assert "write_queue_size" in stats
            assert isinstance(stats["write_queue_size"], int)
        except (AttributeError, TypeError) as e:
            pytest.fail(f"RED C-5: BufferModule.get_stats() 注入 MemoryWriteQueue 后崩溃: {e}")

    def test_c5_add_to_write_queue_with_memory_write_queue(self):
        """RED: BufferModule._write_queue 为 MemoryWriteQueue 时 add_to_write_queue 不应崩溃

        注：MemoryWriteQueue 用 enqueue 接收 MemoryItem，BufferModule.add_to_write_queue 接收 Dict
        修复策略：add_to_write_queue 检测类型，对 MemoryWriteQueue 警告并忽略 Dict 项
        """
        from neurova.cognitive_layers.memory_layer.conversation_buffer import MemoryWriteQueue
        from neurova.cognitive_layers.memory_layer.modules.buffer_module import BufferModule

        bm = BufferModule()
        bm._write_queue = MemoryWriteQueue()

        try:
            # bug 存在时抛 AttributeError: 'MemoryWriteQueue' object has no attribute 'append'
            bm.add_to_write_queue({"content": "test"})
        except (AttributeError, TypeError) as e:
            pytest.fail(f"RED C-5: add_to_write_queue 注入 MemoryWriteQueue 后崩溃: {e}")
