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
        """检索记忆"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager()
        
        # 模拟记忆数据
        mock_memories = [
            Mock(content="记忆1", importance=0.8),
            Mock(content="记忆2", importance=0.6),
        ]
        
        # 模拟底层记忆管理器
        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.search.return_value = mock_memories
            
            results = manager.recall_memories("测试查询", limit=2)
            
            assert len(results) == 2
            mock_mm.search.assert_called_once()
    
    def test_get_memories(self):
        """获取记忆列表"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager()
        
        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.get_all.return_value = [Mock(), Mock()]
            
            memories = manager.get_memories(limit=10)
            
            assert len(memories) == 2
    
    def test_create_memory(self):
        """创建新记忆"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager()
        
        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.create.return_value = "memory_123"
            
            memory_id = manager.create_memory(
                content="新记忆",
                importance=0.7,
                metadata={"source": "test"}
            )
            
            assert memory_id == "memory_123"
            mock_mm.create.assert_called_once()
    
    def test_update_memory(self):
        """更新记忆"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager()
        
        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.update.return_value = True
            
            success = manager.update_memory(
                memory_id="memory_123",
                content="更新后的内容",
                importance=0.9,
            )
            
            assert success is True
            mock_mm.update.assert_called_once()
    
    def test_delete_memory(self):
        """删除记忆"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager()
        
        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.delete.return_value = True
            
            success = manager.delete_memory("memory_123")
            
            assert success is True
            mock_mm.delete.assert_called_once()


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
        """批量写入清空队列"""
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
            mock_mm.batch_create.return_value = ["id1", "id2", "id3"]
            
            manager.batch_write()
            
            assert len(manager._write_queue) == 0
            mock_mm.batch_create.assert_called_once()


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
        """运行衰减周期"""
        from neurova.memory_rw_manager import MemoryReadWriteManager
        
        manager = MemoryReadWriteManager()
        
        with patch.object(manager, '_memory_manager') as mock_mm:
            mock_mm.get_all.return_value = [
                Mock(temperature=1.0, last_accessed=time.time() - 3600),
                Mock(temperature=0.8, last_accessed=time.time() - 7200),
            ]
            mock_mm.update.return_value = True
            
            manager.run_decay_cycle()
            
            # 应该更新了温度
            assert mock_mm.update.call_count == 2


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