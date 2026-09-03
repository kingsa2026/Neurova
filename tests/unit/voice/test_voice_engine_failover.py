"""
VoiceEngine 自动选择与故障转移测试

测试 VoiceEngine 的自动引擎选择和故障转移机制。
使用 conftest.py 中的共享 fixtures。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from neurova.voice_engine import VoiceEngine, VoiceEngineType, VoiceResult, VoiceEngineFactory


class TestVoiceEngineAutoSelection:
    """测试自动引擎选择"""

    def test_auto_select_first_available(self, available_engine):
        """应选择第一个可用的引擎"""
        from neurova.voice_engine import AutoVoiceEngine

        engines = [available_engine]
        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engines=engines,
        )

        assert auto.current_engine is available_engine
        assert auto.is_available() is True

    def test_auto_skip_unavailable(self, unavailable_engine, available_engine):
        """应跳过不可用的引擎，选择下一个可用的"""
        from neurova.voice_engine import AutoVoiceEngine

        engines = [unavailable_engine, available_engine]
        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engines=engines,
        )

        assert auto.current_engine is available_engine
        assert auto.is_available() is True

    def test_auto_all_unavailable(self, unavailable_engine):
        """所有引擎不可用时，标记为不可用"""
        from neurova.voice_engine import AutoVoiceEngine

        engines = [unavailable_engine, unavailable_engine]
        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engines=engines,
        )

        assert auto.current_engine is None
        assert auto.is_available() is False

    def test_auto_empty_engines(self):
        """空引擎列表应标记为不可用"""
        from neurova.voice_engine import AutoVoiceEngine

        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engines=[],
        )

        assert auto.current_engine is None
        assert auto.is_available() is False


class TestVoiceEngineFailover:
    """测试故障转移"""

    @pytest.mark.asyncio
    async def test_failover_on_synthesize_failure(self, failing_engine, available_engine):
        """TTS 合成失败时应故障转移到下一个引擎"""
        from neurova.voice_engine import AutoVoiceEngine

        # 第一个引擎合成返回空数据（失败）
        engines = [failing_engine, available_engine]
        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engines=engines,
        )

        result = await auto.process(
            input_data="测试文本",
            operation="synthesize",
        )

        # 应该成功（从第二个引擎获取结果）
        assert result.error is None
        assert result.audio_data == b"audio data"
        # 应该已经故障转移到第二个引擎
        assert auto.current_engine is available_engine

    @pytest.mark.asyncio
    async def test_failover_on_transcribe_failure(self, failing_engine, available_engine):
        """ASR 识别失败时应故障转移到下一个引擎"""
        from neurova.voice_engine import AutoVoiceEngine

        engines = [failing_engine, available_engine]
        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.ASR,
            engines=engines,
        )

        result = await auto.process(
            input_data=b"audio data",
            operation="transcribe",
        )

        assert result.error is None
        assert result.text == "识别结果"
        assert auto.current_engine is available_engine

    @pytest.mark.asyncio
    async def test_failover_all_engines_fail(self, failing_engine):
        """所有引擎都失败时应返回错误"""
        from neurova.voice_engine import AutoVoiceEngine

        engines = [failing_engine, failing_engine]
        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engines=engines,
        )

        result = await auto.process(
            input_data="测试文本",
            operation="synthesize",
        )

        assert result.error is not None

    @pytest.mark.asyncio
    async def test_failover_engine_exception(self):
        """引擎抛出异常时应故障转移到下一个引擎"""
        from neurova.voice_engine import AutoVoiceEngine

        # 第一个引擎抛出异常
        broken_engine = MagicMock()
        broken_engine.is_initialized = True
        broken_engine.synthesize = AsyncMock(side_effect=RuntimeError("引擎崩溃"))

        # 第二个引擎正常
        good_engine = MagicMock()
        good_engine.is_initialized = True
        good_engine.synthesize = AsyncMock(return_value=b"recovered audio")

        engines = [broken_engine, good_engine]
        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engines=engines,
        )

        result = await auto.process(
            input_data="测试文本",
            operation="synthesize",
        )

        assert result.error is None
        assert result.audio_data == b"recovered audio"
        assert auto.current_engine is good_engine


class TestAutoVoiceEngineInfo:
    """测试 AutoVoiceEngine 信息查询"""

    def test_get_info_includes_engines(self, available_engine):
        """get_info 应包含引擎列表信息"""
        from neurova.voice_engine import AutoVoiceEngine

        engines = [available_engine]
        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engines=engines,
        )

        info = auto.get_info()
        assert info["engine_type"] == "tts"
        assert info["is_initialized"] is True
        assert info["available_engines"] == 1
        assert info["engine_class"] == "MagicMock"
        assert info["total_engines"] == 1

    def test_get_info_fallback_chain(self, available_engine, unavailable_engine):
        """get_info 应显示故障转移链"""
        from neurova.voice_engine import AutoVoiceEngine

        engines = [unavailable_engine, available_engine]
        auto = AutoVoiceEngine(
            engine_type=VoiceEngineType.TTS,
            engines=engines,
        )

        info = auto.get_info()
        assert info["available_engines"] == 1
        assert info["total_engines"] == 2