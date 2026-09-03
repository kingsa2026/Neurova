"""
RSI 编排器测试

测试 RSI 迭代的协调、自动优化、定时任务
"""

import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, List, Any
import asyncio

from neurova.evolution.rsi.orchestrator import RSIOrchestrator


class TestRSIOrchestrator(unittest.TestCase):
    """测试 RSI 编排器"""
    
    def setUp(self):
        """测试前准备"""
        # 创建模拟的四大闭环系统
        self.sleep_system = MagicMock()
        self.sleep_system.get_feedback.return_value = {
            'consolidation_count': 10,
            'merge_rate': 0.3,
            'avg_temperature': 45.0,
        }
        self.sleep_system.base_decay_rate = 0.1
        self.sleep_system.similarity_threshold = 0.7
        
        self.emotion_system = MagicMock()
        self.emotion_system.get_feedback.return_value = {
            'emotional_memories': 25,
            'avg_intensity': 0.6,
            'protection_triggered': 3,
        }
        self.emotion_system.emotional_protection_threshold = 0.5
        
        self.experience_system = MagicMock()
        self.experience_system.get_feedback.return_value = {
            'crystallized_patterns': 8,
            'success_rate': 0.75,
            'total_experiences': 50,
        }
        self.experience_system.crystallize_min_observations = 3
        
        self.tool_memory_system = MagicMock()
        self.tool_memory_system.get_feedback.return_value = {
            'total_usages': 100,
            'success_rate': 0.85,
            'muscle_memory_hits': 30,
        }
        self.tool_memory_system.success_bonus = 0.1
        
        # 创建编排器
        self.orchestrator = RSIOrchestrator(
            sleep_system=self.sleep_system,
            emotion_system=self.emotion_system,
            experience_system=self.experience_system,
            tool_memory_system=self.tool_memory_system,
        )
    
    def test_initialization(self):
        """测试初始化"""
        self.assertIsNotNone(self.orchestrator.integration_manager)
        self.assertIsNotNone(self.orchestrator.convergence_analyzer)
        self.assertIsNotNone(self.orchestrator.metrics)
        self.assertIsNotNone(self.orchestrator.rollback_manager)
        self.assertIsNotNone(self.orchestrator.deployment_controller)
    
    def test_run_iteration(self):
        """测试运行一次RSI迭代"""
        # 运行迭代
        result = self.orchestrator.run_iteration()
        
        # 验证结果
        self.assertIn('feedback_signals', result)
        self.assertIn('convergence', result)
        self.assertIn('optimizations', result)
        self.assertIn('metrics', result)
        
        # 验证反馈信号被收集
        self.assertIn('sleep', result['feedback_signals'])
        self.assertIn('emotion', result['feedback_signals'])
        self.assertIn('experience', result['feedback_signals'])
        self.assertIn('tool_memory', result['feedback_signals'])
    
    def test_collect_feedback_signals(self):
        """测试收集反馈信号"""
        signals = self.orchestrator.collect_feedback_signals()
        
        # 验证四大闭环都返回了反馈
        self.assertIn('sleep', signals)
        self.assertIn('emotion', signals)
        self.assertIn('experience', signals)
        self.assertIn('tool_memory', signals)
        
        # 验证反馈内容
        self.assertEqual(signals['sleep']['consolidation_count'], 10)
        self.assertEqual(signals['emotion']['emotional_memories'], 25)
    
    def test_generate_optimizations(self):
        """测试生成优化建议"""
        # 收集反馈信号
        signals = self.orchestrator.collect_feedback_signals()
        
        # 生成优化建议
        optimizations = self.orchestrator.generate_optimizations(signals)
        
        # 验证优化建议
        self.assertIsInstance(optimizations, list)
    
    def test_apply_optimizations(self):
        """测试应用优化"""
        # 模拟优化建议
        optimizations = [
            {'parameter': 'sleep.base_decay_rate', 'new_value': 0.12},
            {'parameter': 'emotion.emotional_protection_threshold', 'new_value': 0.55},
        ]
        
        # 应用优化
        results = self.orchestrator.apply_optimizations(optimizations)
        
        # 验证应用结果
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]['applied'])
        self.assertTrue(results[1]['applied'])
    
    def test_should_continue(self):
        """测试判断是否应该继续"""
        # 初始状态应该继续
        self.assertTrue(self.orchestrator.should_continue())
    
    def test_get_status(self):
        """测试获取状态"""
        status = self.orchestrator.get_status()
        
        self.assertIn('iteration_count', status)
        self.assertIn('convergence_status', status)
        self.assertIn('deployment_phase', status)
        self.assertIn('metrics', status)


if __name__ == '__main__':
    unittest.main()