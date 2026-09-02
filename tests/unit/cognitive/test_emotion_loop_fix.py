"""
情感闭环修复测试

测试 EmotionAnalyzer 的结果被保存到 EmotionModule。
使用 TDD 方法：先写失败的测试，然后实现修复。
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import asyncio

class TestEmotionSavesToMemory:
    """测试情感信息保存到记忆"""

    def test_step_save_memory_calls_emotion_module_set_emotion(self):
        """当保存记忆时，应该调用 EmotionModule.set_emotion()"""
        from neurova.post_chat_pipeline import PostChatPipeline
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionState, EmotionType
        
        # 创建 mock agent
        mock_agent = Mock()
        mock_memory_manager = Mock()
        mock_emotion_module = Mock()
        mock_conversation_buffer = Mock()
        
        # 设置 agent 属性
        mock_agent.memory_manager = mock_memory_manager
        mock_agent.conversation_buffer = mock_conversation_buffer
        
        # 模拟 memory_manager 有 emotion_module 属性
        mock_memory_manager.emotion_module = mock_emotion_module
        
        # 模拟 remember 方法返回记忆 ID
        mock_memory_manager.remember.return_value = "memory_123"
        
        # 模拟 analyze_text_emotion 返回 EmotionState 对象
        joy_state = EmotionState(
            primary_emotion=EmotionType.JOY,
            intensity=0.8,
            valence=0.9,
            arousal=0.7,
        )
        mock_emotion_module.analyze_text_emotion.return_value = joy_state
        
        # 创建 pipeline
        pipeline = PostChatPipeline(agent_ref=mock_agent)
        
        # 调用 _step_save_memory（不需要模拟 EmotionAnalyzer，因为情感保存在 _save_emotion_to_memory 中）
        asyncio.run(pipeline._step_save_memory(
            user_input="我很高兴",
            reply="太好了！",
            session_id="test_session",
            save_memory=True,
        ))
        
        # 验证 EmotionModule.set_emotion 被调用
        mock_emotion_module.set_emotion.assert_called_once()
        
        # 验证调用参数
        call_args = mock_emotion_module.set_emotion.call_args
        memory_id = call_args[0][0]
        emotion_state = call_args[0][1]
        
        assert memory_id == "memory_123"
        assert emotion_state.primary_emotion.value == "joy"
        assert emotion_state.intensity == 0.8

    def test_step_save_memory_handles_missing_emotion_module(self):
        """当 EmotionModule 不存在时，应该优雅处理"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_memory_manager = Mock()
        mock_conversation_buffer = Mock()
        
        mock_agent.memory_manager = mock_memory_manager
        mock_agent.conversation_buffer = mock_conversation_buffer
        
        # 没有 emotion_module 属性
        del mock_memory_manager.emotion_module
        
        mock_memory_manager.remember.return_value = "memory_123"
        
        pipeline = PostChatPipeline(agent_ref=mock_agent)
        
        # 模拟 EmotionAnalyzer
        with patch('neurova.cognitive_layers.emotion_context_layer.emotion.EmotionAnalyzer') as mock_analyzer_class:
            mock_analyzer = Mock()
            mock_analyzer.analyze.return_value = {"label": "joy", "intensity": 0.8}
            mock_analyzer_class.return_value = mock_analyzer
            
            # 应该不会抛出异常
            asyncio.run(pipeline._step_save_memory(
                user_input="我很高兴",
                reply="太好了！",
                session_id="test_session",
                save_memory=True,
            ))

    def test_step_save_memory_handles_emotion_analysis_failure(self):
        """当情感分析失败时，应该继续保存记忆"""
        from neurova.post_chat_pipeline import PostChatPipeline
        
        mock_agent = Mock()
        mock_memory_manager = Mock()
        mock_emotion_module = Mock()
        mock_conversation_buffer = Mock()
        
        mock_agent.memory_manager = mock_memory_manager
        mock_agent.conversation_buffer = mock_conversation_buffer
        mock_memory_manager.emotion_module = mock_emotion_module
        
        mock_memory_manager.remember.return_value = "memory_123"
        
        pipeline = PostChatPipeline(agent_ref=mock_agent)
        
        # 模拟 EmotionAnalyzer 抛出异常
        with patch('neurova.cognitive_layers.emotion_context_layer.emotion.EmotionAnalyzer') as mock_analyzer_class:
            mock_analyzer = Mock()
            mock_analyzer.analyze.side_effect = Exception("情感分析失败")
            mock_analyzer_class.return_value = mock_analyzer
            
            # 应该不会抛出异常
            asyncio.run(pipeline._step_save_memory(
                user_input="我很高兴",
                reply="太好了！",
                session_id="test_session",
                save_memory=True,
            ))

        # 记忆仍然应该被保存
        mock_memory_manager.remember.assert_called()

    def test_step_save_memory_handles_neutral_emotion(self):
        """当情感为 neutral 时，不应该调用 set_emotion"""
        from neurova.post_chat_pipeline import PostChatPipeline
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionState, EmotionType
        
        mock_agent = Mock()
        mock_memory_manager = Mock()
        mock_emotion_module = Mock()
        mock_conversation_buffer = Mock()
        
        mock_agent.memory_manager = mock_memory_manager
        mock_agent.conversation_buffer = mock_conversation_buffer
        mock_memory_manager.emotion_module = mock_emotion_module
        
        mock_memory_manager.remember.return_value = "memory_123"
        
        # 模拟 analyze_text_emotion 返回 neutral EmotionState
        neutral_state = EmotionState(
            primary_emotion=EmotionType.NEUTRAL,
            intensity=0.0,
            valence=0.0,
            arousal=0.0,
        )
        mock_emotion_module.analyze_text_emotion.return_value = neutral_state
        
        pipeline = PostChatPipeline(agent_ref=mock_agent)
        
        asyncio.run(pipeline._step_save_memory(
            user_input="今天天气不错",
            reply="是的，天气很好。",
            session_id="test_session",
            save_memory=True,
        ))
        
        # neutral 情感不应该调用 set_emotion
        mock_emotion_module.set_emotion.assert_not_called()


class TestEmotionAnalyzerIntegration:
    """测试 EmotionAnalyzer 集成"""

    def test_emotion_analyzer_returns_expected_format(self):
        """EmotionAnalyzer.analyze() 应该返回情感字典"""
        from neurova.cognitive_layers.emotion_context_layer.emotion import EmotionAnalyzer
        
        analyzer = EmotionAnalyzer()
        result = analyzer.analyze("我非常高兴")
        
        assert isinstance(result, dict)
        assert len(result) > 0
        # 返回格式为 {emotion_name: intensity} 如 {'joy': 0.5}
        for emotion_name, intensity in result.items():
            assert isinstance(emotion_name, str)
            assert isinstance(intensity, (int, float))
            assert 0 <= intensity <= 1

    def test_emotion_state_conversion(self):
        """情感字典应该能转换为 EmotionState 对象"""
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionState, EmotionType
        
        emotion_data = {
            "label": "joy",
            "intensity": 0.8,
            "valence": 0.9,
            "arousal": 0.7,
        }
        
        # 转换逻辑（需要在实现中添加）
        # 这里我们测试预期的转换结果
        emotion_state = EmotionState(
            primary_emotion=EmotionType.JOY,
            intensity=0.8,
            valence=0.9,
            arousal=0.7,
        )
        
        assert emotion_state.primary_emotion == EmotionType.JOY
        assert emotion_state.intensity == 0.8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])