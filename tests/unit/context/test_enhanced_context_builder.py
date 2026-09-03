"""
EnhancedContextBuilder 测试

验证：
- 上下文构建的核心功能
- 记忆检索集成
- 会话管理
- 缓存和压缩集成
- 统计信息
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from typing import List, Dict, Any


class TestEnhancedContextBuilder:
    """EnhancedContextBuilder 核心功能测试"""
    
    def test_create_builder(self):
        """创建增强上下文构建器"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        assert builder is not None
    
    def test_build_context(self):
        """构建上下文"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        context = builder.build_context(
            query="测试查询",
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert context is not None
        assert isinstance(context, dict)
    
    def test_retrieve_memories(self):
        """检索相关记忆"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        with patch.object(builder, '_memory_rw_manager') as mock_mrw:
            mock_mrw.recall_memories.return_value = [
                Mock(content="相关记忆1"),
                Mock(content="相关记忆2"),
            ]
            
            memories = builder._retrieve_memories("测试查询", limit=5)
            
            assert len(memories) == 2
            mock_mrw.recall_memories.assert_called_once()
    
    def test_add_message_to_session(self):
        """添加消息到会话"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        builder.add_message_to_session(
            session_id="session_123",
            role="user",
            content="你好",
        )
        
        history = builder.get_session_history("session_123")
        assert len(history) == 1
        assert history[0]["role"] == "user"
    
    def test_get_session_history(self):
        """获取会话历史"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        builder.add_message_to_session("s1", "user", "消息1")
        builder.add_message_to_session("s1", "assistant", "回复1")
        builder.add_message_to_session("s1", "user", "消息2")
        
        history = builder.get_session_history("s1")
        assert len(history) == 3
    
    def test_clear_session(self):
        """清除会话"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        builder.add_message_to_session("s1", "user", "消息1")
        builder.clear_session("s1")
        
        history = builder.get_session_history("s1")
        assert len(history) == 0
    
    def test_create_memory(self):
        """通过构建器创建记忆"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        with patch.object(builder, '_memory_rw_manager') as mock_mrw:
            mock_mrw.create_memory.return_value = "memory_789"
            
            memory_id = builder.create_memory(
                content="重要信息",
                importance=0.9,
            )
            
            assert memory_id == "memory_789"
            mock_mrw.create_memory.assert_called_once()
    
    def test_flush_all(self):
        """刷新所有缓存"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        with patch.object(builder, '_memory_rw_manager') as mock_mrw:
            builder.flush_all()
            mock_mrw.flush_all.assert_called_once()


class TestContextBuilding:
    """上下文构建逻辑测试"""
    
    def test_build_context_returns_dict(self):
        """构建上下文返回字典"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        context = builder.build_context(query="测试")
        
        assert isinstance(context, dict)
    
    def test_build_context_includes_memories(self):
        """构建上下文包含记忆"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        with patch.object(builder, '_retrieve_memories') as mock_retrieve:
            mock_retrieve.return_value = [
                Mock(content="记忆内容", importance=0.8),
            ]
            
            context = builder.build_context(query="测试", include_memories=True)
            
            assert "memories" in context or "context" in context
    
    def test_build_context_with_session(self):
        """带会话的上下文构建"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        # 先添加一些会话历史
        builder.add_message_to_session("s1", "user", "你好")
        builder.add_message_to_session("s1", "assistant", "你好！")
        
        context = builder.build_context(
            query="继续对话",
            session_id="s1",
        )
        
        assert context is not None


class TestSessionManagement:
    """会话管理测试"""
    
    def test_multiple_sessions(self):
        """多个会话"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        builder.add_message_to_session("s1", "user", "消息A")
        builder.add_message_to_session("s2", "user", "消息B")
        
        assert len(builder.get_session_history("s1")) == 1
        assert len(builder.get_session_history("s2")) == 1
    
    def test_session_stats(self):
        """会话统计"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        builder.add_message_to_session("s1", "user", "消息1")
        builder.add_message_to_session("s1", "assistant", "回复1")
        
        stats = builder.get_stats()
        assert "session_count" in stats or "sessions" in stats


class TestMaintenance:
    """维护操作测试"""
    
    def test_perform_maintenance(self):
        """执行维护操作"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        # 应该不抛出异常
        builder._perform_maintenance()
    
    def test_get_cache_summary(self):
        """获取缓存摘要"""
        from neurova.enhanced_context_builder import EnhancedContextBuilder
        
        builder = EnhancedContextBuilder()
        
        summary = builder.get_cache_summary()
        assert summary is not None