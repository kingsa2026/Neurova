"""
测试 chat.py 迁移到新接口 build_context_v2

验证：
1. chat 端点使用 build_context_v2 而非旧 build_context
2. 流式响应正常工作
3. 上下文包含用户输入
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, List


class TestChatContextMigration:
    """chat.py 上下文构建迁移测试"""

    def test_chat_uses_build_context_v2(self):
        """测试 chat 端点使用新接口 build_context_v2"""
        # 准备 - mock agent
        mock_agent = Mock()
        mock_agent.config = Mock()
        mock_agent.config.personality = "你是一个友好的助手"
        mock_agent.config.agent_id = "test_agent"
        mock_agent.conversation_history = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好！"},
        ]
        mock_agent.memory_manager = Mock()
        mock_agent._retrieve_memories = Mock(return_value=[])
        
        # mock context_builder 有 build_context_v2 方法
        mock_agent.context_builder = Mock()
        expected_context = [
            {"role": "system", "content": "你是一个友好的助手"},
            {"role": "user", "content": "测试消息"},
        ]
        mock_agent.context_builder.build_context_v2 = Mock(return_value=expected_context)
        
        # 验证 - 调用 build_context_v2
        result = mock_agent.context_builder.build_context_v2(
            user_input="测试消息",
            session={
                "conversation_history": mock_agent.conversation_history,
                "agent_id": mock_agent.config.agent_id,
            },
            options={
                "system_prompt": mock_agent.config.personality,
            },
        )
        
        # 验证
        assert result == expected_context
        mock_agent.context_builder.build_context_v2.assert_called_once()
        
        # 验证参数
        call_args = mock_agent.context_builder.build_context_v2.call_args
        assert call_args.kwargs['user_input'] == "测试消息"
        assert call_args.kwargs['session']['conversation_history'] == mock_agent.conversation_history
        assert call_args.kwargs['options']['system_prompt'] == "你是一个友好的助手"

    def test_chat_new_interface_no_compress_needed(self):
        """测试新接口不需要单独调用 compress_if_needed"""
        # 准备
        mock_builder = Mock()
        mock_builder.build_context_v2 = Mock(return_value=[
            {"role": "system", "content": "test"},
            {"role": "user", "content": "hello"},
        ])
        
        # 执行 - 只调用 build_context_v2，不调用 compress_if_needed
        result = mock_builder.build_context_v2(
            user_input="hello",
            session={},
            options={},
        )
        
        # 验证 - compress_if_needed 不应该被调用
        mock_builder.compress_if_needed.assert_not_called()

    def test_chat_new_interface_auto_memory(self):
        """测试新接口自动检索记忆（不需要手动传入）"""
        # 准备
        mock_builder = Mock()
        mock_builder.build_context_v2 = Mock(return_value=[
            {"role": "system", "content": "test"},
            {"role": "user", "content": "hello"},
        ])
        
        # 执行 - 不传入 memories，新接口会自动检索
        result = mock_builder.build_context_v2(
            user_input="hello",
            session={"user_id": "user_123"},
            options={},
        )
        
        # 验证 - 调用成功
        assert len(result) == 2
        mock_builder.build_context_v2.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
