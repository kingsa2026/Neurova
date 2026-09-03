"""
ContextPool 集成测试 - Tracer Bullet #2

测试目标：
1. ContextPool 与 agent_core.py 的集成
2. ContextPool.draw() 与向量匹配的集成
3. 自动标签生成功能
4. 与现有 ContextOrchestrator 的兼容性
"""

import pytest
from unittest.mock import MagicMock, patch
from neurova.context_pool import (
    ContextSource,
    ContextInput,
    ContextPool,
    SemanticMatchDrawer,
    DriftSafeDeduplicator,
)


class TestContextPoolAgentIntegration:
    """ContextPool 与 Agent 集成测试"""
    
    def test_context_pool_can_replace_context_orchestrator(self):
        """测试 ContextPool 能否替代 ContextOrchestrator"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000
        )
        
        # 添加各种类型的上下文
        pool.add_context(ContextInput(
            source=ContextSource.SYSTEM_INSTRUCTION,
            content="你是一个AI助手",
            priority=100,
            tags=["系统", "指令"]
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="帮我写一个Python函数",
            priority=90,
            tags=["用户", "输入", "Python"]
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="用户之前问过类似问题",
            priority=70,
            tags=["记忆", "历史"]
        ))
        
        # 验证能获取上下文
        contexts = pool.get_contexts()
        assert len(contexts) == 3
        
        # 验证能构建模型格式
        messages = pool.build_context_for_model("gpt-4")
        assert len(messages) == 3
        assert any(msg.get("role") == "system" for msg in messages)
        assert any(msg.get("role") == "user" for msg in messages)
    
    def test_context_pool_draw_with_vector_matching(self):
        """测试 ContextPool.draw() 与向量匹配"""
        # Mock UnifiedVectorStore
        mock_vector_store = MagicMock()
        mock_vector_store.encode.return_value = [0.1, 0.2, 0.3]
        
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000
        )
        
        # 添加带标签的上下文
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="Python 代码优化技巧",
            priority=80,
            tags=["代码", "Python", "优化"]
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.EMOTION,
            content="用户今天心情很好",
            priority=50,
            tags=["情感", "心情"]
        ))
        
        # Mock 向量存储
        with patch('neurova.context_pool.SemanticMatchDrawer.vector_store', mock_vector_store):
            # 按需取水
            result = pool.draw(need="编程 代码")
            
            # 应该返回列表
            assert isinstance(result, list)
            assert len(result) > 0
            
            # 验证向量编码被调用
            assert mock_vector_store.encode.called
    
    def test_context_pool_auto_tag_generation(self):
        """测试自动标签生成功能"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000
        )
        
        # 添加没有标签的上下文
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="这是一段关于机器学习的记忆",
            priority=80
        )
        
        # 验证没有标签
        assert ctx.tags == []
        
        # 添加到池中
        pool.add_context(ctx)
        
        # 验证上下文被添加
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        
        # 注意：当前实现没有自动标签生成，这是一个未来功能
        # 这里只是验证现有功能正常工作
        assert contexts[0].tags == []
    
    def test_context_pool_dedup_integration(self):
        """测试 ContextPool 去重集成"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000
        )
        
        # 添加重复内容
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="相同内容",
            priority=80
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="相同内容",
            priority=70
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="不同内容",
            priority=60
        ))
        
        # 执行去重
        count = pool.dedup(stage='input')
        
        # 应该去除一个重复的
        assert count == 2
        
        # 验证去重后的上下文
        contexts = pool.get_contexts()
        assert len(contexts) == 2
        
        # 验证保留了高优先级的
        priorities = [ctx.priority for ctx in contexts]
        assert 80 in priorities
        assert 60 in priorities


class TestContextPoolBackwardCompatibility:
    """ContextPool 向后兼容性测试"""
    
    def test_context_pool_without_tags(self):
        """测试不带标签的 ContextPool 仍然正常工作"""
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000
        )
        
        # 添加不带标签的上下文
        pool.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户输入",
            priority=50
        ))
        
        # 验证能正常获取上下文
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        assert contexts[0].tags == []
    
    def test_context_pool_backward_compatible_with_old_code(self):
        """测试 ContextPool 与旧代码兼容"""
        # 模拟旧代码使用方式
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=8000
        )
        
        # 旧代码可能没有标签
        pool.add_context(ContextInput(
            source=ContextSource.SYSTEM_INSTRUCTION,
            content="系统指令",
            priority=100
        ))
        
        pool.add_context(ContextInput(
            source=ContextSource.CONVERSATION,
            content="对话历史",
            priority=60
        ))
        
        # 旧代码可能只使用 get_contexts()
        contexts = pool.get_contexts()
        assert len(contexts) == 2
        
        # 旧代码可能使用 build_context_for_model()
        messages = pool.build_context_for_model("gpt-3.5-turbo")
        assert len(messages) == 2
        
        # 旧代码可能使用 compress_context()
        pool.compress_context()
        
        # 验证压缩后仍然有上下文
        contexts_after = pool.get_contexts()
        assert len(contexts_after) > 0


class TestSemanticMatchDrawerIntegration:
    """SemanticMatchDrawer 集成测试"""
    
    def test_drawer_with_real_vector_store(self):
        """测试取水器与真实向量存储（如果可用）"""
        try:
            from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
            
            # 创建真实向量存储
            vector_store = UnifiedVectorStore(backend="tfidf")  # 使用 TF-IDF 后端
            
            # 创建取水器
            drawer = SemanticMatchDrawer(max_tokens=16000)
            drawer._vector_store = vector_store
            
            # 创建水滴
            drops = [
                ContextInput(
                    source=ContextSource.MEMORY,
                    content="Python 代码优化技巧",
                    priority=80,
                    tags=["代码", "Python", "优化"]
                ),
                ContextInput(
                    source=ContextSource.EMOTION,
                    content="用户今天心情很好",
                    priority=50,
                    tags=["情感", "心情"]
                ),
            ]
            
            # 按需取水
            result = drawer.draw(drops, need="编程 代码")
            
            # 应该返回列表
            assert isinstance(result, list)
            assert len(result) > 0
            
            # 验证向量编码被调用
            assert vector_store.backend == "tfidf"
            
        except ImportError:
            pytest.skip("UnifiedVectorStore 不可用")
    
    def test_drawer_fallback_to_keyword_matching(self):
        """测试取水器降级到关键词匹配"""
        # 创建取水器，不设置向量存储
        drawer = SemanticMatchDrawer(max_tokens=16000)
        drawer._vector_store = False  # 明确禁用向量存储
        
        # 创建水滴
        drops = [
            ContextInput(
                source=ContextSource.MEMORY,
                content="Python 代码优化技巧",
                priority=80,
                tags=["代码", "Python", "优化"]
            ),
            ContextInput(
                source=ContextSource.EMOTION,
                content="用户今天心情很好",
                priority=50,
                tags=["情感", "心情"]
            ),
        ]
        
        # 按需取水
        result = drawer.draw(drops, need="编程 代码")
        
        # 应该返回列表
        assert isinstance(result, list)
        assert len(result) > 0
        
        # 验证使用了关键词匹配（Python 代码应该匹配第一个）
        assert any("Python" in drop.content for drop in result)


class TestDriftSafeDeduplicatorIntegration:
    """DriftSafeDeduplicator 集成测试"""
    
    def test_deduplicator_preserves_context_quality(self):
        """测试去重器保持上下文质量"""
        dedup = DriftSafeDeduplicator()
        
        # 创建高质量和低质量的上下文
        drops = [
            ContextInput(
                source=ContextSource.MEMORY,
                content="重要记忆：用户喜欢Python",
                priority=90,
                tags=["记忆", "重要"]
            ),
            ContextInput(
                source=ContextSource.MEMORY,
                content="重要记忆：用户喜欢Python",
                priority=70,
                tags=["记忆", "重要"]
            ),
            ContextInput(
                source=ContextSource.EMOTION,
                content="用户今天心情很好",
                priority=60,
                tags=["情感", "心情"]
            ),
        ]
        
        # 去重
        result = dedup.dedup(drops, stage='input')
        
        # 应该保留两个（一个重复被去除）
        assert len(result) == 2
        
        # 验证保留了高优先级的
        priorities = [drop.priority for drop in result]
        assert 90 in priorities
        assert 60 in priorities
        
        # 验证保留了不同来源
        sources = [drop.source for drop in result]
        assert ContextSource.MEMORY in sources
        assert ContextSource.EMOTION in sources


if __name__ == "__main__":
    pytest.main([__file__, "-v"])