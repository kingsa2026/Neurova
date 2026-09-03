"""
MemoryRecordStore 深度模块测试（V2）

测试 MemoryRecordStore 作为深度模块的行为：
1. 小接口（5个核心方法）
2. 深实现（隐藏存储细节）
3. 可测试性（通过接口测试）
"""

import pytest
import tempfile
import shutil

from neurova.cognitive_layers.memory_layer.memory_record_store import (
    MemoryRecordStore,
    create_memory_record_store,
)
from neurova.cognitive_layers.memory_layer.storage import MemoryStorage


class TestMemoryRecordStoreInterface:
    """测试 MemoryRecordStore 接口设计"""
    
    @pytest.fixture
    def store(self):
        """创建 MemoryRecordStore 实例"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        return MemoryRecordStore(storage)
    
    def test_interface_methods(self, store):
        """验证接口方法存在且签名正确"""
        # 核心CRUD方法
        assert hasattr(store, 'save')
        assert hasattr(store, 'get')
        assert hasattr(store, 'delete')
        assert hasattr(store, 'update')
        assert hasattr(store, 'count')
        
        # 扩展方法
        assert hasattr(store, 'exists')
        assert hasattr(store, 'batch_save')
        assert hasattr(store, 'batch_delete')
    
    def test_save_returns_memory_id(self, store):
        """测试 save 返回 memory_id"""
        memory_id = store.save(content="测试", memory_type="episodic")
        assert isinstance(memory_id, str)
        assert memory_id.startswith("mem_")
    
    def test_get_returns_dict_or_none(self, store):
        """测试 get 返回 Dict 或 None"""
        # 不存在时返回 None
        result = store.get("nonexistent")
        assert result is None
        
        # 存在时返回 Dict
        memory_id = store.save(content="测试", memory_type="episodic")
        result = store.get(memory_id)
        assert isinstance(result, dict)
    
    def test_delete_returns_bool(self, store):
        """测试 delete 返回 bool"""
        memory_id = store.save(content="测试", memory_type="episodic")
        
        # 删除成功
        result = store.delete(memory_id)
        assert isinstance(result, bool)
        assert result is True
        
        # 删除不存在的记录
        result = store.delete("nonexistent")
        assert result is False
    
    def test_update_returns_bool(self, store):
        """测试 update 返回 bool"""
        memory_id = store.save(content="测试", memory_type="episodic")
        
        # 更新成功
        result = store.update(memory_id, content="更新")
        assert isinstance(result, bool)
        assert result is True
        
        # 更新不存在的记录
        result = store.update("nonexistent", content="更新")
        assert result is False
    
    def test_count_returns_int(self, store):
        """测试 count 返回 int"""
        result = store.count()
        assert isinstance(result, int)
        assert result == 0


class TestMemoryRecordStoreBehavior:
    """测试 MemoryRecordStore 行为"""
    
    @pytest.fixture
    def store(self):
        """创建 MemoryRecordStore 实例"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        return MemoryRecordStore(storage)
    
    def test_save_and_get_cycle(self, store):
        """测试保存-获取完整周期"""
        # Given: 记忆内容
        content = "测试记忆内容"
        memory_type = "episodic"
        tags = ["test", "unit"]
        metadata = {"source": "test"}
        
        # When: 保存记忆
        memory_id = store.save(
            content=content,
            memory_type=memory_type,
            tags=tags,
            metadata=metadata,
        )
        
        # Then: 获取记忆并验证
        record = store.get(memory_id)
        assert record["content"] == content
        assert record["memory_type"] == memory_type
        assert record["tags"] == tags
        assert record["metadata"] == metadata
    
    def test_delete_removes_record(self, store):
        """测试删除记录"""
        # Given: 一个已保存的记录
        memory_id = store.save(content="待删除", memory_type="episodic")
        
        # When: 删除记录
        store.delete(memory_id)
        
        # Then: 记录不存在
        assert store.get(memory_id) is None
        assert store.count() == 0
    
    def test_update_modifies_record(self, store):
        """测试更新记录"""
        # Given: 一个已保存的记录
        memory_id = store.save(content="原始内容", memory_type="episodic")
        
        # When: 更新记录
        store.update(memory_id, content="新内容", importance=0.8)
        
        # Then: 记录已更新
        record = store.get(memory_id)
        assert record["content"] == "新内容"
        assert record["importance"] == 0.8
    
    def test_exists_checks_record(self, store):
        """测试记录存在性检查"""
        # Given: 一个已保存的记录
        memory_id = store.save(content="存在性测试", memory_type="episodic")
        
        # Then: 存在性检查
        assert store.exists(memory_id) is True
        assert store.exists("nonexistent") is False
    
    def test_batch_operations(self, store):
        """测试批量操作"""
        # Given: 多条记录
        records = [
            {"content": f"批量记忆{i}", "memory_type": "episodic"}
            for i in range(5)
        ]
        
        # When: 批量保存
        memory_ids = store.batch_save(records)
        
        # Then: 所有记录都保存成功
        assert len(memory_ids) == 5
        assert store.count() == 5
        
        # When: 批量删除前3条
        deleted = store.batch_delete(memory_ids[:3])
        
        # Then: 删除成功
        assert deleted == 3
        assert store.count() == 2


class TestMemoryRecordStoreIsolation:
    """测试 MemoryRecordStore 隔离上下文"""
    
    @pytest.fixture
    def store(self):
        """创建 MemoryRecordStore 实例"""
        temp_dir = tempfile.mkdtemp()
        storage = MemoryStorage(temp_dir)
        return MemoryRecordStore(storage)
    
    def test_save_with_agent_isolation(self, store):
        """测试 agent 隔离"""
        from neurova.cognitive_layers.memory_layer.isolation import IsolationContext
        
        # Given: 不同 agent 的隔离上下文
        ctx_agent1 = IsolationContext(agent_id="agent_1")
        ctx_agent2 = IsolationContext(agent_id="agent_2")
        
        # When: 保存记忆
        id1 = store.save(content="Agent1记忆", memory_type="episodic", isolation_context=ctx_agent1)
        id2 = store.save(content="Agent2记忆", memory_type="episodic", isolation_context=ctx_agent2)
        
        # Then: 记忆包含正确的 agent_id
        record1 = store.get(id1)
        record2 = store.get(id2)
        
        assert record1["agent_id"] == "agent_1"
        assert record2["agent_id"] == "agent_2"


class TestMemoryRecordStoreFactory:
    """测试工厂函数"""
    
    def test_create_memory_record_store(self):
        """测试工厂函数创建实例"""
        store = create_memory_record_store()
        assert isinstance(store, MemoryRecordStore)
        assert store.count() == 0
