"""
CrystallizedExperienceManager 集成测试

测试 CrystallizedExperienceManager 集成到 ChatPipeline 的功能。
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from typing import List, Dict, Any

from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
from neurova.agent.crystallized_experience_manager import CrystallizedExperienceManager


class MockAgent:
    """模拟 Agent 类"""
    
    def __init__(self):
        self.config = Mock()
        self.memory_agent = Mock()
        self.context_orchestrator = Mock()
        self.tool_memory = Mock()
        self.skill_manager = Mock()
        self.tool_synthesizer = Mock()
        self.unified_retriever = Mock()
        self.crystallizer = Mock()
        self.trace_manager = Mock()
        self.neuHebb_manager = Mock()
        self.loop = Mock()
        self.llm_client = Mock()
        self.tool_executor = Mock()
        
        # 设置结晶器模拟
        self.crystallizer.retrieve.return_value = [
            {
                "id": "1",
                "content": "测试结晶经验",
                "method": "tool_a",
                "confidence": 0.9,
                "score": 80.0,
            }
        ]


class MockCrystallizedExperienceManager:
    """模拟 CrystallizedExperienceManager"""
    
    def __init__(self):
        self.retrieve_count = 0
        self.retrieve_results = []
    
    async def retrieve(self, query: str, limit: int = 5, **kwargs):
        """模拟检索"""
        self.retrieve_count += 1
        from neurova.agent.crystallized_experience_manager import RetrievalResult, RetrievalStatus, CrystallizedExperience
        
        if self.retrieve_results:
            return self.retrieve_results[-1]
        
        return RetrievalResult(
            status=RetrievalStatus.SUCCESS,
            experiences=[
                CrystallizedExperience(
                    id="1",
                    content="集成测试结晶经验",
                    method="tool_a",
                    confidence=0.9,
                    score=80.0,
                    source="crystallized",
                )
            ],
            source="pattern_crystallizer",
            latency_ms=10.0,
        )


class TestCrystallizedExperienceIntegration:
    """CrystallizedExperienceManager 集成测试类"""
    
    def setup_method(self):
        """测试前准备"""
        self.agent = MockAgent()
        self.pipeline = ChatPipeline(self.agent)
        self.mock_manager = MockCrystallizedExperienceManager()
        
        # 替换真实的管理器
        self.pipeline._crystallized_experience_manager = self.mock_manager
    
    def test_initialization(self):
        """测试初始化"""
        assert hasattr(self.pipeline, '_crystallized_experience_manager')
        assert self.pipeline._crystallized_experience_manager is self.mock_manager
    
    def test_property_access(self):
        """测试属性访问"""
        assert self.pipeline.crystallized_experience_manager is self.mock_manager
    
    def test_retrieve_crystallized_patterns(self):
        """测试结晶经验检索"""
        ctx = ChatContext(user_input="测试查询")
        
        # 执行检索
        asyncio.run(self.pipeline._retrieve_crystallized_patterns(ctx))
        
        # 验证结果
        assert len(ctx.crystallized_patterns) == 1
        assert ctx.crystallized_patterns[0]['content'] == "集成测试结晶经验"
        assert ctx.crystallized_patterns[0]['method'] == "tool_a"
        assert self.mock_manager.retrieve_count == 1
    
    def test_retrieve_with_empty_input(self):
        """测试空输入"""
        ctx = ChatContext(user_input="")
        
        asyncio.run(self.pipeline._retrieve_crystallized_patterns(ctx))
        
        # 应该正常执行
        assert self.mock_manager.retrieve_count == 1
    
    def test_retrieve_with_trace(self):
        """测试带追踪的检索"""
        ctx = ChatContext(user_input="追踪查询", trace_id="trace_123")
        
        asyncio.run(self.pipeline._retrieve_crystallized_patterns(ctx))
        
        # 验证追踪记录
        self.agent.trace_manager.add_step.assert_called_once()
        call_args = self.agent.trace_manager.add_step.call_args[0]
        assert call_args[0] == "trace_123"
        assert call_args[1] == "crystallize"
    
    def test_retrieve_without_crystallizer(self):
        """测试无结晶器"""
        self.agent.crystallizer = None
        self.pipeline = ChatPipeline(self.agent)
        self.pipeline._crystallized_experience_manager = self.mock_manager
        
        ctx = ChatContext(user_input="查询")
        asyncio.run(self.pipeline._retrieve_crystallized_patterns(ctx))
        
        # 应该跳过检索
        assert self.mock_manager.retrieve_count == 1  # 管理器仍会被调用
    
    def test_integration_with_memory_retrieval(self):
        """测试与记忆检索的集成"""
        # 验证两个管理器都已初始化
        assert hasattr(self.pipeline, '_memory_retrieval_chain')
        assert hasattr(self.pipeline, '_crystallized_experience_manager')
        
        # 两者应该独立工作
        ctx = ChatContext(user_input="完整查询")
        
        # 结晶经验检索
        asyncio.run(self.pipeline._retrieve_crystallized_patterns(ctx))
        
        # 验证结果
        assert len(ctx.crystallized_patterns) == 1


class TestCrystallizedExperienceIntegrationWithRealManager:
    """使用真实 CrystallizedExperienceManager 的集成测试"""
    
    def setup_method(self):
        """测试前准备"""
        self.agent = MockAgent()
        self.pipeline = ChatPipeline(self.agent)
    
    def test_real_manager_initialization(self):
        """测试真实管理器初始化"""
        assert isinstance(self.pipeline._crystallized_experience_manager, CrystallizedExperienceManager)
        assert self.pipeline._crystallized_experience_manager._crystallizer is self.agent.crystallizer
    
    def test_real_manager_health(self):
        """测试真实管理器健康状态"""
        health = self.pipeline._crystallized_experience_manager.get_health()
        from neurova.agent.crystallized_experience_manager import HealthStatus
        assert health == HealthStatus.HEALTHY
    
    def test_real_manager_statistics(self):
        """测试真实管理器统计"""
        stats = self.pipeline._crystallized_experience_manager.get_statistics()
        assert stats["total_attempts"] == 0
        assert stats["success_rate"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])