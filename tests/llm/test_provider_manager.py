"""
单元测试：测试 LLMProviderManager
"""

import unittest
from unittest.mock import Mock, patch
import tempfile
import os
import json

from neurova.llm.provider_manager import (
    LLMProviderManager,
    ProviderConfig,
    LoadBalancingStrategy,
)


class TestLoadBalancingStrategy(unittest.TestCase):
    """测试负载均衡策略枚举"""
    
    def test_strategy_values(self):
        """测试枚举值"""
        self.assertEqual(LoadBalancingStrategy.ROUND_ROBIN.value, "round_robin")
        self.assertEqual(LoadBalancingStrategy.WEIGHTED_RANDOM.value, "weighted_random")
        self.assertEqual(LoadBalancingStrategy.PRIORITY_FIRST.value, "priority_first")
        self.assertEqual(LoadBalancingStrategy.LEAST_ERRORS.value, "least_errors")
        self.assertEqual(LoadBalancingStrategy.FASTEST_RESPONSE.value, "fastest_response")


class TestProviderConfig(unittest.TestCase):
    """测试 ProviderConfig 数据类"""
    
    def test_create_provider_config(self):
        """测试创建提供商配置"""
        config = ProviderConfig(
            id="test-provider",
            name="Test Provider",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            default_model="gpt-4o",
            models=["gpt-4o", "gpt-3.5-turbo"],
            enabled=True,
            priority=10,
            weight=80,
        )
        
        self.assertEqual(config.id, "test-provider")
        self.assertEqual(config.name, "Test Provider")
        self.assertEqual(config.provider, "OpenAI")
        self.assertEqual(config.priority, 10)
        self.assertEqual(config.weight, 80)
        self.assertEqual(config.health_status, "unknown")
        self.assertEqual(config.concurrent_failures, 0)
    
    def test_provider_config_to_dict(self):
        """测试转换为字典"""
        config = ProviderConfig(
            id="test",
            name="Test",
            provider="Test",
            base_url="https://test.com/v1",
        )
        
        data = config.to_dict()
        self.assertEqual(data["id"], "test")
        self.assertEqual(data["name"], "Test")
    
    def test_provider_config_from_dict(self):
        """测试从字典创建"""
        data = {
            "id": "test2",
            "name": "Test2",
            "provider": "Test2",
            "base_url": "https://test2.com/v1",
            "priority": 5,
            "weight": 90,
        }
        
        config = ProviderConfig.from_dict(data)
        self.assertEqual(config.id, "test2")
        self.assertEqual(config.priority, 5)
        self.assertEqual(config.weight, 90)


class TestLLMProviderManager(unittest.TestCase):
    """测试 LLMProviderManager"""
    
    def setUp(self):
        """设置测试环境"""
        # 使用临时文件
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.json'
        )
        self.temp_path = self.temp_file.name
        self.temp_file.close()
        
        # 创建管理器
        self.manager = LLMProviderManager(config_path=self.temp_path)
    
    def tearDown(self):
        """清理测试环境"""
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)
    
    def test_add_provider(self):
        """测试添加提供商"""
        config = self.manager.add_provider(
            name="Test Provider",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            default_model="gpt-4o",
            models=["gpt-4o", "gpt-3.5-turbo"],
            priority=10,
            weight=80,
        )
        
        self.assertIsNotNone(config)
        self.assertEqual(config.name, "Test Provider")
        self.assertEqual(config.priority, 10)
        self.assertEqual(config.weight, 80)
    
    def test_update_provider(self):
        """测试更新提供商"""
        # 先添加
        config = self.manager.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
        )
        
        # 更新
        updated = self.manager.update_provider(
            provider_id=config.id,
            api_key="sk-new",
            priority=20,
            weight=90,
        )
        
        self.assertIsNotNone(updated)
        self.assertEqual(updated.priority, 20)
        self.assertEqual(updated.weight, 90)
    
    def test_remove_provider(self):
        """测试删除提供商"""
        config = self.manager.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
        )
        
        result = self.manager.remove_provider(config.id)
        self.assertTrue(result)
        
        # 再次查找应该返回 None
        found = self.manager.get_provider(config.id)
        self.assertIsNone(found)
    
    def test_get_healthy_providers(self):
        """测试获取健康的服务商"""
        # 添加两个提供商
        config1 = self.manager.add_provider(
            name="Provider1",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            priority=10,
        )
        config1.health_status = "healthy"
        
        config2 = self.manager.add_provider(
            name="Provider2",
            provider="Anthropic",
            base_url="https://api.anthropic.com",
            priority=5,
        )
        config2.health_status = "degraded"
        
        # 获取健康的服务商
        healthy = self.manager.get_healthy_providers(
            strategy=LoadBalancingStrategy.PRIORITY_FIRST
        )
        
        self.assertGreater(len(healthy), 0)
        # 应该按优先级排序
        self.assertEqual(healthy[0].priority, 10)
    
    def test_mark_provider_success(self):
        """测试标记成功"""
        config = self.manager.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
        )
        
        self.manager.mark_provider_success(config.id, response_time=0.5)
        
        # 重新加载
        reloaded = self.manager.get_provider(config.id)
        self.assertGreater(reloaded.concurrent_successes, 0)
        self.assertEqual(reloaded.health_status, "healthy")
    
    def test_mark_provider_failure(self):
        """测试标记失败"""
        config = self.manager.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
        )
        
        self.manager.mark_provider_failure(config.id)
        
        # 重新加载
        reloaded = self.manager.get_provider(config.id)
        self.assertGreater(reloaded.concurrent_failures, 0)
        self.assertEqual(reloaded.health_status, "degraded")
    
    def test_select_provider(self):
        """测试选择提供商"""
        config = self.manager.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        config.health_status = "healthy"
        
        selected = self.manager.select_provider(
            strategy=LoadBalancingStrategy.PRIORITY_FIRST
        )
        
        self.assertIsNotNone(selected)
        self.assertEqual(selected.id, config.id)
    
    def test_auto_failover(self):
        """测试自动故障转移"""
        # 添加两个提供商
        config1 = self.manager.add_provider(
            name="Provider1",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        config1.health_status = "failed"
        config1.concurrent_failures = 3
        
        config2 = self.manager.add_provider(
            name="Provider2",
            provider="Anthropic",
            base_url="https://api.anthropic.com",
            default_model="claude-3",
        )
        config2.health_status = "healthy"
        
        # 执行故障转移
        new_provider = self.manager.auto_failover(config1.id)
        
        self.assertIsNotNone(new_provider)
        self.assertEqual(new_provider.id, config2.id)


if __name__ == "__main__":
    unittest.main()
