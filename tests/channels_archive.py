"""
单元测试：测试 ChannelManager
"""

import unittest
from unittest.mock import Mock, patch
import tempfile
import os
from datetime import datetime

from neurova.channels import (
    ChannelManager,
    ChannelConfig,
    MessageChannel,
)


class TestChannelConfig(unittest.TestCase):
    """测试 ChannelConfig"""
    
    def test_create_channel_config(self):
        """测试创建渠道配置"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
            priority=10,
        )
        
        self.assertEqual(config.channel, MessageChannel.FEISHU)
        self.assertTrue(config.enabled)
        self.assertEqual(config.priority, 10)
        self.assertEqual(config.health_status, "unknown")


class TestChannelManager(unittest.TestCase):
    """测试 ChannelManager"""
    
    def setUp(self):
        """设置测试环境"""
        # 使用临时文件
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.json'
        )
        self.temp_path = self.temp_file.name
        self.temp_file.close()
        
        # 创建管理器
        self.manager = ChannelManager(
            config_path=self.temp_path,
            default_agent_id="test-agent"
        )
    
    def tearDown(self):
        """清理测试环境"""
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)
    
    def test_add_channel(self):
        """测试添加渠道"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
            config={"app_id": "test-id", "app_secret": "test-secret"},
            priority=10,
        )
        
        result = self.manager.add_channel(config)
        
        self.assertTrue(result)
        
        # 验证已添加
        retrieved = self.manager.get_channel_config(MessageChannel.FEISHU)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.priority, 10)
    
    def test_remove_channel(self):
        """测试移除渠道"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
        )
        self.manager.add_channel(config)
        
        # 移除
        result = self.manager.remove_channel(MessageChannel.FEISHU)
        
        self.assertTrue(result)
        
        # 验证已移除
        retrieved = self.manager.get_channel_config(MessageChannel.FEISHU)
        self.assertIsNone(retrieved)
    
    def test_set_channel_priority(self):
        """测试设置渠道优先级"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
        )
        self.manager.add_channel(config)
        
        # 设置优先级
        result = self.manager.set_channel_priority(MessageChannel.FEISHU, 20)
        
        self.assertTrue(result)
        
        # 验证
        retrieved = self.manager.get_channel_config(MessageChannel.FEISHU)
        self.assertEqual(retrieved.priority, 20)
    
    def test_get_channels_by_priority(self):
        """测试按优先级获取渠道"""
        # 添加两个渠道
        config1 = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
            priority=10,
        )
        self.manager.add_channel(config1)
        
        config2 = ChannelConfig(
            channel=MessageChannel.DINGTALK,
            enabled=True,
            priority=20,
        )
        self.manager.add_channel(config2)
        
        # 按优先级获取
        channels = self.manager.get_channels_by_priority(enabled_only=True)
        
        self.assertEqual(len(channels), 2)
        # 应该按优先级降序排序
        self.assertEqual(channels[0]["config"].priority, 20)
        self.assertEqual(channels[1]["config"].priority, 10)
    
    def test_get_preferred_channel(self):
        """测试获取首选渠道"""
        # 添加渠道
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
            priority=10,
            health_status="healthy",
        )
        self.manager.add_channel(config)
        
        # 获取首选渠道
        preferred = self.manager.get_preferred_channel()
        
        self.assertEqual(preferred, MessageChannel.FEISHU)
    
    def test_mark_channel_success(self):
        """测试标记渠道成功"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
        )
        self.manager.add_channel(config)
        
        # 标记成功
        self.manager.mark_channel_success(MessageChannel.FEISHU, response_time=0.5)
        
        # 验证
        retrieved = self.manager.get_channel_config(MessageChannel.FEISHU)
        self.assertGreater(retrieved.concurrent_successes, 0)
        self.assertEqual(retrieved.health_status, "healthy")
    
    def test_mark_channel_failure(self):
        """测试标记渠道失败"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
        )
        self.manager.add_channel(config)
        
        # 标记失败
        self.manager.mark_channel_failure(MessageChannel.FEISHU)
        
        # 验证
        retrieved = self.manager.get_channel_config(MessageChannel.FEISHU)
        self.assertGreater(retrieved.concurrent_failures, 0)
        self.assertEqual(retrieved.health_status, "degraded")
    
    def test_update_channel_health(self):
        """测试更新渠道健康状态"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
        )
        self.manager.add_channel(config)
        
        # 更新健康状态（成功）
        self.manager.update_channel_health(MessageChannel.FEISHU, success=True)
        
        # 验证
        retrieved = self.manager.get_channel_config(MessageChannel.FEISHU)
        self.assertGreater(retrieved.concurrent_successes, 0)
    
    def test_list_channels(self):
        """测试列出渠道"""
        # 添加渠道
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
            priority=10,
        )
        self.manager.add_channel(config)
        
        # 列出
        channels = self.manager.list_channels()
        
        self.assertGreaterEqual(len(channels), 1)
    
    def test_get_channel_status(self):
        """测试获取渠道状态"""
        config = ChannelConfig(
            channel=MessageChannel.FEISHU,
            enabled=True,
            priority=10,
        )
        self.manager.add_channel(config)
        
        # 获取状态
        status = self.manager.get_channel_status(MessageChannel.FEISHU)
        
        self.assertIn("channel", status)
        self.assertIn("enabled", status)
        self.assertIn("priority", status)


if __name__ == "__main__":
    unittest.main()
