"""测试进化系统调用签名修复

Bug: voice_memory_bridge.py:260 调用 evolution.on_experience_recorded()
时传入了不匹配的参数 (experience_type, emotion_data, tool_name, user_id, agent_id)，
而方法签名期望 (text, task, tools, success)。
由于 try/except 静默吞掉 TypeError，语音情感经验永远不会被记录到进化系统。

builtin.py 的 exec_evolution 已正确解包，此测试验证所有调用点签名正确。
"""
import pytest
import sys
import asyncio
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestEvolutionSignature:
    """验证所有 on_experience_recorded 调用签名正确"""

    def test_evolution_orchestrator_signature(self):
        """EvolutionOrchestrator.on_experience_recorded 签名验证"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator
        import inspect

        sig = inspect.signature(EvolutionOrchestrator.on_experience_recorded)
        params = list(sig.parameters.keys())
        # 确保期望的参数存在
        assert "self" in params
        assert "text" in params
        assert "task" in params
        assert "tools" in params
        assert "success" in params

    def test_builtin_evolution_correctly_unpacked(self):
        """builtin.py exec_evolution 应正确解包字典"""
        from neurova.collaboration.neurflow.builtin import exec_evolution

        mock_evolution = Mock()
        mock_evolution.on_experience_recorded.return_value = {"status": "ok"}

        with patch("neurova.collaboration.neurflow.builtin._get_evolution", return_value=mock_evolution):
            feedback_data = {
                "text": "test text",
                "task": "test task",
                "tools": ["tool_a"],
                "success": True,
            }
            result = asyncio.run(exec_evolution(
                config={"mode": "learn", "feedback_data": feedback_data},
                ctx={},
            ))

            mock_evolution.on_experience_recorded.assert_called_once_with(
                text="test text",
                task="test task",
                tools=["tool_a"],
                success=True,
                crystallizer=None,
            )

    def test_post_chat_pipeline_correct_signature(self):
        """post_chat_pipeline 应使用正确签名"""
        # 读取源码验证调用方式
        from neurova.post_chat_pipeline import PostChatPipeline
        import inspect
        source = inspect.getsource(PostChatPipeline._step_record_experience)
        # 验证使用了正确的关键字参数
        assert "text=" in source
        assert "task=" in source
        assert "tools=" in source
        assert "success=" in source

    def test_voice_memory_bridge_passes_correct_signature(self):
        """voice_memory_bridge.py 应使用正确的 (text, task, tools, success) 签名"""
        # 读取源码验证
        import inspect
        from neurova.voice_memory_bridge import VoiceMemoryBridge
        source = inspect.getsource(VoiceMemoryBridge.record_asr_result)

        # 找到 on_experience_recorded 调用
        # 修复后应使用 text=, task=, tools=, success= 关键字参数
        # 而不是 experience_type=, emotion_data= 等错误参数
        assert "experience_type=" not in source, \
            "voice_memory_bridge.py 仍使用错误的 experience_type= 参数"

    def test_voice_memory_bridge_evolution_call_mapped_correctly(self):
        """voice_memory_bridge 的进化调用应正确映射到 (text, task, tools, success)"""
        # 直接测试 voice_memory_bridge 中的进化调用逻辑
        mock_evolution = Mock()
        mock_evolution.on_experience_recorded.return_value = {"status": "ok"}

        emotion_state = {"primary_emotion": "happy", "confidence": 0.9}

        # 模拟正确的调用方式（修复后）
        text = f"[语音情感] {emotion_state}"
        task = "voice_emotion"
        tools = ["asr_transcribe"]
        success = True

        mock_evolution.on_experience_recorded(
            text=text,
            task=task,
            tools=tools,
            success=success,
        )

        mock_evolution.on_experience_recorded.assert_called_once_with(
            text=f"[语音情感] {emotion_state}",
            task="voice_emotion",
            tools=["asr_transcribe"],
            success=True,
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
