"""
上下文门面单元测试

测试ContextFacade的基本功能
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from neurova.context.context_facade import (
    ContextFacade,
    ContextResult,
    get_context_facade,
    reset_context_facade,
)


class TestContextResult:
    """ContextResult测试"""
    
    def test_init(self):
        """测试初始化"""
        result = ContextResult(
            messages=[{"role": "user", "content": "test"}],
            system_prompt="You are a helpful assistant",
            tools=[],
            token_budget={"max_tokens": 4000},
            metadata={"test": True},
        )
        assert len(result.messages) == 1
        assert result.system_prompt == "You are a helpful assistant"
    
    def test_to_dict(self):
        """测试转换为字典"""
        result = ContextResult(
            messages=[],
            system_prompt="",
            tools=[],
            token_budget={},
            metadata={},
        )
        d = result.to_dict()
        assert "messages" in d
        assert "system_prompt" in d


class TestContextFacade:
    """ContextFacade测试"""
    
    def test_init(self):
        """测试初始化"""
        agent_ref = Mock()
        facade = ContextFacade(agent_ref)
        assert facade is not None
    
    def test_build_context_with_no_orchestrator(self):
        """测试无orchestrator时的上下文构建"""
        agent_ref = Mock(spec=[])  # 没有context_orchestrator属性
        facade = ContextFacade(agent_ref)
        
        import asyncio
        result = asyncio.run(facade.build_context("test input"))
        
        assert isinstance(result, ContextResult)
        assert result.messages == []
    
    def test_build_system_prompt_with_no_orchestrator(self):
        """测试无orchestrator时的系统提示构建"""
        agent_ref = Mock(spec=[])
        facade = ContextFacade(agent_ref)
        
        import asyncio
        result = asyncio.run(facade.build_system_prompt())
        
        assert result == ""
    
    def test_build_tools_with_no_orchestrator(self):
        """测试无orchestrator时的工具构建"""
        agent_ref = Mock(spec=[])
        facade = ContextFacade(agent_ref)
        
        import asyncio
        result = asyncio.run(facade.build_tools_for_llm())
        
        assert result == []
    
    def test_get_token_budget(self):
        """测试获取Token预算"""
        agent_ref = Mock(spec=[])
        facade = ContextFacade(agent_ref)
        
        result = facade.get_token_budget()
        assert result == {}
    
    def test_compress_context(self):
        """测试上下文压缩"""
        agent_ref = Mock(spec=[])
        facade = ContextFacade(agent_ref)
        
        context = [
            {"role": "user", "content": "test message 1"},
            {"role": "assistant", "content": "test message 2"},
        ]
        
        result = facade.compress_context(context, target_tokens=100)
        assert len(result) == 2
    
    def test_convert_format_openai(self):
        """测试OpenAI格式转换"""
        agent_ref = Mock(spec=[])
        facade = ContextFacade(agent_ref)
        
        context = [{"role": "user", "content": "test"}]
        result = facade.convert_format(context, "openai")
        assert result == context
    
    def test_convert_format_unsupported(self):
        """测试不支持的格式转换"""
        agent_ref = Mock(spec=[])
        facade = ContextFacade(agent_ref)
        
        context = [{"role": "user", "content": "test"}]
        result = facade.convert_format(context, "unsupported")
        assert result == context


class TestContextFacadeSingleton:
    """ContextFacade单例测试"""
    
    def test_singleton(self):
        """测试单例模式"""
        reset_context_facade()
        
        agent_ref = Mock()
        facade1 = get_context_facade(agent_ref)
        facade2 = get_context_facade()
        
        assert facade1 is facade2
        
        reset_context_facade()
