"""
统一推理引擎测试

TDD: 先写测试，再实现
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock
from neurova.cognitive_layers.memory_layer.unified_reasoning_engine import (
    UnifiedReasoningEngine,
    ReasoningResult,
)


class TestReasoningResult:
    """ReasoningResult 数据类测试"""
    
    def test_init(self):
        """测试初始化"""
        result = ReasoningResult(
            causal_chains=["DB故障→API异常"],
            tool_recommendations=["db_check", "log_analyzer"],
            risk_warnings=["cache_clear有30%失败率"],
            confidence=0.8,
            evidence=["用户说数据库挂了"],
        )
        assert len(result.causal_chains) == 1
        assert len(result.tool_recommendations) == 2
        assert result.confidence == 0.8
    
    def test_to_dict(self):
        """测试转换为字典"""
        result = ReasoningResult(
            causal_chains=[],
            tool_recommendations=[],
            risk_warnings=[],
            confidence=0.0,
            evidence=[],
        )
        d = result.to_dict()
        assert "causal_chains" in d
        assert "tool_recommendations" in d


class TestUnifiedReasoningEngine:
    """UnifiedReasoningEngine 测试"""
    
    def test_init(self):
        """测试初始化"""
        mock_cascade = Mock()
        mock_experience = Mock()
        mock_pattern = Mock()
        
        engine = UnifiedReasoningEngine(
            cascade_engine=mock_cascade,
            experience_kb=mock_experience,
            pattern_miner=mock_pattern,
        )
        
        assert engine.cascade_engine is mock_cascade
        assert engine.experience_kb is mock_experience
        assert engine.pattern_miner is mock_pattern
    
    def test_reason_basic(self):
        """测试基本推理"""
        mock_cascade = Mock()
        mock_cascade.forward_cascade = Mock(return_value=Mock(
            total_affected=2,
            effects=[Mock(entity_id="e1"), Mock(entity_id="e2")],
            confidence=0.8,
        ))
        
        mock_experience = Mock()
        mock_experience.find_similar = Mock(return_value=[
            {"tool": "db_check", "success_rate": 0.9}
        ])
        
        mock_pattern = Mock()
        mock_pattern.recommend = Mock(return_value=["db_check", "log_analyzer"])
        
        engine = UnifiedReasoningEngine(
            cascade_engine=mock_cascade,
            experience_kb=mock_experience,
            pattern_miner=mock_pattern,
        )
        
        result = engine.reason("数据库挂了", {})
        
        assert isinstance(result, ReasoningResult)
        assert len(result.causal_chains) > 0
        assert len(result.tool_recommendations) > 0
    
    def test_reason_with_no_components(self):
        """测试无组件时的推理"""
        engine = UnifiedReasoningEngine(
            cascade_engine=None,
            experience_kb=None,
            pattern_miner=None,
        )
        
        result = engine.reason("test query", {})
        
        assert isinstance(result, ReasoningResult)
        assert result.confidence == 0.0
    
    def test_fuse_results(self):
        """测试结果融合"""
        engine = UnifiedReasoningEngine(
            cascade_engine=Mock(),
            experience_kb=Mock(),
            pattern_miner=Mock(),
        )
        
        # 模拟各组件的结果
        causal_chains = ["DB故障→API异常", "测试→部署"]
        experiences = [{"tool": "db_check", "success_rate": 0.9}]
        patterns = ["db_check", "log_analyzer"]
        
        result = engine._fuse_results(causal_chains, experiences, patterns, cascade_confidence=0.8)
        
        assert isinstance(result, ReasoningResult)
        assert result.confidence > 0
        assert len(result.tool_recommendations) > 0
