"""
统一隔离机制测试

测试三层隔离：agent_id、neuser_id、user_id
"""
import pytest
import tempfile
import shutil
from neurova.cognitive_layers.memory_layer.isolation import IsolationContext


class TestIsolationContext:
    """测试隔离上下文"""
    
    def test_default_context(self):
        """测试默认隔离上下文"""
        ctx = IsolationContext()
        assert ctx.agent_id == "default"
        assert ctx.neuser_id == "default"
        assert ctx.user_id == "default"
        assert ctx.key == "default:default:default"
    
    def test_custom_context(self):
        """测试自定义隔离上下文"""
        ctx = IsolationContext(
            agent_id="agent_1",
            neuser_id="neuser_1", 
            user_id="user_1"
        )
        assert ctx.agent_id == "agent_1"
        assert ctx.neuser_id == "neuser_1"
        assert ctx.user_id == "user_1"
        assert ctx.key == "agent_1:neuser_1:user_1"
    
    def test_partial_context(self):
        """测试部分隔离上下文"""
        ctx = IsolationContext(agent_id="agent_1")
        assert ctx.agent_id == "agent_1"
        assert ctx.neuser_id == "default"
        assert ctx.user_id == "default"
        assert ctx.key == "agent_1:default:default"


class TestStorageIsolation:
    """测试存储层隔离"""
    
    def test_storage_with_isolation(self):
        """测试存储层使用隔离上下文"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        # 使用临时目录避免数据污染
        tmpdir = tempfile.mkdtemp()
        try:
            # 创建存储实例
            storage = MemoryStorage(storage_dir=tmpdir)
            
            # 保存记忆时传入隔离上下文
            ctx = IsolationContext(agent_id="agent_1", user_id="user_1")
            memory_id = storage.save(
                content="测试记忆",
                memory_type="semantic",
                isolation_context=ctx
            )
            
            # 查询时使用隔离上下文
            memories = storage.query(isolation_context=ctx)
            assert len(memories) == 1
            assert memories[0]["content"] == "测试记忆"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_storage_isolation_between_users(self):
        """测试不同用户的存储隔离"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        tmpdir = tempfile.mkdtemp()
        try:
            storage = MemoryStorage(storage_dir=tmpdir)
            
            # 用户1保存记忆
            ctx1 = IsolationContext(agent_id="agent_1", user_id="user_1")
            storage.save(content="用户1的记忆", memory_type="semantic", isolation_context=ctx1)
            
            # 用户2保存记忆
            ctx2 = IsolationContext(agent_id="agent_1", user_id="user_2")
            storage.save(content="用户2的记忆", memory_type="semantic", isolation_context=ctx2)
            
            # 查询时应该隔离
            memories1 = storage.query(isolation_context=ctx1)
            memories2 = storage.query(isolation_context=ctx2)
            
            assert len(memories1) == 1
            assert len(memories2) == 1
            assert memories1[0]["content"] == "用户1的记忆"
            assert memories2[0]["content"] == "用户2的记忆"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestSleepIsolation:
    """测试睡眠整合隔离"""
    
    def test_sleep_with_isolation(self):
        """测试睡眠整合使用隔离上下文"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation, MemoryRecord
        
        # 创建睡眠整合实例
        sleep = SleepConsolidation()
        
        # 创建记忆记录
        records = [
            MemoryRecord(id="1", content="记忆1", temperature=50.0),
            MemoryRecord(id="2", content="记忆2", temperature=50.0),
        ]
        
        # 执行睡眠整合
        ctx = IsolationContext(agent_id="agent_1", user_id="user_1")
        result = sleep.consolidate(records, isolation_context=ctx)
        
        assert len(result) == 2  # 返回整合后的记忆
    
    def test_sleep_isolation_between_agents(self):
        """测试不同Agent的睡眠整合隔离"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation, MemoryRecord
        
        sleep = SleepConsolidation()
        
        # Agent1的记忆
        records1 = [
            MemoryRecord(id="1", content="Agent1的记忆", temperature=50.0),
        ]
        
        # Agent2的记忆  
        records2 = [
            MemoryRecord(id="2", content="Agent2的记忆", temperature=50.0),
        ]
        
        # 分别整合
        ctx1 = IsolationContext(agent_id="agent_1")
        ctx2 = IsolationContext(agent_id="agent_2")
        
        merged_memories1, merge_results1 = sleep.consolidate(records1, isolation_context=ctx1)
        merged_memories2, merge_results2 = sleep.consolidate(records2, isolation_context=ctx2)
        
        # 验证隔离
        assert len(merged_memories1) == 1
        assert len(merged_memories2) == 1
        assert merged_memories1[0].content == "Agent1的记忆"
        assert merged_memories2[0].content == "Agent2的记忆"
        # 验证隔离上下文继承
        assert merged_memories1[0].agent_id == "agent_1"
        assert merged_memories2[0].agent_id == "agent_2"


class TestModelsIsolation:
    """测试模型层隔离"""
    
    def test_memory_with_isolation(self):
        """测试Memory模型使用隔离上下文"""
        from neurova.cognitive_layers.memory_layer.models import Memory, MemoryType
        
        ctx = IsolationContext(agent_id="agent_1", user_id="user_1")
        
        memory = Memory(
            content="测试记忆",
            memory_type=MemoryType.SEMANTIC,
            isolation_context=ctx
        )
        
        assert memory.agent_id == "agent_1"
        assert memory.user_id == "user_1"
        assert memory.neuser_id == "default"
    
    def test_memory_serialization(self):
        """测试Memory序列化包含隔离信息"""
        from neurova.cognitive_layers.memory_layer.models import Memory, MemoryType
        
        ctx = IsolationContext(agent_id="agent_1", neuser_id="neuser_1", user_id="user_1")
        
        memory = Memory(
            content="测试记忆",
            memory_type=MemoryType.SEMANTIC,
            isolation_context=ctx
        )
        
        data = memory.to_dict()
        assert data["agent_id"] == "agent_1"
        assert data["neuser_id"] == "neuser_1"
        assert data["user_id"] == "user_1"
    
    def test_memory_deserialization(self):
        """测试Memory反序列化恢复隔离信息"""
        from neurova.cognitive_layers.memory_layer.models import Memory
        
        data = {
            "id": "test_id",
            "content": "测试记忆",
            "memory_type": "semantic",
            "agent_id": "agent_1",
            "neuser_id": "neuser_1",
            "user_id": "user_1"
        }
        
        memory = Memory.from_dict(data)
        assert memory.agent_id == "agent_1"
        assert memory.neuser_id == "neuser_1"
        assert memory.user_id == "user_1"


class TestIntegrationIsolation:
    """测试集成隔离"""
    
    def test_full_isolation_flow(self):
        """测试完整的隔离流程"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation, MemoryRecord
        
        tmpdir = tempfile.mkdtemp()
        try:
            # 1. 存储层保存
            storage = MemoryStorage(storage_dir=tmpdir)
            ctx = IsolationContext(agent_id="agent_1", neuser_id="neuser_1", user_id="user_1")
            
            memory_id = storage.save(
                content="集成测试记忆",
                memory_type="semantic",
                isolation_context=ctx
            )
            
            # 2. 查询存储
            memories = storage.query(isolation_context=ctx)
            assert len(memories) == 1
            
            # 3. 转换为睡眠整合格式
            records = [MemoryRecord(
                id=memories[0]["id"],
                content=memories[0]["content"],
                temperature=50.0
            )]
            
            # 4. 睡眠整合
            sleep = SleepConsolidation()
            merged_memories, merge_results = sleep.consolidate(records, isolation_context=ctx)
            
            assert len(merged_memories) == 1
            assert merged_memories[0].content == "集成测试记忆"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_cross_isolation_boundary(self):
        """测试跨隔离边界不泄露"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        tmpdir = tempfile.mkdtemp()
        try:
            storage = MemoryStorage(storage_dir=tmpdir)
            
            # 用户1保存记忆
            ctx1 = IsolationContext(agent_id="agent_1", user_id="user_1")
            storage.save(content="用户1记忆", memory_type="semantic", isolation_context=ctx1)
            
            # 用户2查询
            ctx2 = IsolationContext(agent_id="agent_1", user_id="user_2")
            memories = storage.query(isolation_context=ctx2)
            
            # 应该为空
            assert len(memories) == 0
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestSharedIsolation:
    """测试跨 agent 共享记忆"""
    
    def test_shared_memory_visible_across_agents(self):
        """测试共享记忆可以被不同 agent 访问"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        tmpdir = tempfile.mkdtemp()
        try:
            storage = MemoryStorage(storage_dir=tmpdir)
            
            # Agent1 保存共享记忆
            ctx_shared = IsolationContext(agent_id="agent_1", shared=True)
            storage.save(content="公共知识", memory_type="semantic", isolation_context=ctx_shared)
            
            # Agent2 查询（使用不同的 agent_id）
            ctx_agent2 = IsolationContext(agent_id="agent_2")
            memories = storage.query(isolation_context=ctx_agent2)
            
            assert len(memories) == 1
            assert memories[0]["content"] == "公共知识"
            assert memories[0]["shared"] is True
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_shared_memory_with_neuser_boundary(self):
        """测试共享记忆仍受 neuser_id 隔离"""
        from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
        
        tmpdir = tempfile.mkdtemp()
        try:
            storage = MemoryStorage(storage_dir=tmpdir)
            
            # neuser_1 的共享记忆
            ctx1 = IsolationContext(agent_id="agent_1", neuser_id="neuser_1", shared=True)
            storage.save(content="neuser_1的知识", memory_type="semantic", isolation_context=ctx1)
            
            # neuser_2 查询
            ctx2 = IsolationContext(agent_id="agent_2", neuser_id="neuser_2")
            memories = storage.query(isolation_context=ctx2)
            
            # 应该为空，因为 neuser_id 不匹配
            assert len(memories) == 0
            
            # neuser_1 的 agent_2 查询应该能看到
            ctx3 = IsolationContext(agent_id="agent_2", neuser_id="neuser_1")
            memories = storage.query(isolation_context=ctx3)
            
            assert len(memories) == 1
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    
    def test_shared_isolation_context_switch(self):
        """测试 IsolationContext 的 shared 开关"""
        ctx_normal = IsolationContext(agent_id="agent_1", user_id="user_1")
        assert ctx_normal.shared is False
        
        ctx_shared = ctx_normal.with_shared(True)
        assert ctx_shared.shared is True
        assert ctx_shared.agent_id == "agent_1"
        assert ctx_shared.user_id == "user_1"
        
        # 序列化/反序列化
        data = ctx_shared.to_dict()
        assert data["shared"] is True
        
        ctx_restored = IsolationContext.from_dict(data)
        assert ctx_restored.shared is True
    
    def test_memory_model_shared_field(self):
        """测试 Memory 模型的 shared 字段"""
        from neurova.cognitive_layers.memory_layer.models import Memory, MemoryType
        
        # 通过 isolation_context 设置 shared
        ctx = IsolationContext(agent_id="agent_1", shared=True)
        memory = Memory(content="共享记忆", memory_type=MemoryType.SEMANTIC, isolation_context=ctx)
        
        assert memory.shared is True
        assert memory.agent_id == "agent_1"
        
        # 序列化/反序列化
        data = memory.to_dict()
        assert data["shared"] is True
        
        memory2 = Memory.from_dict(data)
        assert memory2.shared is True
