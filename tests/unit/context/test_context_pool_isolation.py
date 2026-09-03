"""
上下文池隔离机制单元测试

测试三层隔离机制：
1. 用户隔离 - 不同用户的上下文完全隔离
2. Agent隔离 - 不同Agent的上下文完全隔离  
3. Session隔离 - 不同Session的上下文完全隔离

测试内容:
1. ContextPool 隔离参数验证
2. 上下文泄露防护
3. 隔离缓存机制
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from neurova.context_pool import (
    ContextSource,
    ContextInput,
    ContextCollector,
    ContextConverter,
    ContextCompressor,
    ContextPool,
    ContextPoolUtils,
)


class TestContextPoolIsolation:
    """ContextPool 隔离机制测试"""
    
    def test_creation_with_isolation_params(self):
        """测试创建带隔离参数的 ContextPool"""
        pool = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_001"
        )
        
        assert pool.user_id == "user_001"
        assert pool.agent_id == "agent_001"
        assert pool.session_id == "session_001"
        assert pool.max_tokens == 16000  # 默认值
    
    def test_creation_requires_user_id(self):
        """测试创建 ContextPool 必须提供 user_id"""
        with pytest.raises(ValueError, match="user_id is required"):
            ContextPool()
    
    def test_creation_requires_agent_id(self):
        """测试创建 ContextPool 必须提供 agent_id"""
        with pytest.raises(ValueError, match="agent_id is required"):
            ContextPool(user_id="user_001")
    
    def test_session_id_optional(self):
        """测试 session_id 是可选的"""
        pool = ContextPool(
            user_id="user_001",
            agent_id="agent_001"
        )
        assert pool.session_id is None
    
    def test_isolation_key_generation(self):
        """测试生成隔离键"""
        pool = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_001"
        )
        
        expected_key = "user_001:agent_001:session_001"
        assert pool.isolation_key == expected_key
    
    def test_isolation_key_without_session(self):
        """测试没有 session_id 时的隔离键"""
        pool = ContextPool(
            user_id="user_001",
            agent_id="agent_001"
        )
        
        expected_key = "user_001:agent_001:default"
        assert pool.isolation_key == expected_key


class TestContextIsolation:
    """上下文隔离测试"""
    
    def test_different_users_isolated(self):
        """测试不同用户的上下文完全隔离"""
        # 创建两个不同用户的 ContextPool
        pool1 = ContextPool(
            user_id="user_001",
            agent_id="agent_001"
        )
        pool2 = ContextPool(
            user_id="user_002",
            agent_id="agent_001"
        )
        
        # 添加上下文
        pool1.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="用户1的私有记忆",
            priority=80
        ))
        pool2.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="用户2的私有记忆",
            priority=80
        ))
        
        # 验证隔离
        contexts1 = pool1.get_contexts()
        contexts2 = pool2.get_contexts()
        
        # 确保上下文不泄露
        for ctx in contexts1:
            assert "用户2" not in ctx.content
        for ctx in contexts2:
            assert "用户1" not in ctx.content
    
    def test_different_agents_isolated(self):
        """测试不同Agent的上下文完全隔离"""
        # 创建同一用户不同Agent的 ContextPool
        pool1 = ContextPool(
            user_id="user_001",
            agent_id="agent_001"
        )
        pool2 = ContextPool(
            agent_id="agent_002",
            user_id="user_001"
        )
        
        # 添加上下文
        pool1.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="Agent1的对话历史",
            priority=70
        ))
        pool2.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="Agent2的对话历史",
            priority=70
        ))
        
        # 验证隔离
        contexts1 = pool1.get_contexts()
        contexts2 = pool2.get_contexts()
        
        # 确保上下文不泄露
        for ctx in contexts1:
            assert "Agent2" not in ctx.content
        for ctx in contexts2:
            assert "Agent1" not in ctx.content
    
    def test_different_sessions_isolated(self):
        """测试不同Session的上下文完全隔离"""
        # 创建同一用户同一Agent不同Session的 ContextPool
        pool1 = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_001"
        )
        pool2 = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_002"
        )
        
        # 添加上下文
        pool1.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="Session1的对话",
            priority=70
        ))
        pool2.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="Session2的对话",
            priority=70
        ))
        
        # 验证隔离
        contexts1 = pool1.get_contexts()
        contexts2 = pool2.get_contexts()
        
        # 确保上下文不泄露
        for ctx in contexts1:
            assert "Session2" not in ctx.content
        for ctx in contexts2:
            assert "Session1" not in ctx.content


class TestIsolatedCaching:
    """隔离缓存机制测试"""
    
    def test_cache_per_isolation_key(self):
        """测试按隔离键缓存"""
        pool = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_001"
        )
        
        # 添加上下文
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="测试记忆",
            priority=80
        ))
        
        # 第一次构建
        result1 = pool.build_context_for_model("gpt-4")
        
        # 第二次构建（应该使用缓存）
        result2 = pool.build_context_for_model("gpt-4")
        
        # 验证结果相同
        assert result1 == result2
    
    def test_cache_invalidation_on_new_context(self):
        """测试添加新上下文时缓存失效"""
        pool = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_001"
        )
        
        # 添加第一个上下文
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="记忆1",
            priority=80
        ))
        
        # 第一次构建
        result1 = pool.build_context_for_model("gpt-4")
        
        # 添加第二个上下文
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="记忆2",
            priority=90
        ))
        
        # 第二次构建（缓存应该失效）
        result2 = pool.build_context_for_model("gpt-4")
        
        # 验证结果不同
        assert result1 != result2
    
    def test_cache_not_shared_between_pools(self):
        """测试不同池之间不共享缓存"""
        pool1 = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_001"
        )
        pool2 = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_002"
        )
        
        # 添加上下文
        pool1.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="池1的记忆",
            priority=80
        ))
        pool2.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="池2的记忆",
            priority=80
        ))
        
        # 构建
        result1 = pool1.build_context_for_model("gpt-4")
        result2 = pool2.build_context_for_model("gpt-4")
        
        # 验证结果不同
        assert result1 != result2


class TestIsolationKeyValidation:
    """隔离键验证测试"""
    
    def test_user_id_cannot_contain_separator(self):
        """测试 user_id 不能包含分隔符"""
        with pytest.raises(ValueError, match="user_id 不能包含分隔符"):
            ContextPool(
                user_id="user:001",
                agent_id="agent_001"
            )
    
    def test_agent_id_cannot_contain_separator(self):
        """测试 agent_id 不能包含分隔符"""
        with pytest.raises(ValueError, match="agent_id 不能包含分隔符"):
            ContextPool(
                user_id="user_001",
                agent_id="agent:001"
            )
    
    def test_session_id_cannot_contain_separator(self):
        """测试 session_id 不能包含分隔符"""
        with pytest.raises(ValueError, match="session_id 不能包含分隔符"):
            ContextPool(
                user_id="user_001",
                agent_id="agent_001",
                session_id="session:001"
            )
    
    def test_valid_ids_with_underscores(self):
        """测试包含下划线的ID是有效的"""
        pool = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_001"
        )
        
        assert pool.user_id == "user_001"
        assert pool.agent_id == "agent_001"
        assert pool.session_id == "session_001"


class TestContextPoolDeepModule:
    """深度模块测试"""
    
    def test_simple_interface_complex_behavior(self):
        """测试简单接口复杂行为"""
        # 简单接口
        pool = ContextPool(
            user_id="user_001",
            agent_id="agent_001",
            session_id="session_001"
        )
        
        # 添加复杂上下文
        contexts = [
            ContextInput(source=ContextSource.SYSTEM_INSTRUCTION, content="系统指令", priority=100),
            ContextInput(source=ContextSource.DEVELOPER_INSTRUCTION, content="开发者指令", priority=95),
            ContextInput(source=ContextSource.MEMORY, content="记忆", priority=80),
            ContextInput(source=ContextSource.CONVERSATION, content="对话", priority=70),
            ContextInput(source=ContextSource.EXPERIENCE, content="经验", priority=60),
            ContextInput(source=ContextSource.EMOTION, content="情感", priority=50),
            ContextInput(source=ContextSource.REFLECTION, content="反思", priority=40),
            ContextInput(source=ContextSource.TOOL_CALL, content="工具调用", priority=30),
            ContextInput(source=ContextSource.MULTIMODAL, content="多模态", priority=20),
            ContextInput(source=ContextSource.USER_INPUT, content="用户输入", priority=100),
        ]
        
        for ctx in contexts:
            pool.add_context(ctx)
        
        # 复杂行为（构建、转换、压缩、隔离）
        result = pool.build_context_for_model("gpt-4")
        
        # 验证结果包含所有上下文
        assert len(result) == len(contexts)
        
        # 验证按优先级排序
        sorted_contexts = pool.get_contexts()
        priorities = [ctx.priority for ctx in sorted_contexts]
        assert priorities == sorted(priorities, reverse=True)
    
    def test_deletion_test(self):
        """测试删除测试 - 删除模块后复杂性是否会分散"""
        # 如果没有 ContextPool，调用者需要：
        # 1. 手动管理隔离参数
        # 2. 手动管理缓存
        # 3. 手动实现上下文收集和转换
        
        # 有了 ContextPool，所有这些都被封装了
        pool = ContextPool(
            user_id="user_001",
            agent_id="agent_001"
        )
        
        # 验证简单接口
        assert hasattr(pool, 'add_context')
        assert hasattr(pool, 'get_contexts')
        assert hasattr(pool, 'build_context_for_model')
        assert hasattr(pool, 'compress_context')
        assert hasattr(pool, 'merge_with')
