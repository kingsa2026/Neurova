"""
活水上下文池单元测试

测试内容:
1. ContextDrop 数据类（带标签、哈希）
2. SemanticMatchDrawer 向量语义匹配取水器
3. DriftSafeDeduplicator 防漂移去重器
"""

import pytest
from datetime import datetime, timedelta
from neurova.context_pool import (
    ContextSource,
    ContextInput,
    ContextPool,
)


class TestContextDrop:
    """ContextDrop 数据类测试 - 验证标签和哈希支持"""
    
    def test_context_input_with_tags(self):
        """测试 ContextInput 支持 tags 字段"""
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="这是一条记忆",
            priority=80,
            tags=["记忆", "重要", "情感"]
        )
        
        assert ctx.tags == ["记忆", "重要", "情感"]
    
    def test_context_input_tags_default_empty(self):
        """测试 tags 默认为空列表"""
        ctx = ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户输入"
        )
        
        assert ctx.tags == []
    
    def test_context_input_with_hash(self):
        """测试 ContextInput 支持 hash 字段"""
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="这是一条记忆",
            hash="abc123"
        )
        
        assert ctx.hash == "abc123"
    
    def test_context_input_hash_auto_generated(self):
        """测试 hash 自动生成"""
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="这是一条记忆"
        )
        
        # hash 应该自动生成
        assert ctx.hash is not None
        assert len(ctx.hash) > 0
    
    def test_context_input_to_dict_with_tags(self):
        """测试 to_dict 包含 tags"""
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="记忆内容",
            tags=["标签1", "标签2"]
        )
        
        data = ctx.to_dict()
        assert "tags" in data
        assert data["tags"] == ["标签1", "标签2"]
    
    def test_context_input_timestamps(self):
        """测试 created_at 和 updated_at 字段"""
        now = datetime.now()
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="记忆内容"
        )
        
        # 应该自动设置时间
        assert ctx.created_at is not None
        assert ctx.updated_at is not None
        assert ctx.created_at >= now
        assert ctx.updated_at >= now


class TestSemanticMatchDrawer:
    """SemanticMatchDrawer 向量语义匹配取水器测试"""
    
    def test_import_semantic_drawer(self):
        """测试导入 SemanticMatchDrawer"""
        from neurova.context_pool import SemanticMatchDrawer
        drawer = SemanticMatchDrawer(max_tokens=16000)
        assert drawer.max_tokens == 16000
    
    def test_draw_with_need(self):
        """测试按需取水"""
        from neurova.context_pool import SemanticMatchDrawer
        
        drawer = SemanticMatchDrawer(max_tokens=16000)
        
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
            ContextInput(
                source=ContextSource.CONVERSATION,
                content="之前讨论过算法问题",
                priority=60,
                tags=["对话", "算法"]
            ),
        ]
        
        # 按需取水
        result = drawer.draw(drops, need="编程 代码")
        
        # 应该返回列表
        assert isinstance(result, list)
        assert len(result) > 0
    
    def test_draw_without_need(self):
        """测试无需求时取水（返回综合得分最高的）"""
        from neurova.context_pool import SemanticMatchDrawer
        
        drawer = SemanticMatchDrawer(max_tokens=16000)
        
        drops = [
            ContextInput(
                source=ContextSource.MEMORY,
                content="记忆内容",
                priority=80
            ),
            ContextInput(
                source=ContextSource.USER_INPUT,
                content="用户输入",
                priority=100
            ),
        ]
        
        result = drawer.draw(drops, need=None)
        
        assert isinstance(result, list)
        assert len(result) > 0
    
    def test_draw_respects_token_budget(self):
        """测试取水遵守 Token 预算"""
        from neurova.context_pool import SemanticMatchDrawer
        
        drawer = SemanticMatchDrawer(max_tokens=100)
        
        # 创建大量内容
        drops = [
            ContextInput(
                source=ContextSource.MEMORY,
                content="很长的内容" * 100,
                priority=80
            ),
            ContextInput(
                source=ContextSource.USER_INPUT,
                content="短内容",
                priority=100
            ),
        ]
        
        result = drawer.draw(drops, need=None)
        
        # 总 token 数应该在预算内
        total_tokens = sum(ctx.tokens for ctx in result)
        assert total_tokens <= 100


class TestDriftSafeDeduplicator:
    """DriftSafeDeduplicator 防漂移去重器测试"""
    
    def test_import_deduplicator(self):
        """测试导入 DriftSafeDeduplicator"""
        from neurova.context_pool import DriftSafeDeduplicator
        dedup = DriftSafeDeduplicator()
        assert dedup is not None
    
    def test_exact_dedup(self):
        """测试精确去重（相同内容）"""
        from neurova.context_pool import DriftSafeDeduplicator
        
        dedup = DriftSafeDeduplicator()
        
        drops = [
            ContextInput(source=ContextSource.MEMORY, content="相同内容", priority=80),
            ContextInput(source=ContextSource.MEMORY, content="相同内容", priority=70),
            ContextInput(source=ContextSource.MEMORY, content="不同内容", priority=60),
        ]
        
        result = dedup.dedup(drops)
        
        # 应该去除一个重复的
        assert len(result) == 2
    
    def test_dedup_preserves_high_priority(self):
        """测试去重保留高优先级"""
        from neurova.context_pool import DriftSafeDeduplicator
        
        dedup = DriftSafeDeduplicator()
        
        drops = [
            ContextInput(source=ContextSource.MEMORY, content="相同内容", priority=60),
            ContextInput(source=ContextSource.MEMORY, content="相同内容", priority=90),
        ]
        
        result = dedup.dedup(drops)
        
        # 应该保留高优先级的
        assert len(result) == 1
        assert result[0].priority == 90


class TestContextPoolIntegration:
    """ContextPool 集成测试 - 验证新功能与现有功能兼容"""
    
    def test_pool_with_tags(self):
        """测试 ContextPool 支持带标签的上下文"""
        pool = ContextPool(user_id="test_user", agent_id="test_agent")
        
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="记忆内容",
            priority=80,
            tags=["记忆", "重要"]
        ))
        
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        assert contexts[0].tags == ["记忆", "重要"]
    
    def test_pool_backward_compatible(self):
        """测试向后兼容（不带标签也能工作）"""
        pool = ContextPool(user_id="test_user", agent_id="test_agent")
        
        pool.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="用户输入",
            priority=50
        ))
        
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        assert contexts[0].tags == []
