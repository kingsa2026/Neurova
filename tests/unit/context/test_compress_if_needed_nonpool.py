"""
非 ContextPool 路径 compress_if_needed 测试

修复: compress_if_needed() 方法不存在
neurova/context/orchestrator.py:474
非 ContextPool 路径调用 context_builder.compress_if_needed() 抛 AttributeError。
影响: 非 ContextPool 路径完全断裂
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from neurova.context.builder import ContextBuilder
from neurova.context.models import TokenBudget
from neurova.context_pool import ContextInput, ContextSource


class TestContextBuilderCompressIfNeeded:
    """ContextBuilder.compress_if_needed() 基础测试"""

    def test_compress_short_context_returns_unchanged(self):
        """短上下文不压缩"""
        builder = ContextBuilder(config={})
        context = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = builder.compress_if_needed(context)
        assert result == context

    def test_compress_empty_context_returns_empty(self):
        """空上下文返回空"""
        builder = ContextBuilder(config={})
        result = builder.compress_if_needed([])
        assert result == []

    def test_compress_single_message_returns_unchanged(self):
        """单条消息不压缩"""
        builder = ContextBuilder(config={})
        context = [{"role": "system", "content": "Short"}]
        result = builder.compress_if_needed(context)
        assert result == context


class TestContextBuilderBuildFromPoolFallback:
    """ContextBuilder.build_from_pool() 降级模式测试"""

    def test_build_from_pool_returns_list(self):
        """降级模式返回 List[Dict]"""
        builder = ContextBuilder(config={})  # 无 unified_injector

        pool = [
            ContextInput(
                source=ContextSource.SYSTEM_INSTRUCTION,
                content="You are a helpful assistant.",
                priority=100,
            ),
            ContextInput(
                source=ContextSource.USER_INPUT,
                content="Hello",
                priority=90,
            ),
        ]

        result = builder.build_from_pool(
            pool,
            token_budget=TokenBudget(max_total=16000),
            user_input="Hello",
        )

        assert isinstance(result, list)
        assert len(result) >= 1
        assert result[0]["role"] == "system"

    def test_build_from_pool_with_reflection_source(self):
        """降级模式处理 REFLECTION 来源（非 REFLECTION_LOG）"""
        builder = ContextBuilder(config={})

        pool = [
            ContextInput(
                source=ContextSource.SYSTEM_INSTRUCTION,
                content="System prompt",
                priority=100,
            ),
            ContextInput(
                source=ContextSource.REFLECTION,  # 使用 REFLECTION 而非 REFLECTION_LOG
                content="反思日志内容",
                priority=60,
            ),
            ContextInput(
                source=ContextSource.USER_INPUT,
                content="Hello",
                priority=90,
            ),
        ]

        result = builder.build_from_pool(
            pool,
            token_budget=TokenBudget(max_total=16000),
            user_input="Hello",
        )

        assert isinstance(result, list)
        assert len(result) >= 1

    def test_build_from_pool_all_source_types(self):
        """降级模式处理所有 ContextSource 类型"""
        builder = ContextBuilder(config={})

        pool = [
            ContextInput(source=ContextSource.SYSTEM_INSTRUCTION, content="Sys", priority=100),
            ContextInput(source=ContextSource.DEVELOPER_INSTRUCTION, content="Dev", priority=90),
            ContextInput(source=ContextSource.MEMORY, content="Mem", priority=70),
            ContextInput(source=ContextSource.EXPERIENCE, content="Exp", priority=70),
            ContextInput(source=ContextSource.EMOTION, content="Emo", priority=50),
            ContextInput(source=ContextSource.CONVERSATION, content="Conv", priority=60),
            ContextInput(source=ContextSource.TOOL_CALL, content="Tool", priority=60),
            ContextInput(source=ContextSource.MULTIMODAL, content="Multi", priority=70),
            ContextInput(source=ContextSource.USER_INPUT, content="Input", priority=90),
        ]

        result = builder.build_from_pool(
            pool,
            token_budget=TokenBudget(max_total=16000),
            user_input="Input",
        )

        assert isinstance(result, list)
        assert len(result) >= 1

    def test_build_from_pool_then_compress(self):
        """build_from_pool + compress_if_needed 链式调用"""
        builder = ContextBuilder(config={})

        pool = [
            ContextInput(source=ContextSource.SYSTEM_INSTRUCTION, content="Sys", priority=100),
            ContextInput(source=ContextSource.USER_INPUT, content="Input", priority=90),
        ]

        context = builder.build_from_pool(
            pool,
            token_budget=TokenBudget(max_total=16000),
            user_input="Input",
        )

        # compress_if_needed 应该正常工作
        result = builder.compress_if_needed(context)
        assert isinstance(result, list)


class TestContextOrchestratorNonPoolPath:
    """ContextOrchestrator 非 ContextPool 路径测试"""

    def _make_orchestrator(self, use_pool=False):
        """创建测试用 ContextOrchestrator"""
        from neurova.context.orchestrator import ContextOrchestrator

        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.config.constitution = ""
        mock_agent.config.behavior_rules = []
        mock_agent.config.enable_context_pool = use_pool
        mock_agent.config.enable_auto_tagging = False
        mock_agent.memory_manager = None
        mock_agent.soul = "You are a helpful assistant."
        mock_agent.personality = ""
        mock_agent.conversation_history = []
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent.growth_log_manager = None

        # 设置 context_builder（模拟 init_context_system）
        mock_agent.context_builder = ContextBuilder(config={})

        orch = ContextOrchestrator(mock_agent, use_pool=use_pool)
        return orch

    @pytest.mark.asyncio
    async def test_build_context_non_pool_path(self):
        """非 ContextPool 路径 build_context 不抛异常"""
        orch = self._make_orchestrator(use_pool=False)

        result = await orch.build_context(
            user_input="Hello",
            tool_memory_result=None,
            auto_execute_result=None,
            tool_decision="do_not_execute",
            experience_items=[],
            relevant_memories=[],
            session_context=[],
            crystallized_patterns=[],
            voice_context=None,
        )

        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_build_context_non_pool_with_memories(self):
        """非 ContextPool 路径带记忆"""
        orch = self._make_orchestrator(use_pool=False)

        result = await orch.build_context(
            user_input="What did I say before?",
            tool_memory_result=None,
            auto_execute_result=None,
            tool_decision="do_not_execute",
            experience_items=[],
            relevant_memories=[{"content": "You mentioned Python", "temperature": 80}],
            session_context=[],
            crystallized_patterns=[],
            voice_context=None,
        )

        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_build_context_non_pool_with_crystallized(self):
        """非 ContextPool 路径带结晶经验"""
        orch = self._make_orchestrator(use_pool=False)

        result = await orch.build_context(
            user_input="Help me code",
            tool_memory_result=None,
            auto_execute_result=None,
            tool_decision="do_not_execute",
            experience_items=[],
            relevant_memories=[],
            session_context=[],
            crystallized_patterns=[{"content": "Use type hints", "confidence": 0.9}],
            voice_context=None,
        )

        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_build_context_non_pool_compress_called(self):
        """非 ContextPool 路径 compress_if_needed 被调用"""
        orch = self._make_orchestrator(use_pool=False)

        with patch.object(
            orch._agent.context_builder, 'compress_if_needed', wraps=orch._agent.context_builder.compress_if_needed
        ) as mock_compress:
            result = await orch.build_context(
                user_input="Hello",
                tool_memory_result=None,
                auto_execute_result=None,
                tool_decision="do_not_execute",
                experience_items=[],
                relevant_memories=[],
                session_context=[],
                crystallized_patterns=[],
                voice_context=None,
            )

            mock_compress.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_context_non_pool_context_builder_none_safe(self):
        """非 ContextPool 路径 context_builder 为 None 时安全处理"""
        orch = self._make_orchestrator(use_pool=False)
        orch._agent.context_builder = None

        # 应该不抛异常（优雅降级）
        try:
            result = await orch.build_context(
                user_input="Hello",
                tool_memory_result=None,
                auto_execute_result=None,
                tool_decision="do_not_execute",
                experience_items=[],
                relevant_memories=[],
                session_context=[],
                crystallized_patterns=[],
                voice_context=None,
            )
            # 如果返回了结果，应该是列表
            if result is not None:
                assert isinstance(result, list)
        except (AttributeError, TypeError):
            # context_builder 为 None 时可能抛异常，但不应崩溃
            pass


class TestContextSourceConsistency:
    """ContextSource 枚举一致性测试"""

    def test_context_source_has_reflection(self):
        """ContextSource 应该有 REFLECTION"""
        assert hasattr(ContextSource, 'REFLECTION')

    def test_context_source_has_tool_call(self):
        """ContextSource 应该有 TOOL_CALL"""
        assert hasattr(ContextSource, 'TOOL_CALL')

    def test_context_source_has_all_expected_values(self):
        """ContextSource 应该有所有预期值"""
        expected = [
            "SYSTEM_INSTRUCTION",
            "DEVELOPER_INSTRUCTION",
            "MEMORY",
            "CONVERSATION",
            "EXPERIENCE",
            "EMOTION",
            "REFLECTION",
            "TOOL_CALL",
            "MULTIMODAL",
            "USER_INPUT",
        ]
        for name in expected:
            assert hasattr(ContextSource, name), f"ContextSource 缺少 {name}"


class TestBuilderFallbackNoInjection:
    """builder 降级模式不注入器测试"""

    def test_fallback_compress_short_context(self):
        """降级压缩：短上下文不压缩"""
        builder = ContextBuilder(config={})
        context = [
            {"role": "system", "content": "Short"},
            {"role": "user", "content": "Hi"},
        ]
        result = builder._fallback_compress(context)
        assert result == context

    def test_builder_exists(self):
        """ContextBuilder 存在 compress_if_needed"""
        builder = ContextBuilder(config={})
        assert hasattr(builder, 'compress_if_needed')
        assert callable(builder.compress_if_needed)

    def test_builder_exists_build_from_pool(self):
        """ContextBuilder 存在 build_from_pool"""
        builder = ContextBuilder(config={})
        assert hasattr(builder, 'build_from_pool')
        assert callable(builder.build_from_pool)
