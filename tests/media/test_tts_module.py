"""
TTS 模块单元测试

测试 TTS 基类、EdgeTTS、MOSSNanTTS、MockTTSSimple 和 TTSManager。
"""

import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import io

from neurova.tts.base import TTSBase
from neurova.tts.edge_tts import EdgeTTS
from neurova.tts.moss_nano import MOSSNanTTS
from neurova.tts.mock_tts_simple import MockTTSSimple
from neurova.tts.manager import TTSManager, TTSConfig


class TestTTSBase:
    """测试 TTS 基类"""

    def test_abstract_methods(self):
        """测试抽象方法"""
        # TTSBase 是抽象类，不能直接实例化
        with pytest.raises(TypeError):
            TTSBase()

    def test_concrete_tts(self):
        """测试具体 TTS 实现"""

        class TestTTS(TTSBase):
            async def initialize(self):
                return True

            async def synthesize(self, text: str) -> bytes:
                return b"test audio"

            async def synthesize_stream(self, text: str):
                yield b"chunk1"
                yield b"chunk2"

            async def shutdown(self):
                pass

        tts = TestTTS()
        assert not tts.is_initialized


class TestEdgeTTS:
    """测试 EdgeTTS"""

    @pytest.mark.asyncio
    async def test_initialize(self):
        """测试初始化"""
        tts = EdgeTTS()
        # 模拟 edge_tts 库
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            result = await tts.initialize()
            assert result is True
            assert tts.is_initialized

    @pytest.mark.asyncio
    async def test_synthesize(self):
        """测试语音合成"""
        tts = EdgeTTS()
        # 模拟 edge_tts 库
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            await tts.initialize()

            # 模拟 Communicate 类
            mock_communicate = MagicMock()
            mock_communicate.stream = AsyncMock(return_value=iter([
                {"type": "audio", "data": b"audio data"},
            ]))
            
            with patch("edge_tts.Communicate", return_value=mock_communicate):
                audio = await tts.synthesize("测试文本")
                assert isinstance(audio, bytes)

    @pytest.mark.asyncio
    async def test_list_voices(self):
        """测试列出音色"""
        tts = EdgeTTS()
        # 模拟 edge_tts 库
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            await tts.initialize()

            # 模拟 list_voices 函数
            with patch("edge_tts.list_voices", return_value=[
                {"Name": "zh-CN-XiaoxiaoNeural", "Gender": "Female"},
                {"Name": "zh-CN-YunxiNeural", "Gender": "Male"},
            ]):
                voices = await tts.list_voices()
                assert len(voices) == 2
                assert voices[0]["Name"] == "zh-CN-XiaoxiaoNeural"


class TestMOSSNanTTS:
    """测试 MOSSNanTTS"""

    @pytest.mark.asyncio
    async def test_initialize(self):
        """测试初始化"""
        tts = MOSSNanTTS()
        # 模拟模型文件存在和 ONNX Runtime
        with patch("pathlib.Path.exists", return_value=True), \
             patch.dict('sys.modules', {'onnxruntime': MagicMock()}):
            result = await tts.initialize()
            assert result is True
            assert tts.is_initialized

    @pytest.mark.asyncio
    async def test_synthesize(self):
        """测试语音合成"""
        tts = MOSSNanTTS()
        # 模拟模型文件存在和 ONNX Runtime
        with patch("pathlib.Path.exists", return_value=True), \
             patch.dict('sys.modules', {'onnxruntime': MagicMock()}):
            await tts.initialize()

            # 模拟 ONNX Runtime
            mock_session = MagicMock()
            mock_session.run.return_value = [b"audio data"]
            
            with patch("onnxruntime.InferenceSession", return_value=mock_session):
                audio = await tts.synthesize("测试文本")
                assert isinstance(audio, bytes)


class TestMockTTSSimple:
    """测试 MockTTSSimple"""

    @pytest.mark.asyncio
    async def test_initialize(self):
        """测试初始化"""
        tts = MockTTSSimple()
        result = await tts.initialize()
        assert result is True
        assert tts.is_initialized

    @pytest.mark.asyncio
    async def test_synthesize(self):
        """测试语音合成"""
        tts = MockTTSSimple()
        await tts.initialize()

        audio = await tts.synthesize("测试文本")
        assert isinstance(audio, bytes)
        # MockTTS 应该生成有效的 WAV 数据
        assert audio[:4] == b'RIFF'  # WAV 文件头

    @pytest.mark.asyncio
    async def test_synthesize_stream(self):
        """测试流式语音合成"""
        tts = MockTTSSimple()
        await tts.initialize()

        chunks = []
        async for chunk in tts.synthesize_stream("测试文本"):
            chunks.append(chunk)

        assert len(chunks) > 0
        # 合并所有 chunk 应该是有效的 WAV 数据
        audio = b"".join(chunks)
        assert audio[:4] == b'RIFF'


class TestTTSConfig:
    """测试 TTSConfig"""

    def test_default_config(self):
        """测试默认配置"""
        config = TTSConfig()
        assert config.engine == "edge-tts"
        assert config.voice == "zh-CN-XiaoxiaoNeural"
        assert config.rate == "+0%"
        assert config.volume == "+0%"

    def test_custom_config(self):
        """测试自定义配置"""
        config = TTSConfig(
            engine="moss-nano",
            voice="custom_voice",
            rate="+10%",
            volume="-20%",
        )
        assert config.engine == "moss-nano"
        assert config.voice == "custom_voice"
        assert config.rate == "+10%"
        assert config.volume == "-20%"


class TestTTSManager:
    """测试 TTSManager"""

    @pytest.mark.asyncio
    async def test_initialize_edge_tts(self):
        """测试初始化 EdgeTTS"""
        manager = TTSManager(TTSConfig(engine="edge-tts"))
        # 模拟 edge_tts 库
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            await manager.initialize()
            assert manager.is_initialized

    @pytest.mark.asyncio
    async def test_initialize_mock_tts(self):
        """测试初始化 MockTTS"""
        manager = TTSManager(TTSConfig(engine="mock"))
        await manager.initialize()
        assert manager.is_initialized

    @pytest.mark.asyncio
    async def test_synthesize(self):
        """测试语音合成"""
        manager = TTSManager(TTSConfig(engine="mock"))
        await manager.initialize()

        audio = await manager.synthesize("测试文本")
        assert isinstance(audio, bytes)
        assert len(audio) > 0

    @pytest.mark.asyncio
    async def test_synthesize_stream(self):
        """测试流式语音合成"""
        manager = TTSManager(TTSConfig(engine="mock"))
        await manager.initialize()

        chunks = []
        async for chunk in manager.synthesize_stream("测试文本"):
            chunks.append(chunk)

        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_list_voices(self):
        """测试列出音色"""
        manager = TTSManager(TTSConfig(engine="edge-tts"))
        # 模拟 edge_tts 库
        with patch.dict('sys.modules', {'edge_tts': MagicMock()}):
            await manager.initialize()

            # 模拟 list_voices 函数
            with patch("edge_tts.list_voices", return_value=[
                {"Name": "zh-CN-XiaoxiaoNeural", "Gender": "Female"},
            ]):
                voices = await manager.list_voices()
                assert len(voices) == 1

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """测试关闭"""
        manager = TTSManager(TTSConfig(engine="mock"))
        await manager.initialize()
        await manager.shutdown()
        assert not manager.is_initialized


if __name__ == "__main__":
    pytest.main([__file__, "-v"])