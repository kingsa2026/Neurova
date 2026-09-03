"""
RSI 集成管理器测试

测试 RSI 与四大闭环系统的集成
"""

import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, List, Any

from neurova.evolution.rsi.integration_manager import RSIIntegrationManager, ParameterInfo


class TestRSIIntegrationManager(unittest.TestCase):
    """测试 RSI 集成管理器"""
    
    def setUp(self):
        """测试前准备"""
        # 模拟四大闭环系统
        self.sleep_system = MagicMock()
        self.emotion_system = MagicMock()
        self.experience_system = MagicMock()
        self.tool_memory_system = MagicMock()
        
        # 设置模拟系统的属性
        self.sleep_system.base_decay_rate = 0.1
        self.sleep_system.similarity_threshold = 0.8
        self.sleep_system.merge_threshold = 3
        
        self.emotion_system.emotional_protection_threshold = 0.5
        self.emotion_system.emotional_protection_factor = 0.6
        
        self.experience_system.crystallize_min_observations = 3
        self.experience_system.crystallize_min_success_rate = 0.6
        self.experience_system.pattern_min_support = 0.1
        
        self.tool_memory_system.success_bonus = 0.1
        self.tool_memory_system.failure_penalty = 0.9
        self.tool_memory_system.decay_rate = 0.01
        self.tool_memory_system.muscle_memory_threshold = 0.7
    
    def test_initialization(self):
        """测试初始化"""
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
        
        manager = RSIIntegrationManager(
            sleep_system=self.sleep_system,
            emotion_system=self.emotion_system,
            experience_system=self.experience_system,
            tool_memory_system=self.tool_memory_system
        )
        
        # 验证系统连接
        self.assertEqual(manager.sleep_system, self.sleep_system)
        self.assertEqual(manager.emotion_system, self.emotion_system)
        self.assertEqual(manager.experience_system, self.experience_system)
        self.assertEqual(manager.tool_memory_system, self.tool_memory_system)
        
        # 验证初始状态
        self.assertEqual(manager.get_system_status()['sleep']['status'], 'active')
        self.assertEqual(manager.get_system_status()['emotion']['status'], 'active')
        self.assertEqual(manager.get_system_status()['experience']['status'], 'active')
        self.assertEqual(manager.get_system_status()['tool_memory']['status'], 'active')
    
    def test_get_optimizable_parameters(self):
        """测试获取可优化参数"""
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
        
        manager = RSIIntegrationManager(
            sleep_system=self.sleep_system,
            emotion_system=self.emotion_system,
            experience_system=self.experience_system,
            tool_memory_system=self.tool_memory_system
        )
        
        parameters = manager.get_optimizable_parameters()
        
        # 验证返回格式
        self.assertIn('sleep', parameters)
        self.assertIn('emotion', parameters)
        self.assertIn('experience', parameters)
        self.assertIn('tool_memory', parameters)
        
        # 验证参数数量
        self.assertEqual(len(parameters['sleep']), 3)
        self.assertEqual(len(parameters['emotion']), 2)
        self.assertEqual(len(parameters['experience']), 3)
        self.assertEqual(len(parameters['tool_memory']), 4)
        
        # 验证参数类型
        for system_params in parameters.values():
            for param in system_params:
                self.assertIsInstance(param, ParameterInfo)
    
    def test_collect_feedback_signals(self):
        """测试收集反馈信号"""
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
        
        # 设置模拟系统的反馈信号
        self.sleep_system.get_feedback.return_value = {
            'consolidation_rate': 0.85,
            'memory_count': 1000
        }
        self.emotion_system.get_feedback.return_value = {
            'protection_rate': 0.92,
            'emotional_memories': 500
        }
        self.experience_system.get_feedback.return_value = {
            'crystallization_rate': 0.78,
            'pattern_count': 200
        }
        self.tool_memory_system.get_feedback.return_value = {
            'success_rate': 0.88,
            'tool_count': 50
        }
        
        manager = RSIIntegrationManager(
            sleep_system=self.sleep_system,
            emotion_system=self.emotion_system,
            experience_system=self.experience_system,
            tool_memory_system=self.tool_memory_system
        )
        
        signals = manager.collect_feedback_signals()
        
        # 验证返回格式
        self.assertIn('sleep', signals)
        self.assertIn('emotion', signals)
        self.assertIn('experience', signals)
        self.assertIn('tool_memory', signals)
        
        # 验证信号内容
        self.assertEqual(signals['sleep']['consolidation_rate'], 0.85)
        self.assertEqual(signals['emotion']['protection_rate'], 0.92)
        self.assertEqual(signals['experience']['crystallization_rate'], 0.78)
        self.assertEqual(signals['tool_memory']['success_rate'], 0.88)
    
    def test_apply_optimization(self):
        """测试应用优化"""
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
        
        manager = RSIIntegrationManager(
            sleep_system=self.sleep_system,
            emotion_system=self.emotion_system,
            experience_system=self.experience_system,
            tool_memory_system=self.tool_memory_system
        )
        
        # 测试有效优化
        result = manager.apply_optimization('sleep.base_decay_rate', 0.15)
        self.assertTrue(result)
        self.assertEqual(self.sleep_system.base_decay_rate, 0.15)
        
        # 测试无效参数路径
        result = manager.apply_optimization('invalid.parameter', 0.5)
        self.assertFalse(result)
        
        # 测试无效系统名
        result = manager.apply_optimization('unknown.base_decay_rate', 0.2)
        self.assertFalse(result)
    
    def test_get_system_status(self):
        """测试获取系统状态"""
        from neurova.evolution.rsi.integration_manager import RSIIntegrationManager
        
        # 设置模拟系统的状态
        self.sleep_system.get_status.return_value = {
            'memory_count': 1000,
            'last_consolidation': '2026-06-08T06:00:00'
        }
        self.emotion_system.get_status.return_value = {
            'emotional_memories': 500,
            'last_analysis': '2026-06-08T06:05:00'
        }
        self.experience_system.get_status.return_value = {
            'crystallized_patterns': 200,
            'last_crystallization': '2026-06-08T06:10:00'
        }
        self.tool_memory_system.get_status.return_value = {
            'tool_count': 50,
            'last_weight_update': '2026-06-08T06:15:00'
        }
        
        manager = RSIIntegrationManager(
            sleep_system=self.sleep_system,
            emotion_system=self.emotion_system,
            experience_system=self.experience_system,
            tool_memory_system=self.tool_memory_system
        )
        
        status = manager.get_system_status()
        
        # 验证返回格式
        self.assertIn('sleep', status)
        self.assertIn('emotion', status)
        self.assertIn('experience', status)
        self.assertIn('tool_memory', status)
        
        # 验证状态信息
        self.assertEqual(status['sleep']['memory_count'], 1000)
        self.assertEqual(status['emotion']['emotional_memories'], 500)
        self.assertEqual(status['experience']['crystallized_patterns'], 200)
        self.assertEqual(status['tool_memory']['tool_count'], 50)


if __name__ == '__main__':
    unittest.main()