"""
单元测试：测试 LLMConfigConsole
"""

import unittest
from unittest.mock import Mock, patch
import tempfile
import os
from datetime import datetime, timedelta

from neurova.llm.config_console import LLMConfigConsole


class TestLLMConfigConsole(unittest.TestCase):
    """测试 LLMConfigConsole"""
    
    def setUp(self):
        """设置测试环境"""
        # 使用临时文件
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.json'
        )
        self.temp_path = self.temp_file.name
        self.temp_file.close()
        
        # 创建控制台
        self.console = LLMConfigConsole(config_path=self.temp_path)
    
    def tearDown(self):
        """清理测试环境"""
        if os.path.exists(self.temp_path):
            os.unlink(self.temp_path)
        
        # 清理 token_usage.json
        token_path = os.path.join(os.path.dirname(self.temp_path), "token_usage.json")
        if os.path.exists(token_path):
            os.unlink(token_path)
    
    def test_list_providers(self):
        """测试列出提供商"""
        providers = self.console.list_providers()
        
        # 应该有内置提供商
        self.assertGreaterEqual(len(providers), 0)
    
    def test_add_provider(self):
        """测试添加提供商"""
        result = self.console.add_provider(
            name="Test Provider",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            default_model="gpt-4o",
            models=["gpt-4o", "gpt-3.5-turbo"],
            priority=10,
            weight=80,
        )
        
        self.assertEqual(result["name"], "Test Provider")
        self.assertEqual(result["priority"], 10)
        self.assertEqual(result["weight"], 80)
    
    def test_update_provider(self):
        """测试更新提供商"""
        # 先添加
        result = self.console.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
        )
        provider_id = result["id"]
        
        # 更新
        updated = self.console.update_provider(
            provider_id=provider_id,
            api_key="sk-new",
            priority=20,
            weight=90,
        )
        
        self.assertIsNotNone(updated)
        self.assertEqual(updated["priority"], 20)
    
    def test_remove_provider(self):
        """测试删除提供商"""
        # 先添加
        result = self.console.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
        )
        provider_id = result["id"]
        
        # 删除
        result = self.console.remove_provider(provider_id)
        
        self.assertTrue(result)
        
        # 再次查找应该返回 None
        found = self.console.get_provider(provider_id)
        self.assertIsNone(found)
    
    def test_get_default_params(self):
        """测试获取默认参数"""
        params = self.console.get_default_params()
        
        self.assertIn("temperature", params)
        self.assertIn("top_p", params)
        self.assertIn("max_tokens", params)
        self.assertEqual(params["temperature"], 0.7)
    
    def test_update_default_params(self):
        """测试更新默认参数"""
        params = self.console.update_default_params(
            temperature=0.9,
            max_tokens=4096,
        )
        
        self.assertEqual(params["temperature"], 0.9)
        self.assertEqual(params["max_tokens"], 4096)
    
    def test_get_provider_params(self):
        """测试获取提供商参数"""
        # 先添加提供商
        result = self.console.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
        )
        provider_id = result["id"]
        
        # 获取参数
        params = self.console.get_provider_params(provider_id)
        
        # 应该返回默认参数（因为还没设置）
        self.assertEqual(params["temperature"], 0.7)
    
    def test_update_provider_params(self):
        """测试更新提供商参数"""
        # 先添加提供商
        result = self.console.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
        )
        provider_id = result["id"]
        
        # 更新参数
        params = self.console.update_provider_params(
            provider_id=provider_id,
            temperature=0.5,
            top_p=0.8,
        )
        
        self.assertEqual(params["temperature"], 0.5)
        self.assertEqual(params["top_p"], 0.8)
    
    def test_reset_provider_params(self):
        """测试重置提供商参数"""
        # 先添加提供商
        result = self.console.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
        )
        provider_id = result["id"]
        
        # 更新参数
        self.console.update_provider_params(
            provider_id=provider_id,
            temperature=0.5,
        )
        
        # 重置
        params = self.console.reset_provider_params(provider_id)
        
        # 应该返回默认参数
        self.assertEqual(params["temperature"], 0.7)
    
    def test_record_token_usage(self):
        """测试记录 Token 使用"""
        # 先添加提供商
        result = self.console.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        provider_id = result["id"]
        
        # 记录 Token 使用
        self.console.record_token_usage(
            provider_id=provider_id,
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            cost=0.003,
        )
        
        # 获取统计
        usage = self.console.get_token_usage()
        
        self.assertGreater(usage["total_input_tokens"], 0)
        self.assertGreater(usage["total_output_tokens"], 0)
        self.assertGreater(usage["total_cost"], 0)
    
    def test_get_token_usage_summary(self):
        """测试获取 Token 使用摘要"""
        summary = self.console.get_token_usage_summary(days=7)
        
        self.assertIn("period_days", summary)
        self.assertIn("usage", summary)
        self.assertIn("daily_average", summary)
        self.assertEqual(summary["period_days"], 7)
    
    def test_reset_token_usage(self):
        """测试重置 Token 使用统计"""
        # 先添加提供商并记录 Token 使用
        result = self.console.add_provider(
            name="Test",
            provider="OpenAI",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o",
        )
        provider_id = result["id"]
        
        self.console.record_token_usage(
            provider_id=provider_id,
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
        )
        
        # 重置
        self.console.reset_token_usage()
        
        # 获取统计
        usage = self.console.get_token_usage()
        
        self.assertEqual(usage["total_input_tokens"], 0)
        self.assertEqual(usage["total_output_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
