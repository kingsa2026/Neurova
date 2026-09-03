"""
RSI Agent 集成测试

验证 RSI 系统正确集成到 Agent 中：
1. Agent 初始化 RSI 编排器
2. PostChatPipeline 触发 RSI 迭代
3. 四大闭环系统正确连接到 RSI
"""

import unittest
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock
from typing import Dict, Any

import asyncio


class TestRSIAgentIntegration(unittest.TestCase):
    """测试 RSI 与 Agent 的集成"""
    
    def test_rsi_orchestrator_initialized_in_agent(self):
        """Agent 应该初始化 RSI 编排器"""
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator
        
        # 创建模拟系统
        sleep_system = MagicMock()
        sleep_system.get_feedback.return_value = {'consolidation_count': 0, 'merge_rate': 0.0, 'avg_temperature': 50.0}
        
        emotion_system = MagicMock()
        emotion_system.get_feedback.return_value = {'emotional_memories': 0, 'avg_intensity': 0.0, 'protection_triggered': 0}
        
        experience_system = MagicMock()
        experience_system.get_feedback.return_value = {'crystallized_patterns': 0, 'success_rate': 0.0, 'total_experiences': 0}
        
        tool_memory_system = MagicMock()
        tool_memory_system.get_feedback.return_value = {'total_usages': 0, 'success_rate': 0.0, 'muscle_memory_hits': 0}
        
        # 创建编排器
        orchestrator = RSIOrchestrator(
            sleep_system=sleep_system,
            emotion_system=emotion_system,
            experience_system=experience_system,
            tool_memory_system=tool_memory_system,
        )
        
        # 验证子组件初始化
        self.assertIsNotNone(orchestrator.integration_manager)
        self.assertIsNotNone(orchestrator.convergence_analyzer)
        self.assertIsNotNone(orchestrator.metrics)
        self.assertIsNotNone(orchestrator.rollback_manager)
        self.assertIsNotNone(orchestrator.deployment_controller)
    
    def test_rsi_orchestrator_with_real_systems(self):
        """RSI 编排器应该能与真实闭环系统协作"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
        from neurova.evolution.experience_feedback import ExperienceFeedback
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator
        
        # 创建真实系统
        sleep = SleepConsolidation()
        emotion = EmotionModule()
        experience = ExperienceFeedback()
        tool_memory = ToolMemoryIntegration()
        
        # 创建编排器
        orchestrator = RSIOrchestrator(
            sleep_system=sleep,
            emotion_system=emotion,
            experience_system=experience,
            tool_memory_system=tool_memory,
        )
        
        # 运行迭代
        result = orchestrator.run_iteration()
        
        # 验证结果结构
        self.assertIn('feedback_signals', result)
        self.assertIn('convergence', result)
        self.assertIn('optimizations', result)
        self.assertIn('metrics', result)
        
        # 验证反馈信号不是空的
        self.assertIn('sleep', result['feedback_signals'])
        self.assertIn('emotion', result['feedback_signals'])
        self.assertIn('experience', result['feedback_signals'])
        self.assertIn('tool_memory', result['feedback_signals'])
    
    def test_null_system_fallback(self):
        """当闭环系统不可用时，_NullSystem 应该作为 fallback"""
        from neurova.agent_core import _NullSystem
        
        null_system = _NullSystem()
        feedback = null_system.get_feedback()

        # P0-A2 升级：中性默认反馈，让 RSI 在缺系统时仍能保守运行
        self.assertIsInstance(feedback, dict)
        self.assertEqual(feedback.get("performance_score"), 0.5)
        self.assertEqual(feedback.get("status"), "null_fallback")
    
    def test_rsi_orchestrator_with_null_systems(self):
        """RSI 编排器应该能处理 _NullSystem"""
        from neurova.agent_core import _NullSystem
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator
        
        orchestrator = RSIOrchestrator(
            sleep_system=_NullSystem(),
            emotion_system=_NullSystem(),
            experience_system=_NullSystem(),
            tool_memory_system=_NullSystem(),
        )
        
        # 迭代应该成功完成（无崩溃）
        result = orchestrator.run_iteration()
        self.assertIn('feedback_signals', result)
    
    def test_rsi_should_continue_initially(self):
        """RSI 初始状态应该继续迭代"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
        from neurova.evolution.experience_feedback import ExperienceFeedback
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator
        
        orchestrator = RSIOrchestrator(
            sleep_system=SleepConsolidation(),
            emotion_system=EmotionModule(),
            experience_system=ExperienceFeedback(),
            tool_memory_system=ToolMemoryIntegration(),
        )
        
        self.assertTrue(orchestrator.should_continue())
    
    def test_rsi_get_status(self):
        """RSI 状态应该包含所有必要字段"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
        from neurova.evolution.experience_feedback import ExperienceFeedback
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator
        
        orchestrator = RSIOrchestrator(
            sleep_system=SleepConsolidation(),
            emotion_system=EmotionModule(),
            experience_system=ExperienceFeedback(),
            tool_memory_system=ToolMemoryIntegration(),
        )
        
        status = orchestrator.get_status()
        
        self.assertIn('iteration_count', status)
        self.assertIn('convergence_status', status)
        self.assertIn('deployment_phase', status)
        self.assertIn('metrics', status)
        
        # 初始状态
        self.assertEqual(status['iteration_count'], 0)
        self.assertEqual(status['deployment_phase'], 0)  # Phase 0: 观察阶段
    
    def test_rsi_multiple_iterations(self):
        """多次迭代应该增加迭代计数"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
        from neurova.evolution.experience_feedback import ExperienceFeedback
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator
        
        orchestrator = RSIOrchestrator(
            sleep_system=SleepConsolidation(),
            emotion_system=EmotionModule(),
            experience_system=ExperienceFeedback(),
            tool_memory_system=ToolMemoryIntegration(),
        )
        
        for _ in range(3):
            orchestrator.run_iteration()
        
        status = orchestrator.get_status()
        self.assertEqual(status['iteration_count'], 3)


class TestPostChatPipelineRSI(unittest.TestCase):
    """测试 PostChatPipeline 中的 RSI 迭代"""
    
    def test_step_rsi_iteration_no_orchestrator(self):
        """没有 RSI 编排器时应该返回 None"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        agent = MagicMock()
        agent.rsi_orchestrator = None
        
        pipeline = PostChatPipeline(agent)
        
        result = asyncio.run(pipeline._step_rsi_iteration())
        
        self.assertIsNone(result)
    
    def test_step_rsi_iteration_with_orchestrator(self):
        """有 RSI 编排器时应该执行迭代"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        agent = MagicMock()
        mock_orchestrator = MagicMock()
        mock_orchestrator.should_continue.return_value = True
        mock_orchestrator.run_iteration.return_value = {
            'feedback_signals': {},
            'convergence': {'status': 'insufficient_data'},
            'optimizations': [],
            'metrics': {},
        }
        agent.rsi_orchestrator = mock_orchestrator
        
        pipeline = PostChatPipeline(agent)
        
        result = asyncio.run(pipeline._step_rsi_iteration())
        
        self.assertIsNotNone(result)
        mock_orchestrator.should_continue.assert_called_once()
        mock_orchestrator.run_iteration.assert_called_once()
    
    def test_step_rsi_iteration_should_not_continue(self):
        """RSI 不应该继续时不应该执行迭代"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        agent = MagicMock()
        mock_orchestrator = MagicMock()
        mock_orchestrator.should_continue.return_value = False
        agent.rsi_orchestrator = mock_orchestrator
        
        pipeline = PostChatPipeline(agent)
        
        result = asyncio.run(pipeline._step_rsi_iteration())
        
        self.assertIsNone(result)
        mock_orchestrator.should_continue.assert_called_once()
        mock_orchestrator.run_iteration.assert_not_called()


class TestRSIOptimizableParameters(unittest.TestCase):
    """测试 RSI 可优化参数在各系统中存在"""
    
    def test_sleep_system_has_rsi_params(self):
        """SleepConsolidation 应该有 RSI 可优化参数"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        sleep = SleepConsolidation(decay_rate=0.1, similarity_threshold=0.7)
        
        self.assertEqual(sleep.base_decay_rate, 0.1)
        self.assertEqual(sleep.similarity_threshold, 0.7)
        self.assertEqual(sleep.merge_threshold, 0.7)
    
    def test_emotion_system_has_rsi_params(self):
        """EmotionModule 应该有 RSI 可优化参数"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
        
        emotion = EmotionModule()
        
        self.assertEqual(emotion.emotional_protection_threshold, 0.5)
        self.assertEqual(emotion.emotional_protection_factor, 0.3)
    
    def test_experience_system_has_rsi_params(self):
        """ExperienceFeedback 应该有 RSI 可优化参数"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        exp = ExperienceFeedback()
        
        self.assertEqual(exp.crystallize_min_observations, 3)
        self.assertEqual(exp.crystallize_min_success_rate, 0.6)
        self.assertEqual(exp.pattern_min_support, 0.3)
    
    def test_tool_memory_system_has_rsi_params(self):
        """ToolMemoryIntegration 应该有 RSI 可优化参数"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        
        tmi = ToolMemoryIntegration()
        
        self.assertEqual(tmi.success_bonus, 0.1)
        self.assertEqual(tmi.failure_penalty, 0.05)
        self.assertEqual(tmi.decay_rate, 0.01)
        self.assertEqual(tmi.muscle_memory_threshold, 0.8)


if __name__ == '__main__':
    unittest.main()