"""
闭环反馈接口测试

验证四大闭环系统（睡眠、情感、经验、工具记忆）实现 get_feedback() 接口，
为 RSI 系统提供反馈信号。
"""

import unittest
from unittest.mock import MagicMock, patch
from typing import Dict, Any


class TestSleepFeedback(unittest.TestCase):
    """测试睡眠整合模块的 get_feedback 接口"""
    
    def test_get_feedback_returns_dict(self):
        """get_feedback 应该返回字典"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        sleep = SleepConsolidation()
        feedback = sleep.get_feedback()
        
        self.assertIsInstance(feedback, dict)
    
    def test_get_feedback_contains_required_keys(self):
        """get_feedback 应该包含 RSI 需要的键"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
        
        sleep = SleepConsolidation()
        feedback = sleep.get_feedback()
        
        self.assertIn('consolidation_count', feedback)
        self.assertIn('merge_rate', feedback)
        self.assertIn('avg_temperature', feedback)
    
    def test_get_feedback_after_consolidation(self):
        """整合后 get_feedback 应该返回更新的数据"""
        from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation, MemoryRecord
        
        sleep = SleepConsolidation()
        
        # 创建测试记忆
        memories = [
            MemoryRecord(id=f"m{i}", content=f"content {i}", temperature=50.0)
            for i in range(5)
        ]
        
        # 执行整合
        sleep.consolidate(memories)
        
        feedback = sleep.get_feedback()
        
        self.assertGreater(feedback['consolidation_count'], 0)
        self.assertIsInstance(feedback['merge_rate'], float)
        self.assertIsInstance(feedback['avg_temperature'], float)


class TestEmotionFeedback(unittest.TestCase):
    """测试情感模块的 get_feedback 接口"""
    
    def test_get_feedback_returns_dict(self):
        """get_feedback 应该返回字典"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
        
        emotion = EmotionModule()
        feedback = emotion.get_feedback()
        
        self.assertIsInstance(feedback, dict)
    
    def test_get_feedback_contains_required_keys(self):
        """get_feedback 应该包含 RSI 需要的键"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
        
        emotion = EmotionModule()
        feedback = emotion.get_feedback()
        
        self.assertIn('emotional_memories', feedback)
        self.assertIn('avg_intensity', feedback)
        self.assertIn('protection_triggered', feedback)
    
    def test_get_feedback_with_emotions(self):
        """有情感数据时 get_feedback 应该返回正确统计"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import (
            EmotionModule, EmotionType, EmotionState
        )
        
        emotion = EmotionModule()
        
        # 添加情感标注
        for i in range(5):
            state = EmotionState(
                primary_emotion=EmotionType.JOY,
                intensity=0.7,
                valence=0.8,
                arousal=0.6,
            )
            emotion.set_emotion(f"mem_{i}", state)
        
        feedback = emotion.get_feedback()
        
        self.assertEqual(feedback['emotional_memories'], 5)
        self.assertGreater(feedback['avg_intensity'], 0)


class TestExperienceFeedback(unittest.TestCase):
    """测试经验反哺系统的 get_feedback 接口"""
    
    def test_get_feedback_returns_dict(self):
        """get_feedback 应该返回字典"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        exp = ExperienceFeedback()
        feedback = exp.get_feedback()
        
        self.assertIsInstance(feedback, dict)
    
    def test_get_feedback_contains_required_keys(self):
        """get_feedback 应该包含 RSI 需要的键"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        exp = ExperienceFeedback()
        feedback = exp.get_feedback()
        
        self.assertIn('crystallized_patterns', feedback)
        self.assertIn('success_rate', feedback)
        self.assertIn('total_experiences', feedback)
    
    def test_get_feedback_with_experiences(self):
        """有经验数据时 get_feedback 应该返回正确统计"""
        from neurova.evolution.experience_feedback import ExperienceFeedback
        
        exp = ExperienceFeedback(known_tools=['test_tool', 'search_file'])
        
        # 处理一些经验
        exp.process_experience("使用 test_tool 成功完成任务", "coding")
        exp.process_experience("使用 search_file 搜索失败", "search")
        exp.process_experience("使用 test_tool 成功", "coding")
        
        feedback = exp.get_feedback()
        
        self.assertGreater(feedback['total_experiences'], 0)
        self.assertIsInstance(feedback['success_rate'], float)
        self.assertIsInstance(feedback['crystallized_patterns'], int)


class TestToolMemoryFeedback(unittest.TestCase):
    """测试工具记忆集成的 get_feedback 接口"""
    
    def test_get_feedback_returns_dict(self):
        """get_feedback 应该返回字典"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        
        tmi = ToolMemoryIntegration()
        feedback = tmi.get_feedback()
        
        self.assertIsInstance(feedback, dict)
    
    def test_get_feedback_contains_required_keys(self):
        """get_feedback 应该包含 RSI 需要的键"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        
        tmi = ToolMemoryIntegration()
        feedback = tmi.get_feedback()
        
        self.assertIn('total_usages', feedback)
        self.assertIn('success_rate', feedback)
        self.assertIn('muscle_memory_hits', feedback)
    
    def test_get_feedback_with_usage(self):
        """有使用数据时 get_feedback 应该返回正确统计"""
        from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
        
        tmi = ToolMemoryIntegration()
        
        # 记录工具使用
        tmi.record_tool_usage(tool_name='test_tool', success=True)
        tmi.record_tool_usage(tool_name='test_tool', success=True)
        tmi.record_tool_usage(tool_name='search_file', success=False)
        
        feedback = tmi.get_feedback()
        
        self.assertEqual(feedback['total_usages'], 3)
        self.assertAlmostEqual(feedback['success_rate'], 2/3, places=2)


class TestClosedLoopIntegrationWithRSI(unittest.TestCase):
    """测试四大闭环系统与 RSI 的集成"""
    
    def test_orchestrator_collects_real_feedback(self):
        """RSIOrchestrator 应该能从真实闭环系统收集反馈"""
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
        
        # 收集反馈信号
        signals = orchestrator.collect_feedback_signals()
        
        # 验证收集到了真实数据（不是空字典）
        self.assertIn('sleep', signals)
        self.assertIn('emotion', signals)
        self.assertIn('experience', signals)
        self.assertIn('tool_memory', signals)
        
        # 验证不是错误响应
        self.assertNotIn('error', signals.get('sleep', {}))
        self.assertNotIn('error', signals.get('emotion', {}))
        self.assertNotIn('error', signals.get('experience', {}))
        self.assertNotIn('error', signals.get('tool_memory', {}))


if __name__ == '__main__':
    unittest.main()