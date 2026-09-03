"""
ContextOrchestrator 结晶经验注入测试 — D9 Tracer Bullet

测试目标：
1. build_context() 接受 crystallized_patterns 参数
2. 结晶经验被正确注入到上下文中
3. 结晶经验以 [结晶经验] 前缀标记
4. 空结晶经验不影响原有行为
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio


# ── Tracer Bullet 1: build_context 接受 crystallized_patterns 参数 ──

class TestBuildContextAcceptsCrystallizedPatterns:
    """build_context() 可以接受 crystallized_patterns 参数而不报错"""

    def test_build_context_signature_includes_crystallized_patterns(self):
        """验证 build_context 方法签名包含 crystallized_patterns 参数"""
        import inspect
        from neurova.context.orchestrator import ContextOrchestrator
        
        sig = inspect.signature(ContextOrchestrator.build_context)
        assert 'crystallized_patterns' in sig.parameters, \
            f"build_context 缺少 crystallized_patterns 参数，当前参数: {list(sig.parameters.keys())}"

    def test_build_context_with_empty_crystallized_patterns(self):
        """传递空列表不会报错"""
        from neurova.context.orchestrator import ContextOrchestrator
        
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test"
        mock_agent.config.constitution = None
        mock_agent.config.behavior_rules = []
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.config.enable_context_pool = False
        mock_agent.config.enable_auto_tagging = False
        mock_agent.soul = "test soul"
        mock_agent.personality = None
        mock_agent.conversation_history = []
        mock_agent.memory_manager = None
        mock_agent.growth_log_manager = None
        mock_agent.tool_router = None
        mock_agent._skill_registry = None
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        mock_agent.context_builder = MagicMock()
        mock_agent.context_builder.build_from_pool = MagicMock(return_value=[])
        mock_agent.context_builder.compress_if_needed = MagicMock(return_value=[])
        
        orchestrator = ContextOrchestrator(mock_agent, use_pool=False)
        
        # 应该不报错
        result = asyncio.run(orchestrator.build_context(
            user_input="test",
            crystallized_patterns=[],
        ))
        assert isinstance(result, list)


# ── Tracer Bullet 2: 结晶经验注入到上下文 ──

class TestCrystallizedPatternsInjected:
    """结晶经验被正确注入到上下文中"""

    def test_crystallized_patterns_added_to_candidate_pool(self):
        """结晶经验被添加到候选池中"""
        from neurova.context.orchestrator import ContextOrchestrator
        from neurova.context_pool import ContextSource
        
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test"
        mock_agent.config.constitution = None
        mock_agent.config.behavior_rules = []
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.config.enable_context_pool = False
        mock_agent.config.enable_auto_tagging = False
        mock_agent.soul = "test soul"
        mock_agent.personality = None
        mock_agent.conversation_history = []
        mock_agent.memory_manager = None
        mock_agent.growth_log_manager = None
        mock_agent.tool_router = None
        mock_agent._skill_registry = None
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        mock_agent.context_builder = MagicMock()
        mock_agent.context_builder.build_from_pool = MagicMock(return_value=[])
        mock_agent.context_builder.compress_if_needed = MagicMock(return_value=[])
        
        orchestrator = ContextOrchestrator(mock_agent, use_pool=False)
        
        crystallized = [
            {"content": "使用 Python 处理文件时，先检查文件是否存在", "score": 0.9},
            {"content": "调用 API 时添加重试机制", "score": 0.8},
        ]
        
        result = asyncio.run(orchestrator.build_context(
            user_input="帮我读取文件",
            crystallized_patterns=crystallized,
        ))
        
        # 验证 build_from_pool 被调用时的候选池包含结晶经验
        call_args = mock_agent.context_builder.build_from_pool.call_args
        candidate_pool = call_args[0][0]
        
        # 查找结晶经验类型的候选项
        pattern_items = [
            item for item in candidate_pool
            if item.source == ContextSource.EXPERIENCE and "[结晶经验]" in item.content
        ]
        assert len(pattern_items) == 2, f"期望 2 条结晶经验，实际 {len(pattern_items)}"

    def test_crystallized_patterns_priority_higher_than_experience(self):
        """结晶经验的优先级高于普通经验"""
        from neurova.context.orchestrator import ContextOrchestrator
        from neurova.context_pool import ContextSource
        
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test"
        mock_agent.config.constitution = None
        mock_agent.config.behavior_rules = []
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.config.enable_context_pool = False
        mock_agent.config.enable_auto_tagging = False
        mock_agent.soul = "test soul"
        mock_agent.personality = None
        mock_agent.conversation_history = []
        mock_agent.memory_manager = None
        mock_agent.growth_log_manager = None
        mock_agent.tool_router = None
        mock_agent._skill_registry = None
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        mock_agent.context_builder = MagicMock()
        mock_agent.context_builder.build_from_pool = MagicMock(return_value=[])
        mock_agent.context_builder.compress_if_needed = MagicMock(return_value=[])
        
        orchestrator = ContextOrchestrator(mock_agent, use_pool=False)
        
        crystallized = [{"content": "结晶经验内容", "score": 0.9}]
        experience = [{"content": "普通经验内容"}]
        
        result = asyncio.run(orchestrator.build_context(
            user_input="test",
            crystallized_patterns=crystallized,
            experience_items=experience,
        ))
        
        call_args = mock_agent.context_builder.build_from_pool.call_args
        candidate_pool = call_args[0][0]
        
        # 结晶经验优先级应为 80
        pattern_items = [
            item for item in candidate_pool
            if "[结晶经验]" in item.content
        ]
        assert len(pattern_items) == 1
        assert pattern_items[0].priority == 80
        
        # 普通经验优先级应为 70
        exp_items = [
            item for item in candidate_pool
            if item.source == ContextSource.EXPERIENCE and "[结晶经验]" not in item.content
        ]
        assert len(exp_items) == 1
        assert exp_items[0].priority == 70


# ── Tracer Bullet 3: ContextPool 模式也支持结晶经验 ──

class TestCrystallizedPatternsInPoolMode:
    """ContextPool 模式下也支持结晶经验注入"""

    def test_crystallized_patterns_added_to_pool(self):
        """结晶经验被添加到 ContextPool 中"""
        from neurova.context.orchestrator import ContextOrchestrator
        from neurova.context_pool import ContextSource
        
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test"
        mock_agent.config.constitution = None
        mock_agent.config.behavior_rules = []
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.config.enable_context_pool = True
        mock_agent.config.enable_auto_tagging = False
        mock_agent.soul = "test soul"
        mock_agent.personality = None
        mock_agent.conversation_history = []
        mock_agent.memory_manager = None
        mock_agent.growth_log_manager = None
        mock_agent.tool_router = None
        mock_agent._skill_registry = None
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        mock_agent.context_builder = MagicMock()
        
        orchestrator = ContextOrchestrator(mock_agent, use_pool=True)
        # 模拟 ContextPool
        orchestrator.context_pool = MagicMock()
        orchestrator.context_pool.draw = MagicMock(return_value=[])
        
        crystallized = [
            {"content": "结晶经验内容", "score": 0.9},
        ]
        
        result = asyncio.run(orchestrator.build_context(
            user_input="test",
            crystallized_patterns=crystallized,
        ))
        
        # 验证 add_context 被调用（包含结晶经验）
        add_calls = orchestrator.context_pool.add_context.call_args_list
        pattern_calls = [
            call for call in add_calls
            if "[结晶经验]" in call[0][0].content
        ]
        assert len(pattern_calls) == 1, f"期望 1 次结晶经验添加，实际 {len(pattern_calls)}"


# ── Tracer Bullet 4: 完整流程 ──

class TestCrystallizedPatternsFullFlow:
    """完整流程：结晶经验被正确注入到最终上下文中"""

    def test_full_flow_with_crystallized_patterns(self):
        """完整流程：结晶经验出现在最终上下文中"""
        from neurova.context.orchestrator import ContextOrchestrator
        
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test"
        mock_agent.config.constitution = None
        mock_agent.config.behavior_rules = []
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.config.enable_context_pool = False
        mock_agent.config.enable_auto_tagging = False
        mock_agent.soul = "你是一个 AI 助手"
        mock_agent.personality = None
        mock_agent.conversation_history = []
        mock_agent.memory_manager = None
        mock_agent.growth_log_manager = None
        mock_agent.tool_router = None
        mock_agent._skill_registry = None
        mock_agent.user_id = "test_user"
        mock_agent.agent_id = "test_agent"
        
        # 模拟 context_builder 返回包含结晶经验的上下文
        def fake_build_from_pool(pool, **kwargs):
            result = []
            for item in pool:
                if "[结晶经验]" in item.content:
                    result.append({"role": "system", "content": item.content})
                elif item.source.value == "system_instruction":
                    result.append({"role": "system", "content": item.content})
                elif item.source.value == "user_input":
                    result.append({"role": "user", "content": item.content})
            return result
        
        mock_agent.context_builder = MagicMock()
        mock_agent.context_builder.build_from_pool = MagicMock(side_effect=fake_build_from_pool)
        mock_agent.context_builder.compress_if_needed = MagicMock(side_effect=lambda x: x)
        
        orchestrator = ContextOrchestrator(mock_agent, use_pool=False)
        
        crystallized = [
            {"content": "处理文件时先检查是否存在", "score": 0.9},
        ]
        
        result = asyncio.run(orchestrator.build_context(
            user_input="帮我读取文件",
            crystallized_patterns=crystallized,
        ))
        
        # 验证结晶经验出现在最终上下文中
        pattern_messages = [
            msg for msg in result
            if "[结晶经验]" in msg.get("content", "")
        ]
        assert len(pattern_messages) == 1, f"期望 1 条结晶经验消息，实际 {len(pattern_messages)}"
        assert "处理文件时先检查是否存在" in pattern_messages[0]["content"]
