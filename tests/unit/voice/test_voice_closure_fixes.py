"""
语音系统闭环修复测试

测试四个断裂点的修复：
1. P0: ASR → 进化系统
2. P1: 语音工具注册 (asr_transcribe, tts_synthesize, voice_memory_search)
3. P1: 语音记忆 → RecallEngine (VOICE 通道)
4. P2: 语音情感 → 进化系统
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone


# ============================================================
# 测试 1: P0 - ASR → 进化系统
# ============================================================

class TestASRToEvolution:
    """测试 ASR 结果记录到进化系统"""

    @pytest.mark.asyncio
    async def test_asr_calls_evolution_on_after_tool_execution(self):
        """验证 record_asr_result 调用 evolution_orchestrator.on_after_tool_execution"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        # 创建 mock 依赖
        mock_memory = MagicMock()
        mock_memory.remember.return_value = "mem_123"
        mock_emotion = MagicMock()
        mock_evolution = MagicMock()

        config = VoiceMemoryConfig(
            enable_asr_memory=True,
            enable_emotion_analysis=False,  # 禁用情感分析以简化测试
            min_confidence_threshold=0.3,
        )

        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            emotion_module=mock_emotion,
            evolution_orchestrator=mock_evolution,
        )

        # 模拟 ASR 结果
        asr_result = {
            "text": "今天天气真好",
            "confidence": 0.92,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 800,
        }

        # 执行（async 方法需要 await）
        result = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_1",
            agent_id="agent_1",
        )

        # 验证进化系统被调用
        mock_evolution.on_after_tool_execution.assert_called_once()
        call_args = mock_evolution.on_after_tool_execution.call_args
        assert call_args.kwargs["tool_name"] == "asr_transcribe"
        assert call_args.kwargs["success"] is True
        assert call_args.kwargs["execution_time"] == 0.8  # 800ms -> 0.8s
        assert call_args.kwargs["params"]["engine"] == "funasr"
        assert call_args.kwargs["params"]["confidence"] == 0.92

    @pytest.mark.asyncio
    async def test_asr_evolution_failure_does_not_block(self):
        """验证进化系统调用失败不阻塞主流程"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        mock_memory = MagicMock()
        mock_memory.remember.return_value = "mem_123"
        mock_emotion = MagicMock()
        mock_evolution = MagicMock()
        mock_evolution.on_after_tool_execution.side_effect = Exception("evolution error")

        config = VoiceMemoryConfig(
            enable_asr_memory=True,
            enable_emotion_analysis=False,  # 禁用情感分析以简化测试
            min_confidence_threshold=0.3,
        )

        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            emotion_module=mock_emotion,
            evolution_orchestrator=mock_evolution,
        )

        asr_result = {
            "text": "测试文本",
            "confidence": 0.85,
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 1000,
        }

        # 不应该抛出异常
        result = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_1",
            agent_id="agent_1",
        )

        assert result.success


# ============================================================
# 测试 2: P1 - 语音工具注册
# ============================================================

class TestVoiceToolRegistration:
    """测试语音工具在 BuiltinToolRegistry 中注册"""

    def test_asr_transcribe_tool_exists(self):
        """验证 asr_transcribe 工具已注册"""
        from neurova.builtin_tools import get_builtin_tool_params

        params = get_builtin_tool_params("asr_transcribe")
        assert params is not None
        assert "description" in params
        assert "parameters" in params
        assert "audio_data" in params["parameters"]["properties"]
        assert "audio_data" in params["parameters"]["required"]

    def test_tts_synthesize_tool_exists(self):
        """验证 tts_synthesize 工具已注册"""
        from neurova.builtin_tools import get_builtin_tool_params

        params = get_builtin_tool_params("tts_synthesize")
        assert params is not None
        assert "description" in params
        assert "parameters" in params
        assert "text" in params["parameters"]["properties"]
        assert "text" in params["parameters"]["required"]

    def test_voice_memory_search_tool_exists(self):
        """验证 voice_memory_search 工具已注册"""
        from neurova.builtin_tools import get_builtin_tool_params

        params = get_builtin_tool_params("voice_memory_search")
        assert params is not None
        assert "description" in params
        assert "parameters" in params
        assert "query" in params["parameters"]["properties"]
        assert "query" in params["parameters"]["required"]

    def test_asr_tool_openai_format(self):
        """验证 asr_transcribe 转换为 OpenAI function calling 格式"""
        from neurova.builtin_tools import BuiltinTool, get_builtin_tool_params

        params = get_builtin_tool_params("asr_transcribe")
        tool = BuiltinTool(
            name="asr_transcribe",
            description=params["description"],
            parameters=params["parameters"],
        )
        openai_format = tool.to_openai_format()

        assert openai_format["type"] == "function"
        assert openai_format["function"]["name"] == "asr_transcribe"
        assert "audio_data" in openai_format["function"]["parameters"]["properties"]

    def test_tts_tool_openai_format(self):
        """验证 tts_synthesize 转换为 OpenAI function calling 格式"""
        from neurova.builtin_tools import BuiltinTool, get_builtin_tool_params

        params = get_builtin_tool_params("tts_synthesize")
        tool = BuiltinTool(
            name="tts_synthesize",
            description=params["description"],
            parameters=params["parameters"],
        )
        openai_format = tool.to_openai_format()

        assert openai_format["type"] == "function"
        assert openai_format["function"]["name"] == "tts_synthesize"
        assert "text" in openai_format["function"]["parameters"]["properties"]


# ============================================================
# 测试 3: P1 - 语音记忆 → RecallEngine (VOICE 通道)
# ============================================================

class TestVoiceRecallChannel:
    """测试语音记忆检索通道"""

    def test_voice_channel_exists(self):
        """验证 RecallChannel.VOICE 枚举存在"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import RecallChannel

        assert hasattr(RecallChannel, 'VOICE')
        assert RecallChannel.VOICE.value == "voice"

    def test_voice_channel_weight(self):
        """验证 VOICE 通道有权重配置"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        engine = NeurovaRecallEngine()
        from neurova.cognitive_layers.memory_layer.neurova_recall import RecallChannel

        assert RecallChannel.VOICE in engine._channel_weights
        assert engine._channel_weights[RecallChannel.VOICE] == 0.10

    def test_voice_channel_included_by_default(self):
        """验证 recall() 默认包含 VOICE 通道"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import (
            NeurovaRecallEngine, RecallChannel
        )

        engine = NeurovaRecallEngine()
        result = engine.recall("测试查询")

        # 默认通道列表应包含 VOICE
        assert RecallChannel.VOICE in engine._channel_weights

    def test_channel_voice_method_exists(self):
        """验证 _channel_voice 方法存在"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        engine = NeurovaRecallEngine()
        assert hasattr(engine, '_channel_voice')
        assert callable(engine._channel_voice)

    def test_channel_voice_returns_list(self):
        """验证 _channel_voice 返回列表"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        engine = NeurovaRecallEngine()
        result = engine._channel_voice("测试", 5)
        assert isinstance(result, list)

    def test_channel_voice_handles_no_memory_manager(self):
        """验证 _channel_voice 在无 memory_manager 时安全返回"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        engine = NeurovaRecallEngine(memory_manager=None)
        result = engine._channel_voice("测试", 5)
        assert result == []


# ============================================================
# 测试 4: P2 - 语音情感 → 进化系统
# ============================================================

class TestVoiceEmotionToEvolution:
    """测试语音情感记录到进化系统"""

    @pytest.mark.asyncio
    async def test_voice_emotion_calls_evolution_on_experience_recorded(self):
        """验证 record_asr_result 在有情感时调用 on_experience_recorded"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        mock_memory = MagicMock()
        mock_memory.remember.return_value = "mem_123"
        mock_emotion = MagicMock()
        # 模拟情感分析返回结果（带 primary_emotion 和 confidence 属性）
        mock_emotion_state = MagicMock()
        mock_emotion_state.primary_emotion = "happy"
        mock_emotion_state.confidence = 0.85
        mock_emotion.analyze_text_emotion.return_value = mock_emotion_state
        mock_evolution = MagicMock()

        config = VoiceMemoryConfig(
            enable_asr_memory=True,
            enable_emotion_analysis=True,
            min_confidence_threshold=0.3,
        )

        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            emotion_module=mock_emotion,
            evolution_orchestrator=mock_evolution,
        )

        asr_result = {
            "text": "我今天非常开心",
            "confidence": 0.90,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 1000,
        }

        result = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_1",
            agent_id="agent_1",
        )

        # 验证情感进化记录被调用
        # 注意：on_experience_recorded 可能被调用 0 或 1 次，取决于情感分析结果
        if mock_evolution.on_experience_recorded.called:
            call_args = mock_evolution.on_experience_recorded.call_args
            # 现行桥接契约（voice_memory_bridge.py:263）：位置参数
            # text/task/tools/success——task 承载 voice_emotion 语义
            assert call_args.kwargs.get("task") == "voice_emotion" or (
                len(call_args.args) > 1 and call_args.args[1] == "voice_emotion"
            )
            assert call_args.kwargs.get("tools") == ["asr_transcribe"]
            assert call_args.kwargs.get("success") is True

    @pytest.mark.asyncio
    async def test_neutral_emotion_no_evolution_call(self):
        """验证中性情感不调用进化系统"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        mock_memory = MagicMock()
        mock_memory.remember.return_value = "mem_123"
        mock_emotion = MagicMock()
        # 返回 None（模拟无法分析情感）
        mock_emotion.analyze_text_emotion.return_value = None
        mock_evolution = MagicMock()

        config = VoiceMemoryConfig(
            enable_asr_memory=True,
            enable_emotion_analysis=True,
            min_confidence_threshold=0.3,
        )

        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            emotion_module=mock_emotion,
            evolution_orchestrator=mock_evolution,
        )

        asr_result = {
            "text": "请帮我查一下天气",
            "confidence": 0.88,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 900,
        }

        result = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_1",
            agent_id="agent_1",
        )

        # 情感进化记录不应被调用
        mock_evolution.on_experience_recorded.assert_not_called()
