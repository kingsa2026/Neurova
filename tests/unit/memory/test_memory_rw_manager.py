"""
MemoryReadWriteManager 测试

验证：
- 记忆读写管理器的核心功能
- 缓存优先读取
- 批量写入机制
- 记忆生命周期管理
- 温度衰减调度
"""
import pytest
import time
from unittest.mock import Mock, MagicMock, patch
from typing import List, Dict, Any


class TestMemoryReadWriteManager:
    """MemoryReadWriteManager 核心功能测试"""
    
    def test_create_manager(self):
        """创建记忆读写管理器"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager()
        assert manager is not None
    
    def test_recall_memories(self):
        """检索记忆（P2-2：真实 API 为 recall）"""
        from neurova.memory_rw_manager import MemoryReadWriteManager

        manager = MemoryReadWriteManager()

        # 模拟记忆数据
        mock_memories = [
            Mock(content="记忆1", importance=0.8),
            Mock(content="记忆2", importance=0.6),
        ]

        # 模拟底层记忆管理器
        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.recall.return_value = mock_memories

            results = manager.recall_memories("测试查询", limit=2)

            assert len(results) == 2
            mock_mm.recall.assert_called_once()

    def test_get_memories(self):
        """获取记忆列表（P2-2：真实 API 为 get_all_memories，本地切片）"""
        from neurova.memory_rw_manager import MemoryReadWriteManager

        manager = MemoryReadWriteManager()

        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.get_all_memories.return_value = [Mock(), Mock()]

            memories = manager.get_memories(limit=10)

            assert len(memories) == 2

    def test_create_memory(self):
        """创建新记忆（P2-2：真实 API 为 remember）"""
        from neurova.memory_rw_manager import MemoryReadWriteManager

        manager = MemoryReadWriteManager()

        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.remember.return_value = "memory_123"

            memory_id = manager.create_memory(
                content="新记忆",
                importance=0.7,
                metadata={"source": "test"}
            )

            assert memory_id == "memory_123"
            mock_mm.remember.assert_called_once()

    def test_update_memory(self):
        """更新记忆（P2-2：真实 API 为 update_memory；None 字段不透传）"""
        from neurova.memory_rw_manager import MemoryReadWriteManager

        manager = MemoryReadWriteManager()

        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.update_memory.return_value = True

            success = manager.update_memory(
                memory_id="memory_123",
                content="更新后的内容",
                importance=0.9,
            )

            assert success is True
            mock_mm.update_memory.assert_called_once()
            # metadata/temperature 未指定 → 不出现在 kwargs（防 None 覆写）
            kwargs = mock_mm.update_memory.call_args[1]
            assert "metadata" not in kwargs and "temperature" not in kwargs

    def test_delete_memory(self):
        """删除记忆（P2-2：真实 API 为 forget）"""
        from neurova.memory_rw_manager import MemoryReadWriteManager

        manager = MemoryReadWriteManager()

        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.forget.return_value = True

            success = manager.delete_memory("memory_123")

            assert success is True
            mock_mm.forget.assert_called_once()


class TestBatchWrite:
    """批量写入测试"""
    
    def test_batch_write_if_needed(self):
        """检查是否需要批量写入"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager(batch_size=5)
        
        # 添加 4 个记忆（未达到批量阈值）
        for i in range(4):
            manager._write_queue.append(Mock())
        
        # 不应该触发写入
        with patch.object(manager, 'batch_write') as mock_write:
            manager.batch_write_if_needed()
            mock_write.assert_not_called()
    
    def test_batch_write_triggers_at_threshold(self):
        """达到阈值时触发批量写入"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager(batch_size=3)
        
        # 添加 3 个记忆（达到批量阈值）
        for i in range(3):
            manager._write_queue.append(Mock())
        
        with patch.object(manager, 'batch_write') as mock_write:
            manager.batch_write_if_needed()
            mock_write.assert_called_once()
    
    def test_batch_write_flushes_queue(self):
        """批量写入清空队列（P2-2：无 batch_create，逐条 remember）"""
        from neurova.memory_rw_manager import MemoryReadWriteManager, MemoryOperation

        manager = MemoryReadWriteManager()

        # 添加记忆操作到队列
        mock_ops = [
            MemoryOperation(operation_type="create", memory_id="id1", data={"content": "a"}),
            MemoryOperation(operation_type="create", memory_id="id2", data={"content": "b"}),
            MemoryOperation(operation_type="create", memory_id="id3", data={"content": "c"}),
        ]
        manager._write_queue.extend(mock_ops)

        with patch.object(manager, '_memory_manager') as mock_mm:
            manager.batch_write()

            assert len(manager._write_queue) == 0
            assert mock_mm.remember.call_count == 3


class TestTemperatureDecay:
    """温度衰减测试"""
    
    def test_run_decay_if_needed(self):
        """检查是否需要运行衰减"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager(decay_interval=3600)  # 1 小时
        
        # 设置上次衰减时间为刚刚
        manager._last_decay_time = time.time()
        
        with patch.object(manager, 'run_decay_cycle') as mock_decay:
            manager.run_decay_if_needed()
            mock_decay.assert_not_called()
    
    def test_run_decay_cycle(self):
        """运行衰减周期（P2-2：真实 API get_all_memories 返回 dict + update_memory）"""
        from neurova.memory_rw_manager import MemoryReadWriteManager

        manager = MemoryReadWriteManager()

        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.get_all_memories.return_value = [
                {"id": "m1", "temperature": 1.0, "last_accessed_at": "2026-09-11T00:00:00+00:00"},
                {"id": "m2", "temperature": 0.8, "last_accessed_at": "2026-09-10T00:00:00+00:00"},
            ]

            manager.run_decay_cycle()

            # 温度与上次访问时间已衰减 → update_memory 每条一次
            assert mock_mm.update_memory.call_count == 2


class TestStats:
    """统计信息测试"""
    
    def test_get_stats(self):
        """获取统计信息"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager()
        
        # 设置一些状态
        manager._write_queue = [Mock(), Mock()]
        manager._cache_hits = 10
        manager._cache_misses = 5
        
        stats = manager.get_stats()
        
        assert "queue_size" in stats
        assert "cache_hit_rate" in stats
        assert stats["queue_size"] == 2
    
    def test_flush_all(self):
        """清空所有缓存和队列"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager()
        
        # 添加一些数据
        manager._write_queue = [Mock(), Mock()]
        manager._cache = {"key1": Mock(), "key2": Mock()}
        
        manager.flush_all()
        
        assert len(manager._write_queue) == 0
        assert len(manager._cache) == 0