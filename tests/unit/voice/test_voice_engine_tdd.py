"""
VoiceEngine TDD 测试 - 统一语音引擎接口

测试统一的语音引擎接口，为 ASR 和 TTS 提供一致的 API。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult


@pytest.fixture
def mock_asr_engine():
    """创建模拟的 ASR 引擎"""
    engine = MagicMock()
    engine.is_initialized = True
    engine.initialize = AsyncMock(return_value=True)
    engine.transcribe = AsyncMock(return_value={
        "text": "Hello world",
        "confidence": 0.9,
        "language": "en"
    })
    engine.understand = AsyncMock(return_value={
        "intent": "greeting",
        "entities": []
    })
    engine.caption = AsyncMock(return_value="Audio caption")
    return engine


@pytest.fixture
def mock_tts_engine():
    """创建模拟的 TTS 引擎"""
    engine = MagicMock()
    engine.is_initialized = True
    engine.initialize = AsyncMock(return_value=True)
    engine.synthesize = AsyncMock(return_value=b"audio bytes")
    return engine


@pytest.fixture
def asr_voice_engine(mock_asr_engine):
    """创建 ASR VoiceEngine 实例"""
    return VoiceEngine(
        engine_type=VoiceEngineType.ASR,
        engine=mock_asr_engine
    )


@pytest.fixture
def tts_voice_engine(mock_tts_engine):
    """创建 TTS VoiceEngine 实例"""
    return VoiceEngine(
        engine_type=VoiceEngineType.TTS,
        engine=mock_tts_engine
    )


class TestVoiceEngineBehavior:
    """VoiceEngine 行为测试 - 统一接口"""
    
    @pytest.mark.asyncio
    async def test_asr_voice_engine_transcribe(self, asr_voice_engine, mock_asr_engine):
        """ASR 引擎应能转录音频"""
        result = await asr_voice_engine.process(
            input_data=b"audio bytes",
            operation="transcribe"
        )
        
        assert isinstance(result, VoiceResult)
        assert result.text == "Hello world"
        assert result.confidence == 0.9
        mock_asr_engine.transcribe.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_asr_voice_engine_understand(self, asr_voice_engine, mock_asr_engine):
        """ASR 引擎应能理解音频"""
        result = await asr_voice_engine.process(
            input_data=b"audio bytes",
            operation="understand"
        )
        
        assert isinstance(result, VoiceResult)
        assert result.metadata["intent"] == "greeting"
        mock_asr_engine.understand.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_tts_voice_engine_synthesize(self, tts_voice_engine, mock_tts_engine):
        """TTS 引擎应能合成语音"""
        result = await tts_voice_engine.process(
            input_data="Hello world",
            operation="synthesize"
        )
        
        assert isinstance(result, VoiceResult)
        assert result.audio_data == b"audio bytes"
        mock_tts_engine.synthesize.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_voice_engine_unified_interface(self, asr_voice_engine, tts_voice_engine):
        """ASR 和 TTS 应使用统一的接口"""
        # ASR 处理
        asr_result = await asr_voice_engine.process(
            input_data=b"audio",
            operation="transcribe"
        )
        
        # TTS 处理
        tts_result = await tts_voice_engine.process(
            input_data="text",
            operation="synthesize"
        )
        
        # 都返回 VoiceResult
        assert isinstance(asr_result, VoiceResult)
        assert isinstance(tts_result, VoiceResult)
    
    @pytest.mark.asyncio
    async def test_voice_engine_error_handling(self, asr_voice_engine, mock_asr_engine):
        """引擎应优雅地处理错误"""
        mock_asr_engine.transcribe.side_effect = Exception("ASR failed")
        
        result = await asr_voice_engine.process(
            input_data=b"audio",
            operation="transcribe"
        )
        
        assert result.error is not None
        assert "ASR failed" in result.error
    
    @pytest.mark.asyncio
    async def test_voice_engine_get_info(self, asr_voice_engine):
        """引擎应提供信息查询"""
        info = asr_voice_engine.get_info()
        
        assert "engine_type" in info
        assert "is_initialized" in info
        assert info["engine_type"] == "asr"
    
    @pytest.mark.asyncio
    async def test_voice_engine_is_available(self, asr_voice_engine):
        """引擎应报告可用性"""
        assert asr_voice_engine.is_available() is True
        
        asr_voice_engine._engine.is_initialized = False
        assert asr_voice_engine.is_available() is False


class TestVoiceEngineType:
    """VoiceEngineType 枚举测试"""
    
    def test_engine_types(self):
        """应支持 ASR 和 TTS 类型"""
        assert VoiceEngineType.ASR.value == "asr"
        assert VoiceEngineType.TTS.value == "tts"
    
    def test_from_string(self):
        """应能从字符串创建"""
        assert VoiceEngineType("asr") == VoiceEngineType.ASR
        assert VoiceEngineType("tts") == VoiceEngineType.TTS


class TestVoiceResult:
    """VoiceResult 数据类测试"""
    
    def test_voice_result_structure(self):
        """VoiceResult 应有正确的结构"""
        result = VoiceResult(
            text="Hello",
            confidence=0.9,
            audio_data=b"audio",
            metadata={"intent": "greeting"},
            error=None
        )
        
        assert result.text == "Hello"
        assert result.confidence == 0.9
        assert result.audio_data == b"audio"
        assert result.metadata["intent"] == "greeting"
        assert result.error is None
    
    def test_voice_result_defaults(self):
        """VoiceResult 应有默认值"""
        result = VoiceResult()
        
        assert result.text is None
        assert result.confidence is None
        assert result.audio_data is None
        assert result.metadata == {}
        assert result.error is None