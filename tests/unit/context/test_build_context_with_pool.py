"""
build_context 与 ContextPool 集成测试 - Tracer Bullet #6

测试目标：
1. build_context 方法支持 ContextPool
2. 保持向后兼容性
3. 支持活水上下文池功能
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from neurova.context.orchestrator import ContextOrchestrator
from neurova.context_pool import ContextSource


class TestBuildContextWithPool:
    """build_context 与 ContextPool 集成测试"""
    
    @pytest.mark.asyncio
    async def test_build_context_with_pool_enabled(self):
        """测试 build_context 启用 ContextPool"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.config.constitution = ""
        mock_agent.config.behavior_rules = ["规则1", "规则2"]
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = "你是一个AI助手"
        mock_agent.personality = "友好、耐心"
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        
        # 创建 ContextOrchestrator（启用 ContextPool）
        orchestrator = ContextOrchestrator(mock_agent, use_pool=True, auto_tag=True)
        
        # 模拟 get_tools_description
        with patch.object(orchestrator, 'get_tools_description', new_callable=AsyncMock) as mock_tools_desc:
            mock_tools_desc.return_value = "可用工具：file_read, web_search"
            
            # 模拟 context_builder.build_from_pool
            mock_context_builder = MagicMock()
            mock_context_builder.build_from_pool.return_value = [
                {"role": "system", "content": "系统指令"},
                {"role": "user", "content": "用户输入"},
            ]
            orchestrator._agent.context_builder = mock_context_builder
            
            # 调用 build_context
            result = await orchestrator.build_context(
                user_input="帮我写一个Python函数",
                tool_memory_result=None,
                auto_execute_result=None,
                tool_decision="do_not_execute",
                experience_items=[],
                relevant_memories=[],
                session_context=None,
            )
            
            # 验证结果
            assert isinstance(result, list)
            # [FIX] 对话时序修复后：用户输入不再进语义池，而是拼接在上下文末尾，
            # 保证当前输入是 LLM 看到的最后一条 user 消息
            assert len(result) == 7
            assert result[0]["role"] == "system"  # 系统指令
            assert result[-1] == {"role": "user", "content": "帮我写一个Python函数"}
            # 中间为 system 富化内容（个性、规则、工具描述等）
            assert all(m["role"] == "system" for m in result[:-1])

            # 验证 ContextPool 被使用
            assert orchestrator.context_pool is not None

            # 验证系统指令类上下文不再归档（直接组装为固定前缀）；
            # [FIX] 用户输入与对话历史不进池（时序修复的核心保证）；
            # 本用例无对话/记忆，池应保持为空（无损归档只收可复用内容）
            contexts = orchestrator.context_pool.get_contexts()
            assert all(
                c.source
                not in (
                    ContextSource.USER_INPUT,
                    ContextSource.CONVERSATION,
                )
                for c in contexts
            ), "用户输入/对话历史不应进入语义池"
    
    @pytest.mark.asyncio
    async def test_build_context_without_pool(self):
        """测试 build_context 不使用 ContextPool"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.config.constitution = ""
        mock_agent.config.behavior_rules = ["规则1", "规则2"]
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = "你是一个AI助手"
        mock_agent.personality = "友好、耐心"
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        
        # 创建 ContextOrchestrator（不使用 ContextPool）
        orchestrator = ContextOrchestrator(mock_agent, use_pool=False)
        
        # 模拟 get_tools_description
        with patch.object(orchestrator, 'get_tools_description', new_callable=AsyncMock) as mock_tools_desc:
            mock_tools_desc.return_value = "可用工具：file_read, web_search"
            
            # 模拟 context_builder.build_from_pool
            mock_context_builder = MagicMock()
            mock_context_builder.build_from_pool.return_value = [
                {"role": "system", "content": "系统指令"},
                {"role": "user", "content": "用户输入"},
            ]
            mock_context_builder.compress_if_needed.return_value = [
                {"role": "system", "content": "系统指令"},
                {"role": "user", "content": "用户输入"},
            ]
            orchestrator._agent.context_builder = mock_context_builder
            
            # 调用 build_context
            result = await orchestrator.build_context(
                user_input="帮我写一个Python函数",
                tool_memory_result=None,
                auto_execute_result=None,
                tool_decision="do_not_execute",
                experience_items=[],
                relevant_memories=[],
                session_context=None,
            )
            
            # 验证结果
            assert isinstance(result, list)
            assert len(result) == 2
            
            # 验证 ContextPool 未被使用
            assert orchestrator.context_pool is None
    
    @pytest.mark.asyncio
    async def test_build_context_with_pool_draw(self):
        """测试 build_context 使用 ContextPool.draw()"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.config.constitution = ""
        mock_agent.config.behavior_rules = ["规则1", "规则2"]
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = "你是一个AI助手"
        mock_agent.personality = "友好、耐心"
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        
        # 创建 ContextOrchestrator（启用 ContextPool）
        orchestrator = ContextOrchestrator(mock_agent, use_pool=True, auto_tag=True)

        # [FIX] build_context() 开头会 clear() 语义池，预先 add_context 的条目会被
        # 清空；记忆应通过 relevant_memories 参数传入（正式 API）
        pre_memory = "用户之前问过Python问题"

        # 模拟 get_tools_description
        with patch.object(orchestrator, 'get_tools_description', new_callable=AsyncMock) as mock_tools_desc:
            mock_tools_desc.return_value = "可用工具：file_read, web_search"

            # 模拟 context_builder.build_from_pool
            mock_context_builder = MagicMock()
            mock_context_builder.build_from_pool.return_value = [
                {"role": "system", "content": "系统指令"},
                {"role": "user", "content": "用户输入"},
            ]
            orchestrator._agent.context_builder = mock_context_builder

            # 调用 build_context
            result = await orchestrator.build_context(
                user_input="帮我写一个Python函数",
                tool_memory_result=None,
                auto_execute_result=None,
                tool_decision="do_not_execute",
                experience_items=[],
                relevant_memories=[{"content": pre_memory}],
                session_context=None,
            )

            # 验证结果
            assert isinstance(result, list)
            # 记忆经语义池 draw 后以 [记忆] 前缀的 system 消息出现在上下文中
            memory_found = any(pre_memory in ctx.get("content", "") for ctx in result)
            assert memory_found, "记忆上下文应该被包含在结果中"
            # 用户输入仍在末尾
            assert result[-1] == {"role": "user", "content": "帮我写一个Python函数"}

            # 验证 ContextPool.draw() 被调用
            assert orchestrator.context_pool is not None


class TestBuildContextBackwardCompatibility:
    """build_context 向后兼容性测试"""
    
    @pytest.mark.asyncio
    async def test_build_context_backward_compatible(self):
        """测试 build_context 向后兼容"""
        # 创建模拟的 Agent
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.config.constitution = ""
        mock_agent.config.behavior_rules = ["规则1", "规则2"]
        mock_agent.memory_manager = MagicMock()
        mock_agent.context_builder = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.soul = "你是一个AI助手"
        mock_agent.personality = "友好、耐心"
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = MagicMock()
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        
        # 创建 ContextOrchestrator
        orchestrator = ContextOrchestrator(mock_agent)
        
        # 模拟 get_tools_description
        with patch.object(orchestrator, 'get_tools_description', new_callable=AsyncMock) as mock_tools_desc:
            mock_tools_desc.return_value = "可用工具：file_read, web_search"
            
            # 模拟 context_builder.build_from_pool
            mock_context_builder = MagicMock()
            mock_context_builder.build_from_pool.return_value = [
                {"role": "system", "content": "系统指令"},
                {"role": "user", "content": "用户输入"},
            ]
            orchestrator._agent.context_builder = mock_context_builder
            
            # 调用 build_context
            result = await orchestrator.build_context(
                user_input="帮我写一个Python函数",
                tool_memory_result=None,
                auto_execute_result=None,
                tool_decision="do_not_execute",
                experience_items=[],
                relevant_memories=[],
                session_context=None,
            )
            
            # 验证结果
            assert isinstance(result, list)
            # [FIX] 默认启用 ContextPool；用户输入拼接在末尾（时序修复）
            assert len(result) == 7
            assert result[-1] == {"role": "user", "content": "帮我写一个Python函数"}

            # 验证向后兼容性
            assert orchestrator.use_pool is True  # 默认启用
            assert orchestrator.context_pool is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])