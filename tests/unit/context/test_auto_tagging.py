"""
自动标签生成测试 - Tracer Bullet #3

测试目标：
1. 自动标签生成功能
2. 基于内容的标签提取
3. 基于来源的标签添加
4. 标签去重和合并
"""

import pytest
from neurova.context_pool import (
    ContextSource,
    ContextInput,
    ContextPool,
    AutoTagger,
)


class TestAutoTagger:
    """AutoTagger 自动标签生成器测试"""
    
    def test_import_auto_tagger(self):
        """测试导入 AutoTagger"""
        tagger = AutoTagger()
        assert tagger is not None
    
    def test_generate_tags_from_content(self):
        """测试从内容生成标签"""
        tagger = AutoTagger()
        
        # 测试中文内容
        tags = tagger.generate_tags("这是一段关于机器学习的记忆")
        assert isinstance(tags, list)
        assert len(tags) > 0
        assert "机器学习" in tags or "记忆" in tags
        
        # 测试英文内容
        tags = tagger.generate_tags("Python code optimization")
        assert isinstance(tags, list)
        assert len(tags) > 0
        assert "Python" in tags or "code" in tags
    
    def test_generate_tags_from_source(self):
        """测试根据来源生成标签"""
        tagger = AutoTagger()
        
        # 测试不同来源的标签
        tags_memory = tagger.generate_source_tags(ContextSource.MEMORY)
        assert "记忆" in tags_memory
        
        tags_emotion = tagger.generate_source_tags(ContextSource.EMOTION)
        assert "情感" in tags_emotion
        
        tags_user = tagger.generate_source_tags(ContextSource.USER_INPUT)
        assert "用户" in tags_user
    
    def test_merge_tags(self):
        """测试标签合并"""
        tagger = AutoTagger()
        
        # 合并标签
        existing_tags = ["Python", "代码"]
        new_tags = ["优化", "Python", "性能"]
        
        merged = tagger.merge_tags(existing_tags, new_tags)
        
        # 应该去重
        assert len(merged) == 4
        assert "Python" in merged
        assert "代码" in merged
        assert "优化" in merged
        assert "性能" in merged
    
    def test_auto_tag_context_input(self):
        """测试自动为 ContextInput 生成标签"""
        tagger = AutoTagger()
        
        # 创建没有标签的上下文
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="这是一段关于机器学习的记忆",
            priority=80
        )
        
        # 自动生成标签
        tagged_ctx = tagger.auto_tag(ctx)
        
        # 验证标签被添加
        assert len(tagged_ctx.tags) > 0
        assert "记忆" in tagged_ctx.tags  # 来源标签
        assert any("机器学习" in tag for tag in tagged_ctx.tags)  # 内容标签
    
    def test_auto_tag_preserves_existing_tags(self):
        """测试自动标签保留现有标签"""
        tagger = AutoTagger()
        
        # 创建有标签的上下文
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="这是一段关于机器学习的记忆",
            priority=80,
            tags=["重要", "学习"]
        )
        
        # 自动生成标签
        tagged_ctx = tagger.auto_tag(ctx)
        
        # 验证现有标签被保留
        assert "重要" in tagged_ctx.tags
        assert "学习" in tagged_ctx.tags
        
        # 验证新标签被添加
        assert "记忆" in tagged_ctx.tags


class TestContextPoolWithAutoTagging:
    """ContextPool 与自动标签集成测试"""
    
    def test_context_pool_auto_tag_on_add(self):
        """测试 ContextPool 添加上下文时自动标签"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000,
            auto_tag=True  # 启用自动标签
        )
        
        # 添加没有标签的上下文
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="这是一段关于机器学习的记忆",
            priority=80
        ))
        
        # 验证自动标签被添加
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        assert len(contexts[0].tags) > 0
        assert "记忆" in contexts[0].tags
    
    def test_context_pool_without_auto_tag(self):
        """测试 ContextPool 不启用自动标签"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000,
            auto_tag=False  # 不启用自动标签
        )
        
        # 添加没有标签的上下文
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="这是一段关于机器学习的记忆",
            priority=80
        ))
        
        # 验证没有自动标签
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        assert len(contexts[0].tags) == 0
    
    def test_context_pool_auto_tag_with_existing_tags(self):
        """测试 ContextPool 自动标签保留现有标签"""
        # 创建 ContextPool
        pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=16000,
            auto_tag=True  # 启用自动标签
        )
        
        # 添加有标签的上下文
        pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="这是一段关于机器学习的记忆",
            priority=80,
            tags=["重要"]
        ))
        
        # 验证现有标签被保留，新标签被添加
        contexts = pool.get_contexts()
        assert len(contexts) == 1
        assert "重要" in contexts[0].tags
        assert "记忆" in contexts[0].tags


class TestAutoTaggingEdgeCases:
    """自动标签边界情况测试"""
    
    def test_auto_tag_empty_content(self):
        """测试空内容的自动标签"""
        tagger = AutoTagger()
        
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="",
            priority=80
        )
        
        tagged_ctx = tagger.auto_tag(ctx)
        
        # 应该至少有来源标签
        assert "记忆" in tagged_ctx.tags
    
    def test_auto_tag_short_content(self):
        """测试短内容的自动标签"""
        tagger = AutoTagger()
        
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="你好",
            priority=80
        )
        
        tagged_ctx = tagger.auto_tag(ctx)
        
        # 应该至少有来源标签
        assert "记忆" in tagged_ctx.tags
    
    def test_auto_tag_special_characters(self):
        """测试特殊字符内容的自动标签"""
        tagger = AutoTagger()
        
        ctx = ContextInput(
            source=ContextSource.MEMORY,
            content="Python! @#$%^&*() 代码优化",
            priority=80
        )
        
        tagged_ctx = tagger.auto_tag(ctx)
        
        # 应该能提取出有效标签
        assert len(tagged_ctx.tags) > 0
        assert "记忆" in tagged_ctx.tags


if __name__ == "__main__":
    pytest.main([__file__, "-v"])