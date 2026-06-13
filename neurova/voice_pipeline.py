"""
UnifiedVoicePipeline — 统一语音处理管线

解决语音系统碎片化问题：
1. ASR → 上下文 → 记忆 的统一入口
2. TTS → 上下文 → 记忆 的统一入口
3. 语音情感自动注入上下文
4. VoiceMemoryBridge 与上下文系统深度集成

设计原则：
- 深模块：小接口 (process_asr, process_tts)，深实现（自动编排 ASR/TTS/Context/Memory/Emotion）
- 单一入口：Agent 只需调用 pipeline.process_asr()，自动完成所有后续处理
- 接缝设计：在语音处理与上下文/记忆之间创建清晰接缝
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class VoicePipelineResult:
    """语音管线处理结果"""

    # ASR 结果
    text: str = ""
    confidence: float = 0.0
    language: str = "zh"
    engine: str = "unknown"
    duration_ms: int = 0

    # 情感分析结果
    emotion: Optional[Dict[str, Any]] = None

    # TTS 结果
    audio_data: Optional[bytes] = None
    tts_engine: str = "unknown"
    tts_voice: str = "default"
    tts_duration_ms: int = 0

    # 上下文注入状态
    context_injected: bool = False

    # 记忆记录状态
    memory_recorded: bool = False

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and (self.text or self.audio_data)


class UnifiedVoicePipeline:
    """统一语音处理管线

    统一 ASR → 上下文 → 记忆 的处理流程：
    - process_asr(): ASR 处理 + 情感分析 + 上下文注入 + 记忆记录
    - process_tts(): TTS 处理 + 上下文注入 + 使用记录
    - process_voice_interaction(): 完整语音交互（ASR + LLM + TTS）

    依赖：
    - VoiceContextModule: 语音上下文集成
    - VoiceMemoryBridge: 语音记忆桥接
    - ASRManager: ASR 引擎管理
    - TTSManager: TTS 引擎管理
    """

    def __init__(self):
        self._voice_context_module = None
        self._voice_memory_bridge = None
        self._asr_manager = None
        self._tts_manager = None
        self._initialized = False

    def _ensure_initialized(self):
        """延迟初始化依赖模块"""
        if self._initialized:
            return

        try:
            from neurova.voice_context_module import get_voice_context_module

            self._voice_context_module = get_voice_context_module()
        except Exception as e:
            logger.debug("VoiceContextModule 初始化跳过: %s", e)

        try:
            from neurova.voice_memory_bridge import VoiceMemoryBridge, VoiceMemoryConfig

            config = VoiceMemoryConfig()
            self._voice_memory_bridge = VoiceMemoryBridge(config=config)
        except Exception as e:
            logger.debug("VoiceMemoryBridge 初始化跳过: %s", e)

        try:
            from neurova.asr.manager import ASRManager

            self._asr_manager = ASRManager()
        except Exception as e:
            logger.debug("ASRManager 初始化跳过: %s", e)

        try:
            from neurova.tts.manager import TTSManager

            self._tts_manager = TTSManager()
        except Exception as e:
            logger.debug("TTSManager 初始化跳过: %s", e)

        self._initialized = True

    async def process_asr(
        self,
        audio_data: bytes,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        context_pool: Optional[Any] = None,
        **kwargs,
    ) -> VoicePipelineResult:
        """处理 ASR：识别 + 情感分析 + 上下文注入 + 记忆记录

        Args:
            audio_data: 音频数据
            user_id: 用户 ID
            agent_id: Agent ID
            context_pool: ContextPool 实例（可选，自动注入）
            **kwargs: 传递给 ASR 的额外参数

        Returns:
            VoicePipelineResult
        """
        self._ensure_initialized()
        result = VoicePipelineResult()

        # 1. ASR 识别
        try:
            if self._asr_manager:
                asr_result = await self._asr_manager.transcribe(audio_data, **kwargs)
                result.text = asr_result.get("text", "")
                result.confidence = asr_result.get("confidence", 0.0)
                result.language = asr_result.get("language", "zh")
                result.engine = asr_result.get("engine", "unknown")
                result.duration_ms = asr_result.get("duration_ms", 0)
            else:
                result.error = "ASRManager 不可用"
                return result
        except Exception as e:
            result.error = f"ASR 识别失败: {e}"
            logger.warning(result.error)
            return result

        if not result.text:
            result.error = "ASR 识别结果为空"
            return result

        # 2. 情感分析
        result.emotion = self._analyze_emotion(result.text)

        # 3. 构建语音上下文并注入
        asr_dict = {
            "text": result.text,
            "confidence": result.confidence,
            "language": result.language,
            "engine": result.engine,
            "duration_ms": result.duration_ms,
        }

        if self._voice_context_module and context_pool:
            try:
                voice_context = self._voice_context_module.build_voice_context(
                    asr_result=asr_dict,
                )
                # 注入情感
                if result.emotion:
                    voice_context["emotion"] = result.emotion

                self._voice_context_module.inject_metadata(context_pool, voice_context)
                result.context_injected = True
                logger.debug(f"语音上下文已注入 ContextPool")
            except Exception as e:
                logger.warning("语音上下文注入失败: %s", e)

        # 4. 记录到语音记忆
        if self._voice_memory_bridge and user_id and agent_id:
            try:
                memory_result = await self._voice_memory_bridge.record_asr_result(
                    asr_result=asr_dict,
                    user_id=user_id,
                    agent_id=agent_id,
                )
                result.memory_recorded = memory_result.success
                logger.debug(f"ASR 结果已记录到语音记忆")
            except Exception as e:
                logger.warning("语音记忆记录失败: %s", e)

        result.metadata = {
            "asr_dict": asr_dict,
            "emotion": result.emotion,
        }

        return result

    async def process_tts(
        self,
        text: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        context_pool: Optional[Any] = None,
        voice: Optional[str] = None,
        **kwargs,
    ) -> VoicePipelineResult:
        """处理 TTS：合成 + 上下文注入 + 使用记录

        Args:
            text: 要合成的文本
            user_id: 用户 ID
            agent_id: Agent ID
            context_pool: ContextPool 实例（可选，自动注入）
            voice: TTS 音色
            **kwargs: 传递给 TTS 的额外参数

        Returns:
            VoicePipelineResult
        """
        self._ensure_initialized()
        result = VoicePipelineResult()
        result.text = text

        # 1. TTS 合成
        start_time = datetime.now(timezone.utc)
        try:
            if self._tts_manager:
                tts_kwargs = dict(kwargs)
                if voice:
                    tts_kwargs["voice"] = voice

                audio_data = await self._tts_manager.synthesize(text, **tts_kwargs)
                result.audio_data = audio_data

                elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                result.tts_duration_ms = elapsed_ms
                result.tts_engine = getattr(self._tts_manager, "_active_engine_name", "unknown")
                result.tts_voice = voice or "default"
            else:
                result.error = "TTSManager 不可用"
                return result
        except Exception as e:
            result.error = f"TTS 合成失败: {e}"
            logger.warning(result.error)
            return result

        # 2. 构建语音上下文并注入
        tts_dict = {
            "engine": result.tts_engine,
            "voice": result.tts_voice,
            "duration_ms": result.tts_duration_ms,
            "audio_size_bytes": len(result.audio_data) if result.audio_data else 0,
        }

        if self._voice_context_module and context_pool:
            try:
                voice_context = self._voice_context_module.build_voice_context(
                    tts_result=tts_dict,
                )
                self._voice_context_module.inject_metadata(context_pool, voice_context)
                result.context_injected = True
                logger.debug(f"TTS 上下文已注入 ContextPool")
            except Exception as e:
                logger.warning("TTS 上下文注入失败: %s", e)

        # 3. 记录 TTS 使用
        if self._voice_memory_bridge and user_id and agent_id:
            try:
                memory_result = await self._voice_memory_bridge.record_tts_usage(
                    tts_result=tts_dict,
                    user_id=user_id,
                    agent_id=agent_id,
                )
                result.memory_recorded = memory_result.success
                logger.debug(f"TTS 使用已记录到语音记忆")
            except Exception as e:
                logger.warning("TTS 使用记录失败: %s", e)

        result.metadata = {
            "tts_dict": tts_dict,
        }

        return result

    def _analyze_emotion(self, text: str) -> Optional[Dict[str, Any]]:
        """分析文本情感"""
        if not self._voice_context_module:
            return None
        try:
            return self._voice_context_module.analyze_emotion(text)
        except Exception as e:
            logger.debug("情感分析失败: %s", e)
            return None

    def get_pipeline_stats(self) -> Dict[str, Any]:
        """获取管线状态统计"""
        self._ensure_initialized()
        return {
            "voice_context_module": self._voice_context_module is not None,
            "voice_memory_bridge": self._voice_memory_bridge is not None,
            "asr_manager": self._asr_manager is not None,
            "tts_manager": self._tts_manager is not None,
        }


# 单例管理
_pipeline_instance: Optional[UnifiedVoicePipeline] = None


def get_voice_pipeline() -> UnifiedVoicePipeline:
    """获取 UnifiedVoicePipeline 单例"""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = UnifiedVoicePipeline()
    return _pipeline_instance


def reset_voice_pipeline():
    """重置 UnifiedVoicePipeline 单例"""
    global _pipeline_instance
    _pipeline_instance = None
