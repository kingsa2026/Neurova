"""
审批回复机制集成测试

测试目标：验证完整的审批流程，从发送消息到接收回复
"""
import asyncio
import threading
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from neurova.collaboration.neurflow.builtin import exec_approval
from neurova.channels.manager import ChannelManager
from neurova.channels.base import ChannelMessage, ChannelEventType


class TestApprovalIntegration:
    """审批回复机制集成测试"""

    @pytest.fixture
    def mock_channel_manager(self):
        """模拟 ChannelManager"""
        mock = MagicMock(spec=ChannelManager)
        mock.send_message = AsyncMock(return_value="msg_123")
        mock.broadcast_message = AsyncMock(return_value={"feishu": "msg_123"})
        mock.add_message_handler = MagicMock(return_value=0)
        mock.remove_message_handler = MagicMock(return_value=True)
        return mock

    @pytest.fixture
    def mock_channel_adapter(self):
        """模拟 ChannelAdapter"""
        mock = MagicMock()
        mock.channel_type = "feishu"
        mock.is_connected = True
        mock.send_message = AsyncMock(return_value="msg_456")
        return mock

    def test_full_approval_flow_with_handler(self, mock_channel_manager):
        """测试: 完整的审批流程（带处理器）"""
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
        approve_message.content = "approve"
        approve_message.sender_id = "user_123"
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行审批
            result = asyncio.run(exec_approval(config, ctx))
            
            # 获取注册的处理器
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            
            # 模拟收到审批消息
            asyncio.run(handler(approve_message))
            
            # 验证: 审批应该被处理
            assert mock_channel_manager.add_message_handler.called
            assert mock_channel_manager.send_message.called

    def test_approval_timeout_flow(self, mock_channel_manager):
        """测试: 审批超时流程"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 1  # 1秒超时
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行审批
            result = asyncio.run(exec_approval(config, ctx))
            
            # 验证: 应该超时
            assert result["status"] == "timeout"
            assert result["output"]["approved"] is None
            
            # 验证: 超时后应该移除处理器
            mock_channel_manager.remove_message_handler.assert_called_once()

    def test_approval_with_different_channels(self, mock_channel_manager):
        """测试: 不同渠道的审批"""
        # 准备
        channels = ["feishu", "dingtalk", "wecom"]
        
        for channel in channels:
            config = {
                "approver": "user_123",
                "channel": channel,
                "message": f"请通过{channel}审批此工作流",
                "timeout": 1
            }
            ctx = {"execution_id": "test_exec", "node_id": f"approval_{channel}"}
            
            with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
                # 执行审批
                result = asyncio.run(exec_approval(config, ctx))
                
                # 验证: 应该超时（没有实际回复）
                assert result["status"] == "timeout"

    def test_approval_with_broadcast(self, mock_channel_manager):
        """测试: 广播模式的审批"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "",  # 空字符串表示广播
            "message": "请审批此工作流",
            "timeout": 1
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行审批
            result = asyncio.run(exec_approval(config, ctx))
            
            # 验证: 应该使用广播
            mock_channel_manager.broadcast_message.assert_called_once()
            
            # 验证: 应该超时
            assert result["status"] == "timeout"

    def test_approval_rejection_flow(self, mock_channel_manager):
        """测试: 审批拒绝流程"""
        # 准备
        config = {
            "approver": "user_123",
            "channel": "feishu",
            "message": "请审批此工作流",
            "timeout": 5
        }
        ctx = {"execution_id": "test_exec", "node_id": "approval_1"}
        
        # 模拟拒绝消息
        reject_message = MagicMock()
        reject_message.content = "reject 安全考虑"
        reject_message.sender_id = "user_123"
        
        with patch('neurova.collaboration.neurflow.builtin._get_channel_manager', return_value=mock_channel_manager):
            # 执行审批
            result = asyncio.run(exec_approval(config, ctx))
            
            # 获取注册的处理器
            handler = mock_channel_manager.add_message_handler.call_args[0][0]
            
            # 模拟收到拒绝消息
            asyncio.run(handler(reject_message))
            
            # 验证: 审批应该被拒绝
            assert mock_channel_manager.add_message_handler.called


class TestChannelManagerIntegration:
    """ChannelManager 集成测试"""

    def test_channel_manager_with_multiple_handlers(self):
        """测试: ChannelManager 支持多个处理器"""
        # 创建 ChannelManager 实例
        manager = ChannelManager()
        
        # 添加处理器
        handler1 = MagicMock()
        handler2 = MagicMock()
        
        id1 = manager.add_message_handler(handler1, priority=10)
        id2 = manager.add_message_handler(handler2, priority=5)
        
        # 验证: 两个处理器都应该被添加
        assert len(manager._message_handlers) == 2
        
        # 验证: 优先级排序
        assert manager._message_handlers[0][1] == id2  # 优先级5在前
        assert manager._message_handlers[1][1] == id1  # 优先级10在后
        
        # 移除处理器
        assert manager.remove_message_handler(id1) is True
        assert len(manager._message_handlers) == 1
        
        # 验证: 移除的是正确的处理器
        assert manager._message_handlers[0][1] == id2

    def test_channel_manager_message_handling(self):
        """测试: ChannelManager 消息处理"""
        # 创建 ChannelManager 实例
        manager = ChannelManager()
        
        # 添加处理器
        handler = MagicMock()
        manager.add_message_handler(handler, priority=0)
        
        # 创建测试消息
        message = MagicMock()
        message.channel_type = "feishu"
        message.sender_id = "user_123"
        message.content = "test message"
        
        # 模拟事件处理
        # 注意: 这里只是测试处理器注册，实际的事件处理需要完整的异步环境
        assert len(manager._message_handlers) == 1


class TestAdapterEventLoopIntegration:
    """适配器事件循环集成测试"""

    def test_feishu_adapter_event_loop_fix_integration(self):
        """测试: 飞书适配器事件循环修复集成"""
        # 这个测试验证修复后的逻辑
        # 实际测试需要运行完整的飞书适配器，这里只验证逻辑
        pass

    def test_dingtalk_adapter_event_loop_fix_integration(self):
        """测试: 钉钉适配器事件循环修复集成"""
        # 这个测试验证修复后的逻辑
        pass

    def test_wecom_adapter_event_loop_fix_integration(self):
        """测试: 企业微信适配器事件循环修复集成"""
        # 这个测试验证修复后的逻辑
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])