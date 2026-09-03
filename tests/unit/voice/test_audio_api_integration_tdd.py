"""
Audio API 集成测试 - VoiceEngine 集成

测试将 VoiceEngine 统一接口集成到 API 端点中的行为。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult


@pytest.fixture
def mock_voice_engine():
    """创建模拟的 VoiceEngine"""
    engine = MagicMock(spec=VoiceEngine)
    engine.engine_type = VoiceEngineType.TTS
    engine.is_available.return_value = True
    engine.get_info.return_value = {
        "engine_type": "tts",
        "is_initialized": True,
        "engine_class": "MockTTS"
    }
    engine.process = AsyncMock(return_value=VoiceResult(
        audio_data=b"audio bytes",
        metadata={"operation": "synthesize"}
    ))
    return engine


@pytest.fixture
def app():
    """创建测试 FastAPI 应用"""
    app = FastAPI()
    
    # 模拟 app_state
    app.state.voice_engines = {}
    
    @app.post("/test/synthesize")
    async def test_synthesize(text: str):
        """测试 TTS 合成端点"""
        from neurova.voice_engine import VoiceEngineType, VoiceResult
        
        # 获取 VoiceEngine
        voice_engine = app.state.voice_engines.get("tts")
        if not voice_engine:
            return {"error": "VoiceEngine not available"}
        
        # 使用统一接口
        result = await voice_engine.process(
            input_data=text,
            operation="synthesize"
        )
        
        if result.error:
            return {"error": result.error}
        
        return {
            "audio_data": result.audio_data,
            "metadata": result.metadata
        }
    
    @app.post("/test/transcribe")
    async def test_transcribe(audio_bytes: bytes):
        """测试 ASR 转录端点"""
        from neurova.voice_engine import VoiceEngineType, VoiceResult
        
        # 获取 VoiceEngine
        voice_engine = app.state.voice_engines.get("asr")
        if not voice_engine:
            return {"error": "VoiceEngine not available"}
        
        # 使用统一接口
        result = await voice_engine.process(
            input_data=audio_bytes,
            operation="transcribe"
        )
        
        if result.error:
            return {"error": result.error}
        
        return {
            "text": result.text,
            "confidence": result.confidence,
            "metadata": result.metadata
        }
    
    return app


class TestAudioAPIIntegration:
    """Audio API 与 VoiceEngine 集成测试"""
    
    def test_synthesize_endpoint_with_voice_engine(self, app, mock_voice_engine):
        """TTS 端点应能使用 VoiceEngine"""
        # 设置 VoiceEngine
        app.state.voice_engines["tts"] = mock_voice_engine
        
        client = TestClient(app)
        response = client.post("/test/synthesize", params={"text": "Hello world"})
        
        assert response.status_code == 200
        data = response.json()
        assert "audio_data" in data
        assert data["audio_data"] == "audio bytes"
    
    def test_transcribe_endpoint_with_voice_engine(self, app, mock_voice_engine):
        """ASR 端点应能使用 VoiceEngine"""
        # 设置 VoiceEngine
        asr_engine = MagicMock(spec=VoiceEngine)
        asr_engine.engine_type = VoiceEngineType.ASR
        asr_engine.is_available.return_value = True
        asr_engine.process = AsyncMock(return_value=VoiceResult(
            text="Hello world",
            confidence=0.9,
            metadata={"operation": "transcribe"}
        ))
        
        app.state.voice_engines["asr"] = asr_engine
        
        client = TestClient(app)
        # 使用查询参数
        response = client.post(
            "/test/transcribe",
            params={"audio_bytes": "audio bytes"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "text" in data
        assert data["text"] == "Hello world"
    
    def test_endpoint_handles_voice_engine_error(self, app):
        """端点应优雅地处理 VoiceEngine 错误"""
        # 设置一个会失败的 VoiceEngine
        failing_engine = MagicMock(spec=VoiceEngine)
        failing_engine.engine_type = VoiceEngineType.TTS
        failing_engine.is_available.return_value = True
        failing_engine.process = AsyncMock(return_value=VoiceResult(
            error="TTS failed"
        ))
        
        app.state.voice_engines["tts"] = failing_engine
        
        client = TestClient(app)
        response = client.post("/test/synthesize", params={"text": "Hello world"})
        
        assert response.status_code == 200
        data = response.json()
        assert "error" in data
        assert data["error"] == "TTS failed"