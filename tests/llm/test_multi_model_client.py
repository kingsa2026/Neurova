"""
单元测试：测试 MultiModelLLMClient
"""

import unittest
from unittest.mock import Mock, patch
import tempfile
import os

from neurova.llm.multi_model_client import MultiModelLLMClient, ModelClient, get_multi_model_client
from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig, LoadBalancingStrategy


class TestModelClient(unittest.TestCase):
    """测试 ModelClient"""
    
    def test_create_model_client(self):
        """测试创建模型客户端"""
        mock_client = Mock()
        mock_provider = Mock()
        mock_provider.id = "test-provider"
        mock_provider.name = "Test"
        
        client = ModelClient(mock_client, mock_provider, "gpt-4o")
        
        self.assertEqual(client.model, "gpt-4o")
        self.assertEqual(client.request_count, 0)
        self.assertEqual(client.error_count, 0)
    
    def test_increment_request_success(self):
        """测试增加请求计数（成功）"""
        mock_client = Mock()
        mock_provider = Mock()
        client = ModelClient(mock_client, mock_provider, "gpt-4o")
        
        client.increment_request(success=True)
        
        self.assertEqual(client.request_count, 1)
        self.assertEqual(client.error_count, 0)
        self.assertIsNotNone(client.last_used)
    
    def test_increment_request_failure(self):
        """测试增加请求计数（失败）"""
        mock_client = Mock()
        mock_provider = Mock()
        client = ModelClient(mock_client, mock_provider, "gpt-4o")
        
        client.increment_request(success=False)
        
        self.assertEqual(client.request_count, 1)
        self.assertEqual(client.error_count, 1)
    
    def test_success_rate(self):
        """测试计算成功率"""
        mock_client = Mock()
        mock_provider = Mock()
        client = ModelClient(mock_client, mock_provider, "gpt-4o")
        
        # 初始成功率应为 1.0
        self.assertEqual(client.success_rate, 1.0)
        
        # 添加一些请求
        client.increment_request(success=True)
        client.increment_request(success=True)
        client.increment_request(success=False)
        
        # 2/3 成功
        self.assertAlmostEqual(client.success_rate, 2/3, places=2)


class TestMultiModelLLMClient(unittest.TestCase):
    """测试 MultiModelLLMClient"""
    
    def setUp(self):
        """设置测试环境"""
        # 使用临时文件
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.json'
        )
        self.temp_path = self.temp_file.name
        self.temp_file.close()
        
        # 创建管理器
        self.manager = MultiModelLLMClient(
            strategy=LoadBalancingStrategy.PRIORITY_FIRST
        )
    
    def tearDown(self):
        """清理测试环境"""
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)
    
    def test_set_active_model(self):
        """测试设置活跃模型"""
        # 先添加一个提供商
        provider_manager = self.manager._provider_manager
        config = provider_manager.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            default_model="gpt-4o",
        )
        
        # 设置活跃模型
        result = self.manager.set_active_model(config.id, "gpt-4o")
        
        self.assertTrue(result)
        self.assertEqual(self.manager._current_provider_id, config.id)
        self.assertEqual(self.manager._current_model, "gpt-4o")
    
    def test_get_current_client(self):
        """测试获取当前客户端"""
        # 先设置一个活跃模型
        provider_manager = self.manager._provider_manager
        config = provider_manager.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            default_model="gpt-4o",
        )
        
        self.manager.set_active_model(config.id, "gpt-4o")
        
        # 获取当前客户端
        client = self.manager.get_current_client()
        
        self.assertIsNotNone(client)
        self.assertEqual(client.model, "gpt-4o")
    
    def test_list_available_models(self):
        """测试列出可用模型"""
        # 添加提供商
        provider_manager = self.manager._provider_manager
        config = provider_manager.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            default_model="gpt-4o",
            models=["gpt-4o", "gpt-3.5-turbo"],
        )
        
        # 列出模型
        models = self.manager.list_available_models()
        
        self.assertGreater(len(models), 0)
    
    def test_get_stats(self):
        """测试获取统计信息"""
        stats = self.manager.get_stats()
        
        self.assertIn("total_models", stats)
        self.assertIn("total_requests", stats)
        self.assertIn("total_errors", stats)
        self.assertIn("overall_success_rate", stats)


if __name__ == "__main__":
    unittest.main()
