"""
VoiceEngine API 集成测试 - 更新实际 API 端点使用 VoiceEngine

测试将 audio.py 端点从直接调用 TTSManager/ASRManager 迁移到使用 VoiceEngine 统一接口。
使用 conftest.py 中的共享 fixtures。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import Response

from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult


@pytest.fixture
def app_with_voice_engines(mock_tts_voice_engine, mock_asr_voice_engine):
    """创建使用 VoiceEngine 的测试应用"""
    app = FastAPI()
    
    # 模拟 app_state 中的 voice_engines
    app.state.voice_engines = {
        "tts": mock_tts_voice_engine,
        "asr": mock_asr_voice_engine
    }
    
    # 模拟 get_app_state 函数
    def mock_get_app_state():
        return {
            "voice_engines": app.state.voice_engines
        }
    
    # 修补 audio 模块的 get_app_state 绑定（audio.py 是 from-import，
    # patch neurova.api.endpoints.get_app_state 对其无效——顺序依赖失败根因）
    patcher = patch("neurova.api.endpoints.audio.get_app_state", mock_get_app_state)
    patcher.start()
    
    from neurova.api.endpoints.audio import router
    app.include_router(router, prefix="/api/v1/audio")
    
    yield app
    
    patcher.stop()


class TestVoiceEngineAPIIntegration:
    """测试 VoiceEngine 集成到 API 端点"""
    
    def test_synthesize_uses_voice_engine(self, app_with_voice_engines, mock_tts_voice_engine):
        """TTS 合成端点应使用 VoiceEngine"""
        client = TestClient(app_with_voice_engines)
        
        response = client.post(
            "/api/v1/audio/synthesize",
            json={"text": "测试文本", "voice": "zh-CN-XiaoxiaoNeural"}
        )
        
        assert response.status_code == 200
        # 验证 VoiceEngine.process 被调用
        mock_tts_voice_engine.process.assert_called_once()
        call_args = mock_tts_voice_engine.process.call_args
        assert call_args.kwargs["input_data"] == "测试文本"
        assert call_args.kwargs["operation"] == "synthesize"
    
    def test_transcribe_uses_voice_engine(self, app_with_voice_engines, mock_asr_voice_engine):
        """ASR 转录端点应使用 VoiceEngine"""
        client = TestClient(app_with_voice_engines)
        
        # 创建测试音频文件
        import io
        audio_content = b"fake audio data"
        
        response = client.post(
            "/api/v1/audio/transcribe",
            files={"audio_file": ("test.wav", io.BytesIO(audio_content), "audio/wav")},
            data={"language": "zh"}
        )
        
        assert response.status_code == 200
        # 验证 VoiceEngine.process 被调用
        print("DBG fixture asr id=", id(mock_asr_voice_engine))
        mock_asr_voice_engine.process.assert_called_once()
        call_args = mock_asr_voice_engine.process.call_args
        assert call_args.kwargs["operation"] == "transcribe"
        assert call_args.kwargs["input_data"] == audio_content
    
    def test_synthesize_handles_voice_engine_error(self, app_with_voice_engines, mock_failing_voice_engine):
        """TTS 端点应优雅处理 VoiceEngine 错误"""
        # 替换为失败的引擎
        app_with_voice_engines.state.voice_engines["tts"] = mock_failing_voice_engine
        print("process return_value:", app_with_voice_engines.state.voice_engines["tts"].process.return_value)
        
        client = TestClient(app_with_voice_engines)
        response = client.post(
            "/api/v1/audio/synthesize",
            json={"text": "测试文本"}
        )
        
        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert data["detail"] == "引擎故障"
    
    def test_engine_status_uses_voice_engine(self, app_with_voice_engines, mock_tts_voice_engine, mock_asr_voice_engine):
        """引擎状态端点应使用 VoiceEngine"""
        client = TestClient(app_with_voice_engines)
        
        response = client.get("/api/v1/audio/status")
        
        assert response.status_code == 200
        data = response.json()
        assert "tts" in data["data"]
        assert "asr" in data["data"]
        
        # 验证状态信息来自 VoiceEngine
        tts_status = data["data"]["tts"]
        assert tts_status["initialized"] == True
        assert "engine_info" in tts_status
    
    def test_list_engines_uses_voice_engine(self, app_with_voice_engines):
        """引擎列表端点应使用 VoiceEngine"""
        client = TestClient(app_with_voice_engines)
        
        response = client.get("/api/v1/audio/engines")
        
        assert response.status_code == 200
        data = response.json()
        engines = data["data"]
        
        # 应该有两个引擎：tts 和 asr
        engine_names = [e["name"] for e in engines]
        assert "tts" in engine_names
        assert "asr" in engine_names


class TestVoiceEngineAutoSelection:
    """测试语音引擎自动选择和故障转移"""
    
    def test_voice_engine_factory_creates_correct_type(self):
        """VoiceEngineFactory 应创建正确类型的引擎"""
        from neurova.voice_engine import VoiceEngineFactory
        
        # 模拟引擎类
        class MockEngine:
            def __init__(self, **kwargs):
                pass
            async def initialize(self):
                return True
        
        # 创建 TTS 引擎
        tts_engine = VoiceEngineFactory.create_tts_engine(MockEngine)
        assert tts_engine.engine_type == VoiceEngineType.TTS
        
        # 创建 ASR 引擎
        asr_engine = VoiceEngineFactory.create_asr_engine(MockEngine)
        assert asr_engine.engine_type == VoiceEngineType.ASR
    
    @pytest.mark.asyncio
    async def test_voice_engine_process_dispatches_correctly(self):
        """VoiceEngine.process 应根据引擎类型分派到正确的方法"""
        from neurova.voice_engine import VoiceEngine, VoiceEngineType
        
        # 模拟 ASR 引擎
        mock_asr = MagicMock()
        mock_asr.transcribe = AsyncMock(return_value={"text": "测试"})
        
        engine = VoiceEngine(
            engine_type=VoiceEngineType.ASR,
            engine=mock_asr
        )
        
        # 调用 process
        result = await engine.process(input_data=b"audio", operation="transcribe")
        
        # 验证调用了正确的方法
        mock_asr.transcribe.assert_called_once()
        assert result.text == "测试"
    
    @pytest.mark.asyncio
    async def test_voice_engine_handles_unsupported_operation(self):
        """VoiceEngine 应处理不支持的操作"""
        from neurova.voice_engine import VoiceEngine, VoiceEngineType
        
        mock_engine = MagicMock()
        engine = VoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engine=mock_engine
        )
        
        # 调用不支持的操作
        result = await engine.process(input_data="test", operation="unsupported")
        
        assert result.error is not None
        assert "不支持的 TTS 操作" in result.error
    
    def test_voice_engine_is_available_checks_initialization(self):
        """VoiceEngine.is_available 应检查引擎初始化状态"""
        from neurova.voice_engine import VoiceEngine, VoiceEngineType
        
        # 未初始化的引擎
        mock_engine = MagicMock()
        mock_engine.is_initialized = False
        
        engine = VoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engine=mock_engine
        )
        
        assert engine.is_available() == False
        
        # 已初始化的引擎
        mock_engine.is_initialized = True
        assert engine.is_available() == True