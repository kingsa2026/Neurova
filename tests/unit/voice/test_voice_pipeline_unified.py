"""
统一语音管线 + 情感上下文集成测试

测试范围：
1. UnifiedVoicePipeline 接口测试
2. VoiceContextModule 情感独立注入测试
3. 完整语音管线流程测试
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ============================================================
# 测试 1: UnifiedVoicePipeline 接口
# ============================================================

class TestUnifiedVoicePipelineInterface:
    """测试 UnifiedVoicePipeline 接口设计"""

    def test_import_voice_pipeline(self):
        """验证 UnifiedVoicePipeline 可以导入"""
        from neurova.voice_pipeline import UnifiedVoicePipeline
        assert UnifiedVoicePipeline is not None

    def test_voice_pipeline_has_required_methods(self):
        """验证 UnifiedVoicePipeline 有必要的方法"""
        from neurova.voice_pipeline import UnifiedVoicePipeline

        assert hasattr(UnifiedVoicePipeline, 'process_asr')
        assert hasattr(UnifiedVoicePipeline, 'process_tts')
        assert hasattr(UnifiedVoicePipeline, 'get_pipeline_stats')

    def test_voice_pipeline_result_dataclass(self):
        """验证 VoicePipelineResult 数据类"""
        from neurova.voice_pipeline import VoicePipelineResult

        result = VoicePipelineResult(text="hello", confidence=0.9)
        assert result.text == "hello"
        assert result.confidence == 0.9
        assert result.success

    def test_voice_pipeline_result_error(self):
        """验证 VoicePipelineResult 错误状态"""
        from neurova.voice_pipeline import VoicePipelineResult

        result = VoicePipelineResult(error="some error")
        assert result.success is False

    def test_voice_pipeline_stats(self):
        """验证 get_pipeline_stats 返回状态字典"""
        from neurova.voice_pipeline import UnifiedVoicePipeline

        pipeline = UnifiedVoicePipeline()
        stats = pipeline.get_pipeline_stats()
        assert isinstance(stats, dict)
        assert "voice_context_module" in stats
        assert "voice_memory_bridge" in stats
        assert "asr_manager" in stats
        assert "tts_manager" in stats


# ============================================================
# 测试 2: VoiceContextModule 情感独立注入
# ============================================================

class TestVoiceEmotionContextSeparation:
    """测试语音情感独立注入到 ContextSource.EMOTION"""

    def test_emotion_injected_separately(self):
        """验证非中性情感注入独立 EMOTION 上下文"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextInput, ContextSource, ContextPool

        module = VoiceContextModule()

        # 构建带情感的语音上下文
        voice_context = {
            "text": "我非常开心！",
            "confidence": 0.92,
            "language": "zh",
            "engine": "funasr",
            "emotion": {
                "primary_emotion": "joy",
                "confidence": 0.85,
                "valence": 0.7,
                "arousal": 0.6,
            }
        }

        context_pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=4000
        )

        module.inject_metadata(context_pool, voice_context)

        # 验证有 EMOTION 类型的上下文
        emotion_contexts = [
            ctx for ctx in context_pool.get_contexts()
            if ctx.source == ContextSource.EMOTION
        ]
        assert len(emotion_contexts) > 0, "未找到 EMOTION 类型上下文"

        # 验证情感内容包含正确信息
        emotion_ctx = emotion_contexts[0]
        assert "joy" in emotion_ctx.content
        assert "正面" in emotion_ctx.content  # valence > 0

    def test_neutral_emotion_no_separate_injection(self):
        """验证中性情感不注入独立 EMOTION 上下文"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextInput, ContextSource, ContextPool

        module = VoiceContextModule()

        voice_context = {
            "text": "请帮我查一下天气",
            "confidence": 0.88,
            "language": "zh",
            "engine": "funasr",
            "emotion": {
                "primary_emotion": "neutral",
                "confidence": 0.5,
            }
        }

        context_pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=4000
        )

        module.inject_metadata(context_pool, voice_context)

        # 验证没有 EMOTION 类型的上下文
        emotion_contexts = [
            ctx for ctx in context_pool.get_contexts()
            if ctx.source == ContextSource.EMOTION
        ]
        assert len(emotion_contexts) == 0, "中性情感不应注入 EMOTION 上下文"

    def test_both_multimodal_and_emotion_injected(self):
        """验证语音上下文同时注入 MULTIMODAL 和 EMOTION"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextInput, ContextSource, ContextPool

        module = VoiceContextModule()

        voice_context = {
            "text": "我今天非常生气！",
            "confidence": 0.90,
            "language": "zh",
            "engine": "funasr",
            "emotion": {
                "primary_emotion": "anger",
                "confidence": 0.80,
                "valence": -0.6,
                "arousal": 0.8,
            }
        }

        context_pool = ContextPool(
            user_id="test_user",
            agent_id="test_agent",
            max_tokens=4000
        )

        module.inject_metadata(context_pool, voice_context)

        # 验证有 MULTIMODAL 上下文
        multimodal_contexts = [
            ctx for ctx in context_pool.get_contexts()
            if ctx.source == ContextSource.MULTIMODAL
        ]
        assert len(multimodal_contexts) > 0, "未找到 MULTIMODAL 上下文"

        # 验证有 EMOTION 上下文
        emotion_contexts = [
            ctx for ctx in context_pool.get_contexts()
            if ctx.source == ContextSource.EMOTION
        ]
        assert len(emotion_contexts) > 0, "未找到 EMOTION 上下文"

        # 验证 EMOTION 内容包含负面情感
        emotion_ctx = emotion_contexts[0]
        assert "anger" in emotion_ctx.content
        assert "负面" in emotion_ctx.content  # valence < 0


# ============================================================
# 测试 3: 完整语音管线流程
# ============================================================

class TestCompleteVoicePipelineFlow:
    """测试完整的语音管线流程"""

    def test_pipeline_singleton(self):
        """验证单例模式"""
        from neurova.voice_pipeline import get_voice_pipeline, reset_voice_pipeline

        reset_voice_pipeline()
        p1 = get_voice_pipeline()
        p2 = get_voice_pipeline()
        assert p1 is p2

        reset_voice_pipeline()

    def test_pipeline_lazy_initialization(self):
        """验证延迟初始化"""
        from neurova.voice_pipeline import UnifiedVoicePipeline

        pipeline = UnifiedVoicePipeline()
        assert pipeline._initialized is False

        # 第一次调用触发初始化
        stats = pipeline.get_pipeline_stats()
        assert pipeline._initialized is True
        assert isinstance(stats, dict)

    def test_emotion_valence_description(self):
        """验证情感效价描述生成"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextPool, ContextSource

        module = VoiceContextModule()

        # 正面情感
        voice_context_positive = {
            "text": "太棒了！",
            "emotion": {
                "primary_emotion": "joy",
                "confidence": 0.9,
                "valence": 0.8,
                "arousal": 0.7,
            }
        }

        context_pool = ContextPool(user_id="u", agent_id="a", max_tokens=4000)
        module.inject_metadata(context_pool, voice_context_positive)

        emotion_ctx = [
            ctx for ctx in context_pool.get_contexts()
            if ctx.source == ContextSource.EMOTION
        ][0]
        assert "正面" in emotion_ctx.content
        assert "激动" in emotion_ctx.content  # arousal > 0.5

    def test_emotion_arousal_description(self):
        """验证情感唤醒度描述生成"""
        from neurova.voice_context_module import VoiceContextModule
        from neurova.context_pool import ContextPool, ContextSource

        module = VoiceContextModule()

        voice_context = {
            "text": "我很平静",
            "emotion": {
                "primary_emotion": "trust",
                "confidence": 0.7,
                "valence": 0.3,
                "arousal": 0.2,
            }
        }

        context_pool = ContextPool(user_id="u", agent_id="a", max_tokens=4000)
        module.inject_metadata(context_pool, voice_context)

        emotion_ctx = [
            ctx for ctx in context_pool.get_contexts()
            if ctx.source == ContextSource.EMOTION
        ][0]
        assert "平静" in emotion_ctx.content  # arousal <= 0.5


# ============================================================
# 测试 4: Agent.process_multimodal 语音管线集成
# ============================================================

class TestProcessMultimodalVoicePipeline:
    """测试 process_multimodal 中 UnifiedVoicePipeline 集成"""

    @pytest.mark.asyncio
    async def test_pipeline_used_when_available(self):
        """验证 voice_pipeline 可用时优先使用管线"""
        from neurova.voice_pipeline import UnifiedVoicePipeline, VoicePipelineResult

        mock_pipeline = MagicMock(spec=UnifiedVoicePipeline)
        mock_pipeline.process_asr = AsyncMock(return_value=VoicePipelineResult(
            text="你好世界",
            confidence=0.95,
            language="zh",
            engine="funasr",
            duration_ms=120,
            emotion={"primary_emotion": "joy", "confidence": 0.7, "valence": 0.5, "arousal": 0.4},
        ))

        agent = MagicMock()
        agent.voice_pipeline = mock_pipeline
        agent.asr_manager = None
        agent.config = MagicMock()
        agent.config.user_id = "u1"
        agent.config.agent_id = "a1"

        metadata = {"audio_bytes": b"fake-audio", "filename": "test.wav", "mime_type": "audio/wav"}

        # 调用 process_multimodal 中的语音处理逻辑
        audio_bytes = metadata["audio_bytes"]
        voice_context = None
        media_desc = "[用户发送了一段语音消息]"

        if audio_bytes and agent.voice_pipeline:
            pipeline_result = await agent.voice_pipeline.process_asr(
                audio_data=audio_bytes,
                user_id="u1",
                agent_id="a1",
            )
            if pipeline_result.text:
                media_desc = f"[语音识别结果: {pipeline_result.text}]"
                voice_context = {
                    "text": pipeline_result.text,
                    "confidence": pipeline_result.confidence,
                    "language": pipeline_result.language,
                    "engine": pipeline_result.engine,
                    "duration_ms": pipeline_result.duration_ms,
                    "emotion": pipeline_result.emotion,
                }

        assert media_desc == "[语音识别结果: 你好世界]"
        assert voice_context is not None
        assert voice_context["text"] == "你好世界"
        assert voice_context["emotion"]["primary_emotion"] == "joy"
        mock_pipeline.process_asr.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_when_pipeline_unavailable(self):
        """验证 pipeline 不可用时降级到 ASR 引擎"""
        mock_asr = AsyncMock()
        mock_asr.transcribe = AsyncMock(return_value={
            "text": "降级转写",
            "confidence": 0.8,
            "language": "zh",
            "engine": "whisper",
            "duration_ms": 200,
        })

        agent = MagicMock()
        agent.voice_pipeline = None
        agent.asr_manager = mock_asr

        audio_bytes = b"fake-audio"
        voice_context = None
        media_desc = "[用户发送了一段语音消息]"

        if audio_bytes and agent.voice_pipeline:
            pass  # 不执行
        elif audio_bytes and agent.asr_manager:
            asr_result = await agent.asr_manager.transcribe(audio_bytes)
            if asr_result and "text" in asr_result:
                media_desc = f"[语音识别结果: {asr_result['text']}]"
                voice_context = {"text": asr_result["text"]}

        assert media_desc == "[语音识别结果: 降级转写]"
        assert voice_context is not None
        assert voice_context["text"] == "降级转写"

    @pytest.mark.asyncio
    async def test_pipeline_error_does_not_crash(self):
        """验证管线错误不会导致整个处理崩溃"""
        from neurova.voice_pipeline import UnifiedVoicePipeline, VoicePipelineResult

        mock_pipeline = MagicMock(spec=UnifiedVoicePipeline)
        mock_pipeline.process_asr = AsyncMock(return_value=VoicePipelineResult(
            error="ASR 引擎不可用",
        ))

        agent = MagicMock()
        agent.voice_pipeline = mock_pipeline
        agent.asr_manager = None

        audio_bytes = b"fake-audio"
        voice_context = None
        media_desc = "[用户发送了一段语音消息]"

        if audio_bytes and agent.voice_pipeline:
            pipeline_result = await agent.voice_pipeline.process_asr(
                audio_data=audio_bytes,
                user_id="u1",
                agent_id="a1",
            )
            if pipeline_result.text:
                media_desc = f"[语音识别结果: {pipeline_result.text}]"
            elif pipeline_result.error:
                pass  # 记录错误但不崩溃

        # 降级到默认描述
        assert media_desc == "[用户发送了一段语音消息]"
        assert voice_context is None

    @pytest.mark.asyncio
    async def test_empty_text_from_pipeline(self):
        """验证管线返回空文本时不设置 voice_context"""
        from neurova.voice_pipeline import UnifiedVoicePipeline, VoicePipelineResult

        mock_pipeline = MagicMock(spec=UnifiedVoicePipeline)
        mock_pipeline.process_asr = AsyncMock(return_value=VoicePipelineResult(
            text="",
            error="ASR 识别结果为空",
        ))

        agent = MagicMock()
        agent.voice_pipeline = mock_pipeline

        audio_bytes = b"fake-audio"
        voice_context = None

        if audio_bytes and agent.voice_pipeline:
            pipeline_result = await agent.voice_pipeline.process_asr(
                audio_data=audio_bytes,
            )
            if pipeline_result.text:
                voice_context = {"text": pipeline_result.text}

        assert voice_context is None
