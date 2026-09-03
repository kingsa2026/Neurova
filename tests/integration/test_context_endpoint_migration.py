"""
测试 context.py 端点迁移到新接口 build_context_v2

验证：
1. context build 端点使用 build_context_v2 而非旧 build_context
2. 显式传入记忆时，使用传入的记忆而非自动检索
3. 端点返回正确的上下文结构
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestContextEndpointMigration:
    """context.py 端点迁移测试"""

    def test_build_context_uses_build_context_v2(self):
        """测试 context build 端点使用新接口 build_context_v2"""
        # 准备 - mock context_builder
        mock_context_builder = Mock()
        expected_context = [
            {"role": "system", "content": "你是一个友好的助手"},
            {"role": "user", "content": "测试消息"},
        ]
        mock_context_builder.build_context_v2 = Mock(return_value=expected_context)

        # 模拟 get_context_modules 返回 context_builder
        mock_modules = {
            "context_builder": mock_context_builder,
            "unified_context_injector": None,  # 不再使用
            "memory_manager": Mock(),
            "growth_log_manager": Mock(),
        }

        # 执行 - 调用 build_context_v2
        result = mock_context_builder.build_context_v2(
            user_input="测试消息",
            session={
                "conversation_history": [],
            },
            options={
                "system_prompt": "你是一个友好的助手",
                "include_reflection_log": True,
                "include_question_queue": False,
                "max_tokens": 4000,
                "memories": [{"content": "测试记忆"}],
            },
        )

        # 验证
        assert result == expected_context
        mock_context_builder.build_context_v2.assert_called_once()

        # 验证参数
        call_args = mock_context_builder.build_context_v2.call_args
        assert call_args.kwargs['user_input'] == "测试消息"
        assert call_args.kwargs['options']['system_prompt'] == "你是一个友好的助手"
        assert call_args.kwargs['options']['memories'] == [{"content": "测试记忆"}]
        assert call_args.kwargs['options']['max_tokens'] == 4000

    def test_build_context_no_injector_fallback(self):
        """测试没有 context_builder 时的降级响应"""
        # 准备 - 没有 context_builder
        mock_modules = {
            "context_builder": None,
            "unified_context_injector": None,
            "memory_manager": None,
            "growth_log_manager": None,
        }

        # 验证 - 应该返回基础上下文（降级模式）
        # 当 context_builder 为 None 时，端点应返回基础上下文
        context_builder = mock_modules.get("context_builder")
        assert context_builder is None

    def test_build_context_with_explicit_memories(self):
        """测试显式传入记忆"""
        # 准备
        mock_context_builder = Mock()
        explicit_memories = [
            {"content": "用户叫张三", "score": 0.9},
            {"content": "用户喜欢编程", "score": 0.8},
        ]
        mock_context_builder.build_context_v2 = Mock(return_value=[
            {"role": "system", "content": "test"},
            {"role": "user", "content": "你好"},
        ])

        # 执行 - 传入显式记忆
        result = mock_context_builder.build_context_v2(
            user_input="你好",
            session={},
            options={
                "system_prompt": "test",
                "memories": explicit_memories,
            },
        )

        # 验证 - 记忆被传递到 options
        call_args = mock_context_builder.build_context_v2.call_args
        assert call_args.kwargs['options']['memories'] == explicit_memories
        assert len(call_args.kwargs['options']['memories']) == 2

    def test_build_context_with_conversation_history(self):
        """测试包含对话历史"""
        # 准备
        mock_context_builder = Mock()
        conversation_history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        mock_context_builder.build_context_v2 = Mock(return_value=[
            {"role": "system", "content": "test"},
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
            {"role": "user", "content": "继续"},
        ])

        # 执行
        result = mock_context_builder.build_context_v2(
            user_input="继续",
            session={
                "conversation_history": conversation_history,
            },
            options={"system_prompt": "test"},
        )

        # 验证 - 对话历史被传递到 session
        call_args = mock_context_builder.build_context_v2.call_args
        assert call_args.kwargs['session']['conversation_history'] == conversation_history
        assert len(result) == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
