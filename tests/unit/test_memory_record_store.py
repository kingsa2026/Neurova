"""
MemoryRecordStore 深度模块测试

测试 MemoryRecordStore 的纯 CRUD 行为，
不关心存储实现细节（JSON/SQLite/内存）。
"""

import pytest
import tempfile
import shutil
from pathlib import Path

from neurova.cognitive_layers.memory_layer.storage import MemoryRecord


class TestMemoryRecordStore:
    """MemoryRecordStore 行为测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def store(self, temp_dir):
        """创建 MemoryRecordStore 实例"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        return MemoryStorage(temp_dir)
    
    def test_save_and_get(self, store):
        """测试保存和获取记忆"""
        # Given: 一个记忆内容
        content = "测试记忆内容"
        memory_type = "episodic"
        
        # When: 保存记忆
        memory_id = store.save(content=content, memory_type=memory_type)
        
        # Then: 可以获取到记忆
        record = store.get(memory_id)
        assert record is not None
        assert record["content"] == content
        assert record["memory_type"] == memory_type
    
    def test_save_with_isolation_context(self, store):
        """测试带隔离上下文的保存"""
        # Given: 隔离上下文
        from neurova.cognitive_layers.memory_layer.isolation import IsolationContext
        ctx = IsolationContext(agent_id="agent_1", neuser_id="user_1")
        
        # When: 保存记忆
        memory_id = store.save(
            content="隔离记忆",
            memory_type="episodic",
            isolation_context=ctx
        )
        
        # Then: 记忆包含隔离字段
        record = store.get(memory_id)
        assert record["agent_id"] == "agent_1"
        assert record["neuser_id"] == "user_1"
    
    def test_delete(self, store):
        """测试删除记忆"""
        # Given: 一个已保存的记忆
        memory_id = store.save(content="待删除", memory_type="episodic")
        
        # When: 删除记忆
        result = store.delete(memory_id)
        
        # Then: 删除成功，记忆不存在
        assert result is True
        assert store.get(memory_id) is None
    
    def test_delete_nonexistent(self, store):
        """测试删除不存在的记忆"""
        # When: 删除不存在的记忆
        result = store.delete("nonexistent_id")
        
        # Then: 返回 False
        assert result is False
    
    def test_update_memory(self, store):
        """测试更新记忆"""
        # Given: 一个已保存的记忆
        memory_id = store.save(content="原始内容", memory_type="episodic")
        
        # When: 更新记忆
        result = store.update_memory(memory_id, content="更新后内容")
        
        # Then: 记忆已更新
        assert result is True
        record = store.get(memory_id)
        assert record["content"] == "更新后内容"
    
    def test_increment_access(self, store):
        """测试增加访问计数"""
        # Given: 一个已保存的记忆
        memory_id = store.save(content="访问计数测试", memory_type="episodic")
        
        # When: 增加访问计数
        result = store.increment_access(memory_id)
        
        # Then: 访问计数增加
        assert result is True
        record = store.get(memory_id)
        assert record["access_count"] == 1
    
    def test_count(self, store):
        """测试计数功能"""
        # Given: 多个记忆
        store.save(content="记忆1", memory_type="episodic")
        store.save(content="记忆2", memory_type="semantic")
        
        # When: 获取计数
        count = store.count()
        
        # Then: 返回正确数量
        assert count == 2
    
    def test_list_all(self, store):
        """测试列出所有记忆"""
        # Given: 多个记忆
        store.save(content="记忆1", memory_type="episodic")
        store.save(content="记忆2", memory_type="semantic")
        
        # When: 列出所有记忆
        all_records = store.list_all()
        
        # Then: 返回所有记忆
        assert len(all_records) == 2
    
    def test_clear(self, store):
        """测试清空所有记忆"""
        # Given: 多个记忆
        store.save(content="记忆1", memory_type="episodic")
        store.save(content="记忆2", memory_type="semantic")
        
        # When: 清空记忆
        count = store.clear()
        
        # Then: 所有记忆被删除
        assert count == 2
        assert store.count() == 0
    
    def test_thread_safety(self, store):
        """测试线程安全性"""
        import threading
        
        # Given: 多个线程同时操作
        results = []
        
        def save_memory(i):
            memory_id = store.save(content=f"线程记忆{i}", memory_type="episodic")
            results.append(memory_id)
        
        threads = [threading.Thread(target=save_memory, args=(i,)) for i in range(10)]
        
        # When: 并发执行
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # Then: 所有操作成功
        assert len(results) == 10
        assert store.count() == 10
