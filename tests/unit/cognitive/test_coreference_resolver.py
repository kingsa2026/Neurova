"""
指代消解器测试

TDD: 先写测试，再实现
"""

import pytest
from neurova.cognitive_layers.memory_layer.coreference_resolver import CoreferenceResolver


class TestCoreferenceResolver:
    """CoreferenceResolver 测试"""
    
    def test_init(self):
        """测试初始化"""
        resolver = CoreferenceResolver()
        assert resolver is not None
    
    def test_pronoun_patterns(self):
        """测试代词模式"""
        resolver = CoreferenceResolver()
        assert "它" in resolver.PRONOUN_PATTERNS
        assert "这个" in resolver.PRONOUN_PATTERNS
        assert "那个" in resolver.PRONOUN_PATTERNS
    
    def test_resolve_pronoun(self):
        """测试代词替换"""
        resolver = CoreferenceResolver()
        recent_entities = ["数据库", "API", "服务器"]
        
        text = "它挂了"
        resolved = resolver.resolve(text, recent_entities)
        
        # 应该将"它"替换为最近的实体
        assert "数据库" in resolved or "API" in resolved or "服务器" in resolved
    
    def test_resolve_no_pronoun(self):
        """测试无代词时"""
        resolver = CoreferenceResolver()
        recent_entities = ["数据库", "API"]
        
        text = "数据库挂了"
        resolved = resolver.resolve(text, recent_entities)
        
        # 应该保持原文
        assert resolved == text
    
    def test_resolve_multiple_pronouns(self):
        """测试多个代词"""
        resolver = CoreferenceResolver()
        recent_entities = ["数据库", "API", "服务器"]
        
        text = "它挂了，这个也挂了"
        resolved = resolver.resolve(text, recent_entities)
        
        # 应该替换代词
        assert "数据库" in resolved or "API" in resolved or "服务器" in resolved
    
    def test_find_best_match(self):
        """测试最佳匹配"""
        resolver = CoreferenceResolver()
        recent_entities = ["数据库", "API", "服务器"]
        
        # 优先匹配最近的实体
        match = resolver._find_best_match("它", ["数据库", "服务器"], recent_entities)
        # 应该返回最近的匹配实体
        assert match in ["数据库", "服务器"]
    
    def test_find_best_match_no_match(self):
        """测试无匹配"""
        resolver = CoreferenceResolver()
        recent_entities = ["用户", "开发者"]
        
        match = resolver._find_best_match("它", ["数据库", "服务器"], recent_entities)
        # 无匹配时返回第一个候选
        assert match in ["数据库", "服务器"]
    
    def test_resolve_empty_entities(self):
        """测试空实体列表"""
        resolver = CoreferenceResolver()
        resolved = resolver.resolve("它挂了", [])
        # 无实体时可能返回原文或第一个候选
        assert "挂了" in resolved
