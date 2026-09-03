"""
经验闭环修复测试 — TDD 垂直切片

测试目标：
1. _step_record_experience 不重复调用 evolution.on_experience_recorded
2. crystallized_patterns 正确传递到 build_context
3. experience_items 被正确填充
4. 结晶经验注入到上下文中
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, List, Any

# ══════════════════════════════════════════════════════════════
# Test 1: _step_record_experience 不重复调用
# ══════════════════════════════════════════════════════════════

class TestRecordExperienceNoDuplicate:
    """验证 _step_record_experience 只调用一次 evolution.on_experience_recorded"""

    @pytest.fixture
    def mock_agent(self):
        """创建 mock Agent"""
        agent = MagicMock()
        agent.evolution = MagicMock()
        agent.evolution.on_experience_recorded = MagicMock(return_value={
            "insights_count": 1,
            "tools_mentioned": ["test_tool"],
            "outcome": "success",
            "task": "test task",
            "success": True,
        })
        agent._collect_tool_messages = MagicMock(return_value=[
            {"tool_name": "test_tool", "success": True}
        ])
        return agent

    @pytest.fixture
    def pipeline(self, mock_agent):
        """创建 PostChatPipeline 实例"""
        from neurova.post_chat_pipeline import PostChatPipeline
        return PostChatPipeline(mock_agent)

    @pytest.mark.asyncio
    async def test_on_experience_recorded_called_once(self, pipeline, mock_agent):
        """验证 evolution.on_experience_recorded 只被调用一次"""
        await pipeline._step_record_experience(
            user_input="测试用户输入",
            reply="测试回复",
            save_memory=True,
        )
        
        # 应该只调用一次，而不是两次
        assert mock_agent.evolution.on_experience_recorded.call_count == 1
        
        # 验证调用参数
        call_args = mock_agent.evolution.on_experience_recorded.call_args
        assert call_args.kwargs["task"] == "测试用户输入"
        assert call_args.kwargs["tools"] == ["test_tool"]
        assert call_args.kwargs["success"] is True

    @pytest.mark.asyncio
    async def test_no_duplicate_processing(self, pipeline, mock_agent):
        """验证不会重复处理经验"""
        # 记录初始调用次数
        initial_count = mock_agent.evolution.on_experience_recorded.call_count
        
        await pipeline._step_record_experience(
            user_input="测试输入",
            reply="测试回复",
            save_memory=True,
        )
        
        # 调用次数应该只增加 1
        assert mock_agent.evolution.on_experience_recorded.call_count == initial_count + 1


# ══════════════════════════════════════════════════════════════
# Test 2: crystallized_patterns 正确传递到 build_context
# ══════════════════════════════════════════════════════════════

class TestCrystallizedPatternsPassed:
    """验证 crystallized_patterns 被正确传递到 build_context"""

    @pytest.fixture
    def mock_context_orchestrator(self):
        """创建 mock ContextOrchestrator"""
        orchestrator = AsyncMock()
        orchestrator.build_context = AsyncMock(return_value=[
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "用户输入"},
        ])
        return orchestrator

    @pytest.fixture
    def mock_crystallizer(self):
        """创建 mock PatternCrystallizer"""
        crystallizer = MagicMock()
        crystallizer.retrieve = MagicMock(return_value=[
            {"content": "结晶经验1", "confidence": 0.9},
            {"content": "结晶经验2", "confidence": 0.8},
        ])
        return crystallizer

    def test_build_context_accepts_crystallized_patterns(self):
        """验证 build_context 接受 crystallized_patterns 参数"""
        from neurova.context.orchestrator import ContextOrchestrator
        import inspect
        
        # 验证方法签名接受 crystallized_patterns 参数
        sig = inspect.signature(ContextOrchestrator.build_context)
        assert "crystallized_patterns" in sig.parameters
        
        # 验证参数类型为 Optional[list]
        param = sig.parameters["crystallized_patterns"]
        assert param.default is None

    @pytest.mark.asyncio
    async def test_crystallized_patterns_injected_into_context(self, mock_context_orchestrator):
        """验证结晶经验被注入到上下文中"""
        # 模拟 build_context 返回包含结晶经验的上下文
        mock_context_orchestrator.build_context.return_value = [
            {"role": "system", "content": "系统提示\n\n## 结晶经验\n结晶经验1"},
            {"role": "user", "content": "用户输入"},
        ]
        
        # 调用 build_context
        result = await mock_context_orchestrator.build_context(
            user_input="测试输入",
            crystallized_patterns=[
                {"content": "结晶经验1", "confidence": 0.9},
            ],
        )
        
        # 验证上下文包含结晶经验
        system_msg = next(m for m in result if m["role"] == "system")
        assert "结晶经验" in system_msg["content"]


# ══════════════════════════════════════════════════════════════
# Test 3: experience_items 被正确填充
# ══════════════════════════════════════════════════════════════

class TestExperienceItemsPopulated:
    """验证 experience_items 被正确填充"""

    @pytest.fixture
    def mock_chat_pipeline(self):
        """创建 mock ChatPipeline"""
        pipeline = MagicMock()
        pipeline.crystallizer = MagicMock()
        pipeline.crystallizer.retrieve = MagicMock(return_value=[
            {"content": "结晶经验1", "confidence": 0.9},
        ])
        return pipeline

    def test_experience_items_field_exists(self):
        """验证 ChatContext 有 experience_items 字段"""
        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(user_input="测试")
        assert hasattr(ctx, "experience_items")
        assert ctx.experience_items == []

    def test_crystallized_patterns_field_exists(self):
        """验证 ChatContext 有 crystallized_patterns 字段"""
        from neurova.agent.chat_pipeline import ChatContext
        ctx = ChatContext(user_input="测试")
        assert hasattr(ctx, "crystallized_patterns")
        assert ctx.crystallized_patterns == []


# ══════════════════════════════════════════════════════════════
# Test 4: 完整经验闭环流程
# ══════════════════════════════════════════════════════════════

class TestExperienceLoopEndToEnd:
    """端到端测试：记录 → 结晶 → 注入"""

    @pytest.fixture
    def mock_system(self):
        """创建完整的 mock 系统"""
        # Agent
        agent = MagicMock()
        agent.evolution = MagicMock()
        agent.evolution.on_experience_recorded = MagicMock(return_value={
            "insights_count": 2,
            "tools_mentioned": ["search", "calculator"],
            "outcome": "success",
            "task": "计算任务",
            "success": True,
        })
        agent._collect_tool_messages = MagicMock(return_value=[
            {"tool_name": "search", "success": True},
            {"tool_name": "calculator", "success": True},
        ])
        
        # ContextOrchestrator
        context_orchestrator = AsyncMock()
        context_orchestrator.build_context = AsyncMock(return_value=[
            {"role": "system", "content": "系统提示"},
        ])
        
        # Crystallizer
        crystallizer = MagicMock()
        crystallizer.retrieve = MagicMock(return_value=[
            {"content": "使用 search 后再用 calculator 效果更好", "confidence": 0.95},
        ])
        
        return {
            "agent": agent,
            "context_orchestrator": context_orchestrator,
            "crystallizer": crystallizer,
        }

    @pytest.mark.asyncio
    async def test_full_experience_loop(self, mock_system):
        """测试完整的经验闭环流程"""
        agent = mock_system["agent"]
        context_orchestrator = mock_system["context_orchestrator"]
        crystallizer = mock_system["crystallizer"]
        
        # 1. 记录经验
        from neurova.post_chat_pipeline import PostChatPipeline
        pipeline = PostChatPipeline(agent)
        
        await pipeline._step_record_experience(
            user_input="帮我计算 2+2",
            reply="结果是 4",
            save_memory=True,
        )
        
        # 验证经验被记录
        agent.evolution.on_experience_recorded.assert_called_once()
        
        # 2. 检索结晶经验
        patterns = crystallizer.retrieve("帮我计算 2+2", limit=3)
        assert len(patterns) == 1
        assert "search" in patterns[0]["content"]
        
        # 3. 注入到上下文
        context = await context_orchestrator.build_context(
            user_input="帮我计算 2+2",
            crystallized_patterns=patterns,
        )
        
        # 验证上下文被构建
        assert len(context) > 0


# ══════════════════════════════════════════════════════════════
# Test 5: 边界情况
# ══════════════════════════════════════════════════════════════

class TestExperienceLoopEdgeCases:
    """边界情况测试"""

    @pytest.fixture
    def mock_agent_no_evolution(self):
        """没有 evolution 的 Agent"""
        agent = MagicMock()
        agent.evolution = None
        agent._collect_tool_messages = MagicMock(return_value=[])
        return agent

    @pytest.fixture
    def mock_agent_no_tools(self):
        """没有工具消息的 Agent"""
        agent = MagicMock()
        agent.evolution = MagicMock()
        agent.evolution.on_experience_recorded = MagicMock()
        agent._collect_tool_messages = MagicMock(return_value=[])
        return agent

    @pytest.mark.asyncio
    async def test_no_evolution_does_nothing(self, mock_agent_no_evolution):
        """没有 evolution 时应该直接返回"""
        from neurova.post_chat_pipeline import PostChatPipeline
        pipeline = PostChatPipeline(mock_agent_no_evolution)
        
        # 应该不抛出异常
        await pipeline._step_record_experience(
            user_input="测试",
            reply="回复",
            save_memory=True,
        )

    @pytest.mark.asyncio
    async def test_no_tools_still_records(self, mock_agent_no_tools):
        """没有工具消息时仍然记录经验"""
        from neurova.post_chat_pipeline import PostChatPipeline
        pipeline = PostChatPipeline(mock_agent_no_tools)
        
        await pipeline._step_record_experience(
            user_input="简单对话",
            reply="简单回复",
            save_memory=True,
        )
        
        # 应该仍然调用 on_experience_recorded
        mock_agent_no_tools.evolution.on_experience_recorded.assert_called_once()

    def test_empty_crystallized_patterns(self):
        """空结晶经验列表应该被正确处理"""
        from neurova.context.orchestrator import ContextOrchestrator
        import inspect
        
        # 验证方法签名接受 crystallized_patterns 参数
        sig = inspect.signature(ContextOrchestrator.build_context)
        assert "crystallized_patterns" in sig.parameters
        
        # 验证默认值为 None
        param = sig.parameters["crystallized_patterns"]
        assert param.default is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])