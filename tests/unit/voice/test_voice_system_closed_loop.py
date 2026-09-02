"""
语音系统闭环完整测试

验证三个架构摩擦点的解决方案：
1. VoiceMemoryBridge 解决记忆闭环断裂
2. VoiceAdapter 解决接口不对齐
3. VoiceAdapter health_check 解决生命周期不完整
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

# 导入被测模块
try:
    from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig
    from neurova.voice_adapter import VoiceAdapterFactory, TTSManagerAdapter, ASRManagerAdapter
    from neurova.channels.voice import VoiceAdapter
    from neurova.channels.base import ChannelConfig
except ImportError as e:
    import sys
    print(f"跳过闭环测试: {e}", file=sys.stderr)
    pytest.skip(f"跳过闭环测试: {e}", allow_module_level=True)


class TestVoiceMemoryBridgeClosedLoop:
    """VoiceMemoryBridge 闭环测试"""
    
    @pytest.fixture
    def mock_memory_manager(self):
        """模拟记忆管理器"""
        manager = Mock()
        manager.remember = Mock(return_value="memory_123")
        manager.get_memories_by_type = Mock(return_value=[])
        return manager
    
    @pytest.fixture
    def mock_emotion_module(self):
        """模拟情感模块"""
        module = Mock()
        module.analyze_text_emotion = Mock(return_value=Mock(
            primary_emotion=Mock(value="neutral"),
            confidence=0.8,
            secondary_emotions={},
        ))
        return module
    
    @pytest.fixture
    def mock_evolution_orchestrator(self):
        """模拟进化编排器"""
        orchestrator = Mock()
        orchestrator.record_voice_usage = Mock()
        return orchestrator
    
    @pytest.fixture
    def bridge(self, mock_memory_manager, mock_emotion_module, mock_evolution_orchestrator):
        """创建 VoiceMemoryBridge 实例"""
        config = VoiceMemoryConfig()
        return VoiceMemoryBridge(
            config=config,
            memory_manager=mock_memory_manager,
            emotion_module=mock_emotion_module,
            evolution_orchestrator=mock_evolution_orchestrator,
        )
    
    @pytest.mark.asyncio
    async def test_asr_to_memory_closed_loop(self, bridge, mock_memory_manager):
        """测试 ASR 到记忆的完整闭环"""
        # 1. 模拟 ASR 结果
        asr_result = {
            "text": "用户语音输入测试",
            "confidence": 0.92,
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 1500,
        }
        
        # 2. 记录到记忆系统
        result = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_123",
            agent_id="agent_456",
        )
        
        # 3. 验证闭环
        assert result.success is True
        assert result.memory_id == "memory_123"
        assert result.emotion_label == "neutral"
        
        # 4. 验证记忆管理器被调用
        mock_memory_manager.remember.assert_called_once()
        call_args = mock_memory_manager.remember.call_args
        assert call_args.kwargs["memory_type"] == "asr_transcription"
        assert "语音转写" in call_args.kwargs["content"]
    
    @pytest.mark.asyncio
    async def test_tts_to_evolution_closed_loop(self, bridge, mock_evolution_orchestrator):
        """测试 TTS 到进化系统的完整闭环"""
        # 1. 模拟 TTS 结果
        tts_result = {
            "text_length": 150,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 1800,
            "success": True,
            "audio_size_bytes": 48000,
        }
        
        # 2. 记录使用统计
        result = await bridge.record_tts_usage(
            tts_result=tts_result,
            user_id="user_123",
            agent_id="agent_456",
        )
        
        # 3. 验证闭环
        assert result.success is True
        assert result.stats_recorded is True
        assert result.success_flag is True
        
        # 4. 验证进化编排器被调用
        # 现行桥接契约：经 on_after_tool_execution（tool_name='tts_synthesize'）
        mock_evolution_orchestrator.on_after_tool_execution.assert_called_once()
        call_args = mock_evolution_orchestrator.on_after_tool_execution.call_args
        assert call_args.kwargs["tool_name"] == "tts_synthesize"
        assert call_args.kwargs["success"] is True
    
    @pytest.mark.asyncio
    async def test_emotion_analysis_closed_loop(self, bridge, mock_emotion_module):
        """测试情感分析的完整闭环"""
        # 1. 分析语音情感
        emotion_result = await bridge.analyze_voice_emotion(
            text="我今天非常开心！",
            user_id="user_123",
        )
        
        # 2. 验证闭环
        assert emotion_result is not None
        assert emotion_result["primary_emotion"] == "neutral"
        assert emotion_result["confidence"] == 0.8
        
        # 3. 验证情感模块被调用
        mock_emotion_module.analyze_text_emotion.assert_called_once_with("我今天非常开心！")


class TestVoiceAdapterInterfaceAlignment:
    """VoiceAdapter 接口对齐测试"""
    
    @pytest.fixture
    def mock_tts_manager(self):
        """模拟 TTSManager"""
        manager = Mock()
        manager.synthesize = AsyncMock(return_value=b"audio_data")
        manager.engine_name = "edge-tts"
        manager.is_initialized = True
        return manager
    
    @pytest.fixture
    def mock_asr_manager(self):
        """模拟 ASRManager"""
        manager = Mock()
        manager.transcribe = AsyncMock(return_value={"text": "转写结果", "confidence": 0.9})
        manager.engine_name = "whisper"
        manager.is_initialized = True
        return manager
    
    @pytest.mark.asyncio
    async def test_tts_adapter_alignment(self, mock_tts_manager):
        """测试 TTS 适配器接口对齐"""
        # 1. 创建适配器
        adapter = VoiceAdapterFactory.create_tts_adapter(mock_tts_manager)
        
        # 2. 适配处理请求
        result = await adapter.adapt_process(
            input_data="测试文本",
            operation="synthesize",
            voice="zh-CN-XiaoxiaoNeural",
        )
        
        # 3. 验证对齐
        assert result == b"audio_data"
        mock_tts_manager.synthesize.assert_called_once_with("测试文本", voice="zh-CN-XiaoxiaoNeural")
        
        # 4. 适配结果
        adapted_result = adapter.adapt_result(result, "synthesize")
        assert adapted_result["audio_data"] == b"audio_data"
        assert adapted_result["engine"] == "edge-tts"
    
    @pytest.mark.asyncio
    async def test_asr_adapter_alignment(self, mock_asr_manager):
        """测试 ASR 适配器接口对齐"""
        # 1. 创建适配器
        adapter = VoiceAdapterFactory.create_asr_adapter(mock_asr_manager)
        
        # 2. 适配处理请求
        result = await adapter.adapt_process(
            input_data=b"audio_bytes",
            operation="transcribe",
            language="zh",
        )
        
        # 3. 验证对齐
        assert result == {"text": "转写结果", "confidence": 0.9}
        mock_asr_manager.transcribe.assert_called_once_with(b"audio_bytes", language="zh")
        
        # 4. 适配结果
        adapted_result = adapter.adapt_result(result, "transcribe")
        assert adapted_result["text"] == "转写结果"
        assert adapted_result["confidence"] == 0.9
        assert adapted_result["engine"] == "whisper"


class TestVoiceAdapterLifecycleCompleteness:
    """VoiceAdapter 生命周期完整性测试"""
    
    @pytest.fixture
    def voice_config(self):
        """创建语音通道配置"""
        return ChannelConfig(
            channel_type="voice",
            enabled=True,
            app_id="test_account_sid",
            app_secret="test_auth_token",
            extra={"from_number": "+1234567890"},
        )
    
    @pytest.fixture
    def voice_adapter(self, voice_config):
        """创建 VoiceAdapter 实例"""
        return VoiceAdapter(voice_config)
    
    @pytest.mark.asyncio
    async def test_health_check_complete(self, voice_adapter):
        """测试健康检查完整性"""
        # 1. 调用健康检查
        health = await voice_adapter.health_check()
        
        # 2. 验证完整性
        assert "channel_type" in health
        assert "connected" in health
        assert "enabled" in health
        assert "active_calls_count" in health
        assert "has_client" in health
        assert "from_number" in health
        
        # 3. 验证值
        assert health["channel_type"] == "voice"
        assert health["connected"] is False
        assert health["enabled"] is True
        assert health["active_calls_count"] == 0
        assert health["has_client"] is False
        assert health["from_number"] == "+1234567890"
    
    @pytest.mark.asyncio
    async def test_lifecycle_methods_complete(self, voice_adapter):
        """测试生命周期方法完整性"""
        # 1. 验证所有必需方法存在
        assert hasattr(voice_adapter, "connect")
        assert hasattr(voice_adapter, "disconnect")
        assert hasattr(voice_adapter, "send_message")
        assert hasattr(voice_adapter, "health_check")
        
        # 2. 验证方法可调用
        assert callable(voice_adapter.connect)
        assert callable(voice_adapter.disconnect)
        assert callable(voice_adapter.send_message)
        assert callable(voice_adapter.health_check)
        
        # 3. 验证属性
        assert hasattr(voice_adapter, "is_connected")
        assert hasattr(voice_adapter, "channel_type")


class TestEndToEndVoiceSystemIntegration:
    """端到端语音系统集成测试"""
    
    @pytest.mark.asyncio
    async def test_complete_voice_processing_pipeline(self):
        """测试完整的语音处理管线"""
        # 1. 创建组件（注入 mock 依赖）
        mock_memory_manager = Mock()
        mock_memory_manager.remember = Mock(return_value="memory_123")
        asr_stub = {"metadata": {"confidence": 0.88, "engine": "funasr", "memory_type": "asr_transcription"}}
        tts_stub = {"metadata": {"success": True, "engine": "edge-tts", "memory_type": "tts_usage"}}
        def _recall(query, limit=1000):
            if "asr" in query:
                return [asr_stub]
            return [tts_stub]
        mock_memory_manager.recall.side_effect = _recall
        bridge = VoiceMemoryBridge(
            memory_manager=mock_memory_manager,
            config=VoiceMemoryConfig(min_confidence_threshold=0.0),
        )
        
        # 2. 模拟 ASR 处理
        asr_result = {
            "text": "用户语音输入",
            "confidence": 0.88,
            "language": "zh",
            "engine": "funasr",
            "duration_ms": 2000,
        }
        
        asr_memory = await bridge.record_asr_result(
            asr_result=asr_result,
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert asr_memory.success is True
        
        # 3. 模拟 TTS 处理
        tts_result = {
            "text_length": 150,
            "engine": "edge-tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "duration_ms": 1800,
            "success": True,
            "audio_size_bytes": 48000,
        }
        
        tts_stats = await bridge.record_tts_usage(
            tts_result=tts_result,
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert tts_stats.success is True
        
        # 4. 验证统计
        stats = await bridge.get_voice_memory_stats(
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert stats["asr_count"] >= 1
        assert stats["tts_count"] >= 1
    
    @pytest.mark.asyncio
    async def test_adapter_with_voice_memory_bridge(self):
        """测试适配器与 VoiceMemoryBridge 集成"""
        # 1. 创建模拟组件
        mock_tts_manager = Mock()
        mock_tts_manager.synthesize = AsyncMock(return_value=b"audio_data")
        mock_tts_manager.engine_name = "edge-tts"
        
        mock_evolution = Mock()
        mock_evolution.on_after_tool_execution = Mock()
        
        # 2. 创建适配器
        adapter = VoiceAdapterFactory.create_tts_adapter(mock_tts_manager)
        
        # 3. 创建桥接器（注入 evolution_orchestrator）
        bridge = VoiceMemoryBridge(
            evolution_orchestrator=mock_evolution,
        )
        
        # 4. 适配处理
        audio_data = await adapter.adapt_process(
            input_data="测试文本",
            operation="synthesize",
        )
        
        # 5. 记录使用统计
        tts_result = {
            "text_length": len("测试文本"),
            "engine": "edge-tts",
            "voice": "default",
            "duration_ms": 1000,
            "success": True,
            "audio_size_bytes": len(audio_data),
        }
        
        usage_result = await bridge.record_tts_usage(
            tts_result=tts_result,
            user_id="user_123",
            agent_id="agent_456",
        )
        
        assert usage_result.success is True
        assert usage_result.stats_recorded is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])