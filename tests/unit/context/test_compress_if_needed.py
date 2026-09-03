"""
compress_if_needed 方法测试

修复: ContextBuilder.compress_if_needed() 方法不存在
影响: 非 ContextPool 路径调用 context_builder.compress_if_needed() 抛 AttributeError
"""

import pytest
from unittest.mock import MagicMock, patch
from neurova.context.builder import ContextBuilder


class TestCompressIfNeeded:
    """ContextBuilder.compress_if_needed 方法测试"""

    def test_short_context_returns_unchanged(self):
        """短上下文不压缩，直接返回"""
        builder = ContextBuilder(config={})

        # 构建一个小上下文（远低于 MAX_CONTEXT_TOKENS）
        context = [
            {"role": "system", "content": "你是一个AI助手"},
            {"role": "user", "content": "你好"},
        ]

        result = builder.compress_if_needed(context)

        # 上下文很短，不应被压缩
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[-1]["role"] == "user"

    def test_empty_context_returns_empty(self):
        """空上下文返回空列表"""
        builder = ContextBuilder(config={})
        result = builder.compress_if_needed([])
        assert result == []

    def test_single_message_returns_unchanged(self):
        """单条消息不压缩"""
        builder = ContextBuilder(config={})
        context = [{"role": "system", "content": "test"}]
        result = builder.compress_if_needed(context)
        assert len(result) == 1

    def test_fallback_compress_truncates_history(self):
        """降级模式：长历史被截断"""
        builder = ContextBuilder(config={})

        # 构建一个超大上下文
        system_msg = {"role": "system", "content": "你是一个AI助手"}
        user_msg = {"role": "user", "content": "最后的问题"}

        # 生成大量历史消息（每条约 500 tokens）
        history = []
        for i in range(100):
            history.append({
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"这是第{i}轮对话，" + "测试内容" * 50
            })

        context = [system_msg] + history + [user_msg]

        result = builder.compress_if_needed(context)

        # 结果应该有 system + 截断历史 + user
        assert result[0]["role"] == "system"
        assert result[-1]["role"] == "user"
        # 历史被截断了
        assert len(result) < len(context)

    def test_compressed_context_preserves_system_and_user(self):
        """压缩后保留系统消息和用户消息"""
        builder = ContextBuilder(config={})

        system_msg = {"role": "system", "content": "核心系统指令"}
        user_msg = {"role": "user", "content": "最终问题"}

        # 大量历史
        history = [
            {"role": "user", "content": "问题" + "x" * 1000}
            for _ in range(50)
        ]

        context = [system_msg] + history + [user_msg]
        result = builder.compress_if_needed(context)

        # system 和 user 消息必须保留
        assert result[0] == system_msg
        assert result[-1] == user_msg

    def test_with_unified_injector_delegates(self):
        """有 UnifiedContextInjector 时委托给 injector"""
        mock_injector = MagicMock()
        mock_injector._count_tokens = MagicMock(return_value=100)
        mock_injector._compress_context = MagicMock(return_value=(
            "压缩后的系统消息",
            [{"role": "assistant", "content": "压缩后的历史"}],
            0.5,
        ))

        builder = ContextBuilder(config={}, unified_injector=mock_injector)

        # 构建超大上下文（总 token > MAX_CONTEXT_TOKENS）
        # MAX_CONTEXT_TOKENS = 16000，每个 msg token = 100
        # 200 条消息 = 20000 tokens > 16000
        context = [
            {"role": "system", "content": f"系统消息{i}"}
            for i in range(200)
        ]

        result = builder.compress_if_needed(context)

        # 应该调用了 injector._compress_context
        mock_injector._compress_context.assert_called_once()
        # 结果应该有 system + 历史 + user
        assert len(result) >= 2
        assert result[0]["content"] == "压缩后的系统消息"

    def test_with_unified_injector_fallback_on_error(self):
        """injector 压缩失败时降级到 fallback"""
        mock_injector = MagicMock()
        mock_injector._count_tokens = MagicMock(return_value=100)
        mock_injector._compress_context = MagicMock(side_effect=Exception("压缩失败"))

        builder = ContextBuilder(config={}, unified_injector=mock_injector)

        # 构建超大上下文
        system_msg = {"role": "system", "content": "系统"}
        user_msg = {"role": "user", "content": "用户"}
        history = [
            {"role": "user", "content": "x" * 1000}
            for _ in range(200)
        ]
        context = [system_msg] + history + [user_msg]

        # 不应该抛异常，应该降级到 fallback
        result = builder.compress_if_needed(context)
        assert result[0]["role"] == "system"
        assert result[-1]["role"] == "user"

    def test_method_exists_on_builder(self):
        """ContextBuilder 公开接口包含 compress_if_needed"""
        builder = ContextBuilder(config={})
        assert hasattr(builder, "compress_if_needed")
        assert callable(builder.compress_if_needed)


class TestContextOrchestratorCompressIntegration:
    """验证 ContextOrchestrator.build_context 中 compress_if_needed 不再抛 AttributeError"""

    @pytest.mark.asyncio
    async def test_compress_if_needed_called_in_orchestrator(self):
        """orchestrator.build_context 调用 compress_if_needed 不抛 AttributeError"""
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.name = "test_agent"
        mock_agent.config.constitution = ""
        mock_agent.config.behavior_rules = ["规则1"]
        mock_agent.memory_manager = MagicMock()
        mock_agent.tool_router = MagicMock()
        mock_agent._skill_registry = MagicMock()
        mock_agent._skill_registry.skills = {}
        mock_agent.soul = "你是一个AI助手"
        mock_agent.personality = "友好"
        mock_agent.conversation_history = []
        mock_agent.growth_log_manager = None

        from neurova.context.orchestrator import ContextOrchestrator

        # 不使用 ContextPool 路径（use_pool=False）
        orchestrator = ContextOrchestrator(mock_agent, use_pool=False)

        # mock context_builder 的 compress_if_needed
        mock_builder = ContextBuilder(config={})
        mock_builder.build_from_pool = MagicMock(return_value=[
            {"role": "system", "content": "test"},
            {"role": "user", "content": "你好"},
        ])
        mock_builder.compress_if_needed = MagicMock(return_value=[
            {"role": "system", "content": "test"},
            {"role": "user", "content": "你好"},
        ])
        mock_agent.context_builder = mock_builder

        from unittest.mock import AsyncMock
        orchestrator.get_tools_description = AsyncMock(return_value="")

        result = await orchestrator.build_context(
            user_input="你好",
            relevant_memories=[],
            experience_items=[],
        )

        # 关键验证：compress_if_needed 被调用
        mock_builder.compress_if_needed.assert_called_once()
        assert isinstance(result, list)
        assert len(result) == 2
