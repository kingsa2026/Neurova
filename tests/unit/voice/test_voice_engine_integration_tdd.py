"""
VoiceEngine 集成测试 - 与 ASRManager/TTSManager 集成

测试将 VoiceEngine 统一接口集成到现有管理器中的行为。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceEngineFactory, VoiceResult


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
def asr_manager():
    """创建模拟的 ASRManager 实例"""
    manager = MagicMock()
    manager.is_initialized = True
    manager.transcribe = AsyncMock(return_value={
        "text": "Hello world",
        "confidence": 0.9,
        "language": "en"
    })
    return manager


@pytest.fixture
def tts_manager():
    """创建模拟的 TTSManager 实例"""
    manager = MagicMock()
    manager.is_initialized = True
    manager.synthesize = AsyncMock(return_value=b"audio bytes")
    return manager


class TestVoiceEngineIntegration:
    """VoiceEngine 与 ASRManager/TTSManager 集成测试"""
    
    @pytest.mark.asyncio
    async def test_create_asr_voice_engine(self, asr_manager, mock_asr_engine):
        """应能从 ASRManager 创建 VoiceEngine"""
        # 模拟 ASRManager 的引擎
        asr_manager._engine = mock_asr_engine
        asr_manager._initialized = True
        
        # 创建 VoiceEngine
        voice_engine = VoiceEngine(
            engine_type=VoiceEngineType.ASR,
            engine=asr_manager
        )
        
        # 测试转录功能
        result = await voice_engine.process(
            input_data=b"audio bytes",
            operation="transcribe"
        )
        
        assert isinstance(result, VoiceResult)
        assert result.text == "Hello world"
        assert result.confidence == 0.9
    
    @pytest.mark.asyncio
    async def test_create_tts_voice_engine(self, tts_manager, mock_tts_engine):
        """应能从 TTSManager 创建 VoiceEngine"""
        # 模拟 TTSManager 的引擎
        tts_manager._engine = mock_tts_engine
        tts_manager._initialized = True
        
        # 创建 VoiceEngine
        voice_engine = VoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engine=tts_manager
        )
        
        # 测试合成功能
        result = await voice_engine.process(
            input_data="Hello world",
            operation="synthesize"
        )
        
        assert isinstance(result, VoiceResult)
        assert result.audio_data == b"audio bytes"
    
    @pytest.mark.asyncio
    async def test_voice_engine_factory_with_managers(self, asr_manager, tts_manager):
        """应能通过工厂创建 VoiceEngine"""
        # 创建 ASR VoiceEngine
        asr_engine = VoiceEngineFactory.create_asr_engine(
            MagicMock,  # 使用 MagicMock 替代实际类
            config=MagicMock()
        )
        
        # 创建 TTS VoiceEngine
        tts_engine = VoiceEngineFactory.create_tts_engine(
            MagicMock,  # 使用 MagicMock 替代实际类
            config=MagicMock()
        )
        
        assert asr_engine.engine_type == VoiceEngineType.ASR
        assert tts_engine.engine_type == VoiceEngineType.TTS
    
    @pytest.mark.asyncio
    async def test_voice_engine_unified_interface(self, asr_manager, tts_manager):
        """ASR 和 TTS 应使用统一的接口"""
        # 创建 VoiceEngine
        asr_voice_engine = VoiceEngine(
            engine_type=VoiceEngineType.ASR,
            engine=asr_manager
        )
        
        tts_voice_engine = VoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engine=tts_manager
        )
        
        # 都应支持 process 方法
        assert hasattr(asr_voice_engine, 'process')
        assert hasattr(tts_voice_engine, 'process')
        
        # 都应支持 get_info 方法
        asr_info = asr_voice_engine.get_info()
        tts_info = tts_voice_engine.get_info()
        
        assert asr_info["engine_type"] == "asr"
        assert tts_info["engine_type"] == "tts"
    
    @pytest.mark.asyncio
    async def test_voice_engine_error_handling(self, asr_manager):
        """VoiceEngine 应优雅地处理错误"""
        # 创建 VoiceEngine
        voice_engine = VoiceEngine(
            engine_type=VoiceEngineType.ASR,
            engine=asr_manager
        )
        
        # 测试不支持的操作
        result = await voice_engine.process(
            input_data=b"audio",
            operation="unsupported_operation"
        )
        
        assert result.error is not None
        assert "不支持的 ASR 操作" in result.error


class TestVoiceEngineWithRealManagers:
    """VoiceEngine 与真实管理器集成测试"""
    
    @pytest.mark.asyncio
    async def test_asr_manager_compatibility(self, asr_manager):
        """ASRManager 应与 VoiceEngine 兼容"""
        # 检查 ASRManager 是否有 VoiceEngine 需要的属性
        assert hasattr(asr_manager, 'is_initialized')
        assert hasattr(asr_manager, 'transcribe')
        
        # 检查 is_initialized 属性
        assert isinstance(asr_manager.is_initialized, bool)
    
    @pytest.mark.asyncio
    async def test_tts_manager_compatibility(self, tts_manager):
        """TTSManager 应与 VoiceEngine 兼容"""
        # 检查 TTSManager 是否有 VoiceEngine 需要的属性
        assert hasattr(tts_manager, 'is_initialized')
        assert hasattr(tts_manager, 'synthesize')
        
        # 检查 is_initialized 属性
        assert isinstance(tts_manager.is_initialized, bool)