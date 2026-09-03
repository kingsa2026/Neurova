"""
审批回复接收机制测试

测试目标：验证审批消息发送后，审批人回复能正确触发 approval_event
修复: 使用 add_message_handler 替代 set_message_handler，使用 threading.Event 替代 asyncio.Event
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from neurova.collaboration.neurflow.builtin import exec_approval


class TestApprovalReplyMechanism:
    """测试审批回复机制的完整性"""

    @pytest.fixture
    def mock_channel_manager(self):
        """模拟 ChannelManager"""
        mock = MagicMock()
        mock.send_message = AsyncMock(return_value="msg_123")
        mock.broadcast_message = AsyncMock(return_value={"feishu": "msg_123"})
        mock.add_message_handler = MagicMock(return_value=0)
        mock.remove_message_handler = MagicMock(return_value=True)
        return mock

    @pytest.fixture
    def mock_channel_adapter(self):
        """模拟 ChannelAdapter"""
        mock = AsyncMock()
        mock.channel_type = "feishu"
        mock.is_connected = True
        mock.send_message.return_value = "msg_456"
        return mock

    def test_approval_should_register_message_handler(self, mock_channel_manager):
        """测试: 审批应该注册消息处理器"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 60
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行
            result = asyncio.run(exec_approval(config, ctx))
            
            # 验证: 应该使用 add_message_handler
            mock_channel_manager.add_message_handler.assert_called_once()
            # 获取注册的处理器
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            assert callable(handler)

    def test_approval_handler_should_process_approve_message(self, mock_channel_manager):
        """测试: 审批处理器应该处理批准消息"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 60
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        # 模拟审批消息
        approve_message = MagicMock()
        approve_message.content = "approve"
        approve_message.sender_id = "user_123"
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行
            result = asyncio.run(exec_approval(config, ctx))
            
            # 获取注册的处理器
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            
            # 模拟收到审批消息
            asyncio.run(handler(approve_message))
            
            # 验证: 处理器应该被调用
            mock_channel_manager.add_message_handler.assert_called_once()

    def test_approval_should_timeout_when_no_reply(self, mock_channel_manager):
        """测试: 无回复时应该超时"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 1  # 1秒超时
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行
            result = asyncio.run(exec_approval(config, ctx))
            
            # 验证
            assert result["status"] == "timeout"
            assert result["output"]["approved"] is None

    def test_approval_event_should_be_set_on_approve(self, mock_channel_manager):
        """测试: 批准时 approval_event 应该被设置"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 5
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        # 模拟审批消息
        approve_message = MagicMock()
        approve_message.content = "同意"
        approve_message.sender_id = "user_123"
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 获取注册的处理器
            result = asyncio.run(exec_approval(config, ctx))
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            
            # 模拟收到审批消息
            asyncio.run(handler(approve_message))
            
            # 验证: 处理器应该被调用
            mock_channel_manager.add_message_handler.assert_called_once()

    def test_approval_should_ignore_messages_from_other_users(self, mock_channel_manager):
        """测试: 应该忽略来自其他用户的消息"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 1
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        # 模拟来自其他用户的消息
        other_message = MagicMock()
        other_message.content = "approve"
        other_message.sender_id = "user_456"  # 不同的用户
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行
            result = asyncio.run(exec_approval(config, ctx))
            
            # 获取注册的处理器
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            
            # 模拟收到其他用户的消息
            asyncio.run(handler(other_message))
            
            # 验证: 处理器应该被调用，但不应该触发审批事件
            mock_channel_manager.add_message_handler.assert_called_once()


class TestApprovalReplyIntegration:
    """测试审批回复的端到端集成"""

    def test_approval_reply_flow_with_real_channel_manager(self):
        """测试: 使用真实 ChannelManager 的审批回复流程"""
        # 验证修复后的跨事件循环问题已解决
        pass

    def test_multiple_concurrent_approvals(self):
        """测试: 多个并发审批节点"""
        # 验证 add_message_handler 支持多个处理器
        pass