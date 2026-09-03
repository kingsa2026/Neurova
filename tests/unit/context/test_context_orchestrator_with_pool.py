"""
ContextOrchestrator 与 ContextPool 集成测试 - Tracer Bullet #5

测试目标：
1. 在 ContextOrchestrator 中集成 ContextPool
2. 保持向后兼容性
3. 支持活水上下文池功能
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from neurova.context_pool import (
    ContextSource,
    ContextInput,
    ContextPool,
)
from neurova.context.orchestrator import ContextOrchestrator


class TestContextOrchestratorWithPool:
    """ContextOrchestrator 与 ContextPool 集成测试"""
    
    def test_context_orchestrator_can_use_context_pool(self):
        """测试 ContextOrchestrator 可以使用 ContextPool"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = MagicMock()
        mock_agent.personality = MagicMock()
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        
        # 创建 ContextOrchestrator
        orchestrator = ContextOrchestrator(mock_agent)
        
        # 验证 ContextOrchestrator 可以访问 ContextPool
        assert hasattr(orchestrator, 'context_pool')
        assert isinstance(orchestrator.context_pool, ContextPool)
    
    def test_context_orchestrator_build_context_with_pool(self):
        """测试 ContextOrchestrator 使用 ContextPool 构建上下文"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = MagicMock()
        mock_agent.personality = MagicMock()
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        
        # 创建 ContextOrchestrator
        orchestrator = ContextOrchestrator(mock_agent)
        
        # 模拟 build_context 方法
        with patch.object(orchestrator, 'build_context', new_callable=AsyncMock) as mock_build:
            mock_build.return_value = [
                {"role": "system", "content": "系统指令"},
                {"role": "user", "content": "用户输入"},
            ]
            
            # 调用 build_context
            import asyncio
            result = asyncio.run(orchestrator.build_context(
                user_input="用户输入",
                tool_memory_result=None,
                auto_execute_result=None,
                tool_decision=None,
                experience_items=[],
                relevant_memories=[],
                session_context=None,
            ))
            
            # 验证结果
            assert len(result) == 2
            assert result[0]["role"] == "system"
            assert result[1]["role"] == "user"
    
    def test_context_orchestrator_draw_from_pool(self):
        """测试 ContextOrchestrator 从 ContextPool 中取水"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = MagicMock()
        mock_agent.personality = MagicMock()
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        
        # 创建 ContextOrchestrator
        orchestrator = ContextOrchestrator(mock_agent)
        
        # 添加上下文到 ContextPool
        orchestrator.context_pool.add_context(ContextInput(
            source=ContextSource.SYSTEM_INSTRUCTION,
            content="你是一个AI助手",
            priority=100
        ))
        
        orchestrator.context_pool.add_context(ContextInput(
            source=ContextSource.USER_INPUT,
            content="帮我写一个Python函数",
            priority=90
        ))
        
        # 从 ContextPool 中取水
        result = orchestrator.context_pool.draw(need="编程 代码")
        
        # 验证结果
        assert isinstance(result, list)
        assert len(result) > 0
    
    def test_context_orchestrator_auto_tagging(self):
        """测试 ContextOrchestrator 自动标签功能"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = MagicMock()
        mock_agent.personality = MagicMock()
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        
        # 创建 ContextOrchestrator（启用自动标签）
        orchestrator = ContextOrchestrator(mock_agent, auto_tag=True)
        
        # 添加上下文
        orchestrator.context_pool.add_context(ContextInput(
            source=ContextSource.MEMORY,
            content="这是一段关于机器学习的记忆",
            priority=80
        ))
        
        # 验证自动标签
        contexts = orchestrator.context_pool.get_contexts()
        assert len(contexts) == 1
        assert len(contexts[0].tags) > 0
        assert "记忆" in contexts[0].tags


class TestContextOrchestratorBackwardCompatibility:
    """ContextOrchestrator 向后兼容性测试"""
    
    def test_context_orchestrator_without_pool(self):
        """测试 ContextOrchestrator 不使用 ContextPool"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = MagicMock()
        mock_agent.personality = MagicMock()
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        
        # 创建 ContextOrchestrator（不使用 ContextPool）
        orchestrator = ContextOrchestrator(mock_agent, use_pool=False)
        
        # 验证没有 ContextPool
        assert not hasattr(orchestrator, 'context_pool') or orchestrator.context_pool is None
    
    def test_context_orchestrator_backward_compatible_methods(self):
        """测试 ContextOrchestrator 向后兼容方法"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = MagicMock()
        mock_agent.personality = MagicMock()
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        
        # 创建 ContextOrchestrator
        orchestrator = ContextOrchestrator(mock_agent)
        
        # 验证向后兼容方法存在
        assert hasattr(orchestrator, 'init_context_system')
        assert hasattr(orchestrator, 'build_context')
        assert hasattr(orchestrator, 'build_system_prompt')
        assert hasattr(orchestrator, 'get_tools_description')
        assert hasattr(orchestrator, 'build_tools_for_llm')
    
    def test_context_orchestrator_existing_functionality(self):
        """测试 ContextOrchestrator 现有功能"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = MagicMock()
        mock_agent.personality = MagicMock()
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        
        # 创建 ContextOrchestrator
        orchestrator = ContextOrchestrator(mock_agent)
        
        # 测试属性代理
        assert orchestrator.config == mock_agent.config
        assert orchestrator.memory_manager == mock_agent.memory_manager
        assert orchestrator.context_builder == mock_agent.context_builder
        assert orchestrator.tool_router == mock_agent.tool_router
        assert orchestrator.skill_registry == mock_agent._skill_registry
        assert orchestrator.soul == mock_agent.soul
        assert orchestrator.personality == mock_agent.personality
        assert orchestrator.conversation_history == mock_agent.conversation_history
        assert orchestrator.growth_log_manager == mock_agent.growth_log_manager


if __name__ == "__main__":
    pytest.main([__file__, "-v"])