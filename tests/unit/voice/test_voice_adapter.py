"""
VoiceAdapter 测试套件

测试语音适配器模式：
1. TTSManagerAdapter 适配 TTSManager 到 VoiceEngine 接口
2. ASRManagerAdapter 适配 ASRManager 到 VoiceEngine 接口
3. 适配器工厂和便捷函数
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch

# 导入被测模块
try:
    from neurova.voice_adapter import (
        VoiceAdapter,
        TTSManagerAdapter,
        ASRManagerAdapter,
        VoiceAdapterFactory,
        adapt_voice_process,
    )
except ImportError as e:
    import sys
    print(f"跳过适配器测试: {e}", file=sys.stderr)
    pytest.skip(f"跳过适配器测试: {e}", allow_module_level=True)


class TestTTSManagerAdapter:
    """TTSManagerAdapter 测试"""
    
    @pytest.fixture
    def mock_tts_manager(self):
        """模拟 TTSManager"""
        manager = Mock()
        manager.synthesize = AsyncMock(return_value=b"audio_data")
        manager.engine_name = "edge-tts"
        manager.is_initialized = True
        return manager
    
    @pytest.fixture
    def tts_adapter(self, mock_tts_manager):
        """创建 TTS 适配器"""
        return TTSManagerAdapter(mock_tts_manager)
    
    @pytest.mark.asyncio
    async def test_adapt_process_synthesize(self, tts_adapter, mock_tts_manager):
        """测试适配 synthesize 操作"""
        result = await tts_adapter.adapt_process(
            input_data="你好世界",
            operation="synthesize",
            voice="zh-CN-XiaoxiaoNeural",
        )
        
        assert result == b"audio_data"
        mock_tts_manager.synthesize.assert_called_once_with("你好世界", voice="zh-CN-XiaoxiaoNeural")
    
    @pytest.mark.asyncio
    async def test_adapt_process_invalid_operation(self, tts_adapter):
        """测试不支持的操作"""
        with pytest.raises(ValueError, match="不支持的操作"):
            await tts_adapter.adapt_process(
                input_data="测试",
                operation="transcribe",  # TTS 不支持 transcribe
            )
    
    def test_adapt_result(self, tts_adapter):
        """测试结果适配"""
        result = tts_adapter.adapt_result(
            raw_result=b"audio_data",
            operation="synthesize",
        )
        
        assert result["audio_data"] == b"audio_data"
        assert result["operation"] == "synthesize"
        assert result["engine"] == "edge-tts"
    
    def test_get_info(self, tts_adapter):
        """测试获取适配器信息"""
        info = tts_adapter.get_info()
        
        assert info["adapter_class"] == "TTSManagerAdapter"
        assert info["engine_type"] == "tts"
        assert info["engine_name"] == "edge-tts"
        assert info["is_initialized"] is True


class TestASRManagerAdapter:
    """ASRManagerAdapter 测试"""
    
    @pytest.fixture
    def mock_asr_manager(self):
        """模拟 ASRManager"""
        manager = Mock()
        manager.transcribe = AsyncMock(return_value={"text": "转写结果", "confidence": 0.9})
        manager.understand = AsyncMock(return_value={"text": "理解结果", "confidence": 0.8})
        manager.caption = AsyncMock(return_value="字幕结果")
        manager.engine_name = "whisper"
        manager.is_initialized = True
        return manager
    
    @pytest.fixture
    def asr_adapter(self, mock_asr_manager):
        """创建 ASR 适配器"""
        return ASRManagerAdapter(mock_asr_manager)
    
    @pytest.mark.asyncio
    async def test_adapt_process_transcribe(self, asr_adapter, mock_asr_manager):
        """测试适配 transcribe 操作"""
        audio_data = b"audio_bytes"
        result = await asr_adapter.adapt_process(
            input_data=audio_data,
            operation="transcribe",
            language="zh",
        )
        
        assert result == {"text": "转写结果", "confidence": 0.9}
        mock_asr_manager.transcribe.assert_called_once_with(audio_data, language="zh")
    
    @pytest.mark.asyncio
    async def test_adapt_process_understand(self, asr_adapter, mock_asr_manager):
        """测试适配 understand 操作"""
        audio_data = b"audio_bytes"
        result = await asr_adapter.adapt_process(
            input_data=audio_data,
            operation="understand",
            query="天气怎么样",
        )
        
        assert result == {"text": "理解结果", "confidence": 0.8}
        mock_asr_manager.understand.assert_called_once_with(audio_data, query="天气怎么样")
    
    @pytest.mark.asyncio
    async def test_adapt_process_caption(self, asr_adapter, mock_asr_manager):
        """测试适配 caption 操作"""
        audio_data = b"audio_bytes"
        result = await asr_adapter.adapt_process(
            input_data=audio_data,
            operation="caption",
        )
        
        assert result == "字幕结果"
        mock_asr_manager.caption.assert_called_once_with(audio_data)
    
    @pytest.mark.asyncio
    async def test_adapt_process_invalid_operation(self, asr_adapter):
        """测试不支持的操作"""
        with pytest.raises(ValueError, match="不支持的操作"):
            await asr_adapter.adapt_process(
                input_data=b"audio",
                operation="synthesize",  # ASR 不支持 synthesize
            )
    
    def test_adapt_result_transcribe(self, asr_adapter):
        """测试 transcribe 结果适配"""
        result = asr_adapter.adapt_result(
            raw_result={"text": "转写结果", "confidence": 0.9},
            operation="transcribe",
        )
        
        assert result["text"] == "转写结果"
        assert result["confidence"] == 0.9
        assert result["operation"] == "transcribe"
        assert result["engine"] == "whisper"
    
    def test_adapt_result_caption(self, asr_adapter):
        """测试 caption 结果适配"""
        result = asr_adapter.adapt_result(
            raw_result="字幕结果",
            operation="caption",
        )
        
        assert result["text"] == "字幕结果"
        assert result["confidence"] == 1.0
        assert result["operation"] == "caption"
    
    def test_get_info(self, asr_adapter):
        """测试获取适配器信息"""
        info = asr_adapter.get_info()
        
        assert info["adapter_class"] == "ASRManagerAdapter"
        assert info["engine_type"] == "asr"
        assert info["engine_name"] == "whisper"
        assert info["is_initialized"] is True


class TestVoiceAdapterFactory:
    """VoiceAdapterFactory 测试"""
    
    @pytest.fixture
    def mock_tts_manager(self):
        """模拟 TTSManager"""
        manager = Mock()
        manager.engine_name = "edge-tts"
        return manager
    
    @pytest.fixture
    def mock_asr_manager(self):
        """模拟 ASRManager"""
        manager = Mock()
        manager.engine_name = "whisper"
        return manager
    
    def test_create_tts_adapter(self, mock_tts_manager):
        """测试创建 TTS 适配器"""
        adapter = VoiceAdapterFactory.create_tts_adapter(mock_tts_manager)
        
        assert isinstance(adapter, TTSManagerAdapter)
        assert adapter._tts_manager == mock_tts_manager
    
    def test_create_asr_adapter(self, mock_asr_manager):
        """测试创建 ASR 适配器"""
        adapter = VoiceAdapterFactory.create_asr_adapter(mock_asr_manager)
        
        assert isinstance(adapter, ASRManagerAdapter)
        assert adapter._asr_manager == mock_asr_manager
    
    def test_create_adapter_for_engine_tts(self, mock_tts_manager):
        """测试为 TTS 引擎创建适配器"""
        adapter = VoiceAdapterFactory.create_adapter_for_engine("tts", mock_tts_manager)
        
        assert isinstance(adapter, TTSManagerAdapter)
    
    def test_create_adapter_for_engine_asr(self, mock_asr_manager):
        """测试为 ASR 引擎创建适配器"""
        adapter = VoiceAdapterFactory.create_adapter_for_engine("asr", mock_asr_manager)
        
        assert isinstance(adapter, ASRManagerAdapter)
    
    def test_create_adapter_for_engine_invalid(self):
        """测试为无效引擎类型创建适配器"""
        with pytest.raises(ValueError, match="不支持的引擎类型"):
            VoiceAdapterFactory.create_adapter_for_engine("invalid", Mock())


class TestAdaptVoiceProcess:
    """adapt_voice_process 便捷函数测试"""
    
    @pytest.fixture
    def mock_tts_manager(self):
        """模拟 TTSManager"""
        manager = Mock()
        manager.synthesize = AsyncMock(return_value=b"audio_data")
        manager.engine_name = "edge-tts"
        return manager
    
    @pytest.mark.asyncio
    async def test_adapt_tts_process(self, mock_tts_manager):
        """测试便捷函数适配 TTS 处理"""
        result = await adapt_voice_process(
            engine_type="tts",
            engine_manager=mock_tts_manager,
            input_data="测试文本",
            operation="synthesize",
        )
        
        assert result == b"audio_data"
        mock_tts_manager.synthesize.assert_called_once_with("测试文本")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])