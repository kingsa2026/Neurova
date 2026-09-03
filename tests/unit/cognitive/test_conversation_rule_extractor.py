"""
对话规则提取器测试

TDD: 先写测试，再实现
"""

import pytest
import asyncio
from unittest.mock import Mock, MagicMock, AsyncMock
from neurova.cognitive_layers.memory_layer.conversation_rule_extractor import (
    ConversationRuleExtractor,
    ExtractedRule,
)


class TestExtractedRule:
    """ExtractedRule 数据类测试"""
    
    def test_init(self):
        """测试初始化"""
        rule = ExtractedRule(
            source_entity="数据库",
            target_entity="API",
            relation_type="causal",
            confidence=0.8,
            evidence_text="数据库故障导致API异常",
            source_conversation_id="conv_001",
        )
        assert rule.source_entity == "数据库"
        assert rule.target_entity == "API"
        assert rule.relation_type == "causal"
        assert rule.confidence == 0.8
    
    def test_to_dict(self):
        """测试转换为字典"""
        rule = ExtractedRule(
            source_entity="数据库",
            target_entity="API",
            relation_type="causal",
            confidence=0.8,
            evidence_text="数据库故障导致API异常",
            source_conversation_id="conv_001",
        )
        d = rule.to_dict()
        assert "source_entity" in d
        assert "target_entity" in d
        assert "relation_type" in d
        assert "confidence" in d


class TestConversationRuleExtractor:
    """ConversationRuleExtractor 测试"""
    
    def test_init(self):
        """测试初始化"""
        mock_llm = Mock()
        mock_graph = Mock()
        extractor = ConversationRuleExtractor(mock_llm, mock_graph)
        assert extractor.llm_client is mock_llm
        assert extractor.graph is mock_graph
    
    def test_init_with_default_threshold(self):
        """测试默认置信度阈值"""
        extractor = ConversationRuleExtractor(Mock(), Mock())
        assert extractor.confidence_threshold == 0.6
    
    def test_parse_json_response(self):
        """测试解析JSON响应"""
        extractor = ConversationRuleExtractor(Mock(), Mock())
        
        response = '''
        {
            "rules": [
                {
                    "source": "数据库",
                    "target": "API",
                    "relation": "causal",
                    "confidence": 0.8,
                    "evidence": "数据库故障导致API异常"
                },
                {
                    "source": "测试",
                    "target": "部署",
                    "relation": "prerequisite",
                    "confidence": 0.9,
                    "evidence": "测试通过后才能部署"
                }
            ]
        }
        '''
        
        rules = extractor._parse_json_response(response)
        assert len(rules) == 2
        assert rules[0].source_entity == "数据库"
        assert rules[0].relation_type == "causal"
        assert rules[1].source_entity == "测试"
        assert rules[1].relation_type == "prerequisite"
    
    def test_parse_json_response_invalid(self):
        """测试解析无效JSON"""
        extractor = ConversationRuleExtractor(Mock(), Mock())
        
        response = "invalid json"
        rules = extractor._parse_json_response(response)
        assert len(rules) == 0
    
    def test_confidence_filtering(self):
        """测试置信度过滤"""
        extractor = ConversationRuleExtractor(Mock(), Mock())
        extractor.confidence_threshold = 0.7
        
        rules = [
            ExtractedRule("A", "B", "causal", 0.9, "evidence1", "conv1"),
            ExtractedRule("C", "D", "causal", 0.5, "evidence2", "conv2"),
            ExtractedRule("E", "F", "causal", 0.8, "evidence3", "conv3"),
        ]
        
        filtered = [r for r in rules if r.confidence >= extractor.confidence_threshold]
        assert len(filtered) == 2
        assert filtered[0].confidence == 0.9
        assert filtered[1].confidence == 0.8
    
    def test_inject_to_graph(self):
        """测试注入图谱"""
        mock_graph = Mock()
        extractor = ConversationRuleExtractor(Mock(), mock_graph)
        
        rule = ExtractedRule(
            source_entity="数据库",
            target_entity="API",
            relation_type="causal",
            confidence=0.8,
            evidence_text="数据库故障导致API异常",
            source_conversation_id="conv_001",
        )
        
        extractor._inject_to_graph(rule)
        
        # 验证图谱方法被调用
        assert mock_graph.add_entity.call_count == 2
        assert mock_graph.add_dependency.call_count == 1


class TestConversationRuleExtractorAsync:
    """ConversationRuleExtractor 异步测试"""
    
    def test_extract_rules(self):
        """测试从对话提取规则"""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value='''
        {
            "rules": [
                {
                    "source": "数据库",
                    "target": "API",
                    "relation": "causal",
                    "confidence": 0.8,
                    "evidence": "数据库故障导致API异常"
                }
            ]
        }
        ''')
        
        mock_graph = Mock()
        extractor = ConversationRuleExtractor(mock_llm, mock_graph)
        
        rules = asyncio.run(extractor.extract("数据库挂了", "API返回500错误"))
        
        assert len(rules) == 1
        assert rules[0].source_entity == "数据库"
        assert rules[0].relation_type == "causal"
        
        # 验证LLM被调用
        mock_llm.generate.assert_called_once()
        
        # 验证图谱被更新
        assert mock_graph.add_entity.call_count == 2
        assert mock_graph.add_dependency.call_count == 1
    
    def test_extract_rules_filters_low_confidence(self):
        """测试低置信度过滤"""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value='''
        {
            "rules": [
                {
                    "source": "A",
                    "target": "B",
                    "relation": "causal",
                    "confidence": 0.9,
                    "evidence": "high confidence"
                },
                {
                    "source": "C",
                    "target": "D",
                    "relation": "causal",
                    "confidence": 0.3,
                    "evidence": "low confidence"
                }
            ]
        }
        ''')
        
        mock_graph = Mock()
        extractor = ConversationRuleExtractor(mock_llm, mock_graph)
        
        rules = asyncio.run(extractor.extract("test input", "test reply"))
        
        # 只有高置信度的规则被保留
        assert len(rules) == 1
        assert rules[0].confidence == 0.9
