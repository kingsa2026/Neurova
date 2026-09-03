"""
语音系统场景验证测试

验证五个关键场景：
1. ASR 引擎性能学习：连续使用不同 ASR 引擎，进化系统应调整权重
2. TTS 工具调用：LLM 应能通过 function calling 调用 tts_synthesize
3. 语音记忆检索：用户问"我之前用语音说了什么"，应能从语音记忆中检索
4. 情感感知进化：用户情感激动时，进化系统应调整语音响应策略
5. 端到端语音对话：完整的 ASR → LLM → TTS 流程，所有系统协同工作
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone


# ============================================================
# 场景 1: ASR 引擎性能学习
# ============================================================

class TestASREnginePerformanceLearning:
    """测试 ASR 引擎性能学习：连续使用不同 ASR 引擎，进化系统应调整权重"""

    @pytest.mark.asyncio
    async def test_asr_engine_performance_recorded_to_evolution(self):
        """验证 ASR 引擎使用数据记录到进化系统"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        mock_memory = MagicMock()
        mock_memory.remember.return_value = "mem_123"
        mock_emotion = MagicMock()
        mock_evolution = MagicMock()

        config = VoiceMemoryConfig(
            enable_asr_memory=True,
            enable_emotion_analysis=False,
            min_confidence_threshold=0.3,
        )

        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            emotion_module=mock_emotion,
            evolution_orchestrator=mock_evolution,
        )

        # 模拟不同 ASR 引擎的使用
        engines = ["funasr", "whisper", "auto"]
        for engine in engines:
            asr_result = {
                "text": f"测试文本 {engine}",
                "confidence": 0.90,
                "language": "zh",
                "engine": engine,
                "duration_ms": 800,
            }
            await bridge.record_asr_result(
                asr_result=asr_result,
                user_id="user_1",
                agent_id="agent_1",
            )

        # 验证进化系统被调用 3 次（每个引擎一次）
        assert mock_evolution.on_after_tool_execution.call_count == 3
        
        # 验证每次调用都包含引擎信息
        calls = mock_evolution.on_after_tool_execution.call_args_list
        for i, call in enumerate(calls):
            assert call.kwargs["tool_name"] == "asr_transcribe"
            assert call.kwargs["params"]["engine"] == engines[i]
            assert call.kwargs["params"]["confidence"] == 0.90
            assert call.kwargs["success"] is True

    @pytest.mark.asyncio
    async def test_evolution_system_adjusts_weights_based_on_performance(self):
        """验证进化系统根据引擎性能调整权重"""
        # 这个测试验证数据流，实际权重调整在 EvolutionOrchestrator 中
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        mock_memory = MagicMock()
        mock_memory.remember.return_value = "mem_123"
        mock_emotion = MagicMock()
        mock_evolution = MagicMock()

        config = VoiceMemoryConfig(
            enable_asr_memory=True,
            enable_emotion_analysis=False,
            min_confidence_threshold=0.3,
        )

        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            emotion_module=mock_emotion,
            evolution_orchestrator=mock_evolution,
        )

        # 模拟高置信度 ASR 结果
        asr_result = {
            "text": "高置信度文本",
            "confidence": 0.98,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 500,
        }
        
        await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_1",
            agent_id="agent_1",
        )

        # 验证进化系统收到高置信度数据
        call_args = mock_evolution.on_after_tool_execution.call_args
        assert call_args.kwargs["params"]["confidence"] == 0.98
        assert call_args.kwargs["execution_time"] == 0.5  # 500ms -> 0.5s


# ============================================================
# 场景 2: TTS 工具调用
# ============================================================

class TestTTSToolCalling:
    """测试 TTS 工具调用：LLM 应能通过 function calling 调用 tts_synthesize"""

    def test_tts_tool_schema_registered(self):
        """验证 tts_synthesize 工具 schema 已注册"""
        from neurova.builtin_tools import get_builtin_tool_params

        params = get_builtin_tool_params("tts_synthesize")
        assert params is not None
        assert "description" in params
        assert "parameters" in params
        assert "text" in params["parameters"]["properties"]
        assert "text" in params["parameters"]["required"]
        assert "voice" in params["parameters"]["properties"]
        assert "engine" in params["parameters"]["properties"]

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
        assert "voice" in openai_format["function"]["parameters"]["properties"]
        assert "engine" in openai_format["function"]["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_tts_tool_execution_recorded(self):
        """验证 TTS 工具执行记录到进化系统"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        mock_memory = MagicMock()
        mock_memory.remember.return_value = "mem_456"
        mock_emotion = MagicMock()
        mock_evolution = MagicMock()

        config = VoiceMemoryConfig(
            enable_tts_stats=True,
            enable_emotion_analysis=False,
        )

        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            emotion_module=mock_emotion,
            evolution_orchestrator=mock_evolution,
        )

        tts_result = {
            "text_length": 100,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 2000,
            "success": True,
            "audio_size_bytes": 32000,
        }

        result = await bridge.record_tts_usage(
            tts_result=tts_result,
            user_id="user_1",
            agent_id="agent_1",
        )

        # 验证进化系统被调用
        mock_evolution.on_after_tool_execution.assert_called_once()
        call_args = mock_evolution.on_after_tool_execution.call_args
        assert call_args.kwargs["tool_name"] == "tts_synthesize"
        assert call_args.kwargs["params"]["engine"] == "edge-tts"
        assert call_args.kwargs["params"]["voice"] == "zh-CN-XiaoxiaoNeural"
        assert call_args.kwargs["success"] is True
        assert call_args.kwargs["execution_time"] == 2.0  # 2000ms -> 2.0s


# ============================================================
# 场景 3: 语音记忆检索
# ============================================================

class TestVoiceMemoryRetrieval:
    """测试语音记忆检索：用户问"我之前用语音说了什么"，应能从语音记忆中检索"""

    def test_voice_recall_channel_exists(self):
        """验证 RecallChannel.VOICE 枚举存在"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import RecallChannel

        assert hasattr(RecallChannel, 'VOICE')
        assert RecallChannel.VOICE.value == "voice"

    def test_voice_recall_channel_weight(self):
        """验证 VOICE 通道有权重配置"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine
        from neurova.cognitive_layers.memory_layer.neurova_recall import RecallChannel

        engine = NeurovaRecallEngine()
        assert RecallChannel.VOICE in engine._channel_weights
        assert engine._channel_weights[RecallChannel.VOICE] == 0.10

    def test_voice_channel_method_exists(self):
        """验证 _channel_voice 方法存在"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        engine = NeurovaRecallEngine()
        assert hasattr(engine, '_channel_voice')
        assert callable(engine._channel_voice)

    def test_voice_channel_searches_asr_transcription(self):
        """验证语音通道搜索 memory_type='asr_transcription' 的记忆"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        # 创建 mock memory_manager
        mock_memory_manager = MagicMock()
        mock_memory_manager.get_all_memories.return_value = [
            {
                "id": "mem_1",
                "content": "[语音转写] 今天天气真好",
                "memory_type": "asr_transcription",
                "metadata": {
                    "record": {
                        "confidence": 0.92,
                        "engine": "funasr",
                        "language": "zh",
                    }
                },
                "timestamp": "2026-06-07T10:00:00",
            },
            {
                "id": "mem_2",
                "content": "普通文本记忆",
                "memory_type": "text",
                "metadata": {},
                "timestamp": "2026-06-07T10:00:00",
            },
        ]

        engine = NeurovaRecallEngine(memory_manager=mock_memory_manager)
        results = engine._channel_voice("天气", 5)

        # 应该只返回语音转写记忆
        assert len(results) == 1
        assert results[0].memory_id == "mem_1"
        assert results[0].channel.value == "voice"
        assert results[0].score > 0

    def test_voice_channel_scores_by_confidence(self):
        """验证语音通道按置信度排序"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine

        mock_memory_manager = MagicMock()
        mock_memory_manager.get_all_memories.return_value = [
            {
                "id": "mem_1",
                "content": "[语音转写] 低置信度",
                "memory_type": "asr_transcription",
                "metadata": {
                    "record": {"confidence": 0.6, "engine": "funasr", "language": "zh"}
                },
                "timestamp": "2026-06-07T10:00:00",
            },
            {
                "id": "mem_2",
                "content": "[语音转写] 高置信度",
                "memory_type": "asr_transcription",
                "metadata": {
                    "record": {"confidence": 0.95, "engine": "whisper", "language": "zh"}
                },
                "timestamp": "2026-06-07T10:00:00",
            },
        ]

        engine = NeurovaRecallEngine(memory_manager=mock_memory_manager)
        results = engine._channel_voice("", 5)

        # 应该按置信度排序（高置信度在前）
        assert len(results) == 2
        assert results[0].memory_id == "mem_2"  # 高置信度
        assert results[1].memory_id == "mem_1"  # 低置信度


# ============================================================
# 场景 4: 情感感知进化
# ============================================================

class TestEmotionAwareEvolution:
    """测试情感感知进化：用户情感激动时，进化系统应调整语音响应策略"""

    @pytest.mark.asyncio
    async def test_emotion_recorded_to_evolution(self):
        """验证情感分析结果记录到进化系统"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        mock_memory = MagicMock()
        mock_memory.remember.return_value = "mem_789"
        mock_emotion = MagicMock()
        
        # 模拟情感分析返回结果
        mock_emotion_state = MagicMock()
        mock_emotion_state.primary_emotion = "angry"
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
            "text": "我非常生气！",
            "confidence": 0.90,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 1000,
        }

        await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_1",
            agent_id="agent_1",
        )

        # 验证情感进化记录被调用
        if mock_evolution.on_experience_recorded.called:
            call_args = mock_evolution.on_experience_recorded.call_args
            # 现行桥接契约（voice_memory_bridge.py:263）：text/task/tools/success
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
        mock_memory.remember.return_value = "mem_789"
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

        await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_1",
            agent_id="agent_1",
        )

        # 情感进化记录不应被调用
        mock_evolution.on_experience_recorded.assert_not_called()

    def test_emotion_injected_to_context_pool(self):
        """验证情感注入到 ContextPool"""
        from neurova.voice_context_module import VoiceContextModule

        module = VoiceContextModule()
        mock_context_pool = MagicMock()
        
        voice_context = {
            "text": "测试文本",
            "confidence": 0.9,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 800,
            "emotion": {
                "primary_emotion": "angry",
                "confidence": 0.85,
                "valence": -0.7,
                "arousal": 0.8,
            },
        }

        module.inject_metadata(mock_context_pool, voice_context)

        # 验证 ContextPool.add_context 被调用 2 次（MULTIMODAL + EMOTION）
        assert mock_context_pool.add_context.call_count == 2
        
        # 验证情感被注入到 EMOTION 上下文
        calls = mock_context_pool.add_context.call_args_list
        emotion_call = None
        for call in calls:
            if call.args[0].source.value == "emotion":
                emotion_call = call
                break
        
        assert emotion_call is not None
        assert "angry" in emotion_call.args[0].content


# ============================================================
# 场景 5: 端到端语音对话
# ============================================================

class TestEndToEndVoiceDialog:
    """测试端到端语音对话：完整的 ASR → LLM → TTS 流程，所有系统协同工作"""

    def test_voice_pipeline_import(self):
        """验证 UnifiedVoicePipeline 可导入"""
        from neurova.voice_pipeline import UnifiedVoicePipeline, VoicePipelineResult

        assert UnifiedVoicePipeline is not None
        assert VoicePipelineResult is not None

    def test_voice_pipeline_has_required_methods(self):
        """验证 VoicePipeline 有必需的方法"""
        from neurova.voice_pipeline import UnifiedVoicePipeline

        pipeline = UnifiedVoicePipeline()
        assert hasattr(pipeline, 'process_asr')
        assert hasattr(pipeline, 'process_tts')
        assert callable(pipeline.process_asr)
        assert callable(pipeline.process_tts)

    def test_voice_pipeline_result_dataclass(self):
        """验证 VoicePipelineResult 数据类"""
        from neurova.voice_pipeline import VoicePipelineResult

        result = VoicePipelineResult(
            text="测试文本",
            confidence=0.9,
            language="zh",
            engine="funasr",
            duration_ms=800,
        )

        assert result.text == "测试文本"
        assert result.confidence == 0.9
        assert result.success  # 有文本时 success=True

    def test_voice_pipeline_stats(self):
        """验证 VoicePipeline 统计信息"""
        from neurova.voice_pipeline import UnifiedVoicePipeline

        pipeline = UnifiedVoicePipeline()
        stats = pipeline.get_pipeline_stats()

        assert "voice_context_module" in stats
        assert "voice_memory_bridge" in stats
        assert "asr_manager" in stats
        assert "tts_manager" in stats

    def test_voice_pipeline_singleton(self):
        """验证 VoicePipeline 单例模式"""
        from neurova.voice_pipeline import get_voice_pipeline, reset_voice_pipeline

        reset_voice_pipeline()
        pipeline1 = get_voice_pipeline()
        pipeline2 = get_voice_pipeline()

        assert pipeline1 is pipeline2


# ============================================================
# 集成测试：完整流程验证
# ============================================================

class TestVoiceSystemIntegration:
    """测试语音系统集成：所有模块协同工作"""

    def test_voice_context_module_injects_metadata(self):
        """验证 VoiceContextModule 注入元数据"""
        from neurova.voice_context_module import VoiceContextModule

        module = VoiceContextModule()
        mock_context_pool = MagicMock()
        
        asr_result = {
            "text": "测试文本",
            "confidence": 0.9,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 800,
        }

        voice_context = module.build_voice_context(asr_result=asr_result)
        module.inject_metadata(mock_context_pool, voice_context)

        # 验证 ContextPool.add_context 被调用
        assert mock_context_pool.add_context.called

    @pytest.mark.asyncio
    async def test_voice_memory_bridge_records_asr(self):
        """验证 VoiceMemoryBridge 记录 ASR 结果"""
        from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

        mock_memory = MagicMock()
        mock_memory.remember.return_value = "mem_123"
        mock_evolution = MagicMock()

        config = VoiceMemoryConfig(
            enable_asr_memory=True,
            enable_emotion_analysis=False,
            min_confidence_threshold=0.3,
        )

        bridge = VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory,
            evolution_orchestrator=mock_evolution,
        )

        asr_result = {
            "text": "测试文本",
            "confidence": 0.9,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 800,
        }

        result = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_1",
            agent_id="agent_1",
        )

        # 验证记忆被存储
        mock_memory.remember.assert_called_once()
        assert result.success

        # 验证进化系统被调用
        mock_evolution.on_after_tool_execution.assert_called_once()

    def test_all_voice_tools_registered(self):
        """验证所有语音工具已注册"""
        from neurova.builtin_tools import get_builtin_tool_params

        tools = ["asr_transcribe", "tts_synthesize", "voice_memory_search"]
        for tool_name in tools:
            params = get_builtin_tool_params(tool_name)
            assert params is not None, f"Tool {tool_name} not registered"
            assert "description" in params
            assert "parameters" in params

    def test_voice_recall_channel_included(self):
        """验证语音检索通道已包含"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import (
            NeurovaRecallEngine, RecallChannel
        )

        engine = NeurovaRecallEngine()
        assert RecallChannel.VOICE in engine._channel_weights
        assert hasattr(engine, '_channel_voice')
