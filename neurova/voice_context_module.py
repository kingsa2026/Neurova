"""
VoiceContextModule — 语音上下文集成深度模块

集中处理语音元数据到上下文的集成，解决：
1. 语音元数据丢失问题
2. VoiceMemoryBridge 隔离问题
3. 语音情感未注入上下文问题

设计原则：
- 深模块：小接口，深实现
- 接缝设计：在语音处理与上下文构建之间创建清晰接缝
- 适配器模式：适配 VoiceMemoryBridge 与 ContextPool 的接口差异
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = get_logger(__name__)


@dataclass
class VoiceContext:
    """语音上下文数据类"""

    # ASR 元数据
    text: str
    confidence: float = 0.0
    language: str = "zh"
    engine: str = "unknown"
    duration_ms: int = 0

    # 情感分析
    emotion: Optional[Dict[str, Any]] = None

    # 音频元数据
    audio_metadata: Optional[Dict[str, Any]] = None

    # 时间戳
    timestamp: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "text": self.text,
            "confidence": self.confidence,
            "language": self.language,
            "engine": self.engine,
            "duration_ms": self.duration_ms,
            "emotion": self.emotion,
            "audio_metadata": self.audio_metadata,
            "timestamp": self.timestamp,
        }


class VoiceContextModule:
    """语音上下文集成模块

    提供小接口、深实现，集中处理语音上下文相关逻辑：
    - build_voice_context(): 构建语音上下文
    - inject_metadata(): 注入元数据到上下文池
    - analyze_emotion(): 分析语音情感
    - get_voice_context(): 获取语音上下文
    """

    def __init__(self):
        self._current_context: Optional[VoiceContext] = None
        self._emotion_analyzer = None
        self._init_emotion_analyzer()

    def _init_emotion_analyzer(self):
        """初始化情感分析器"""
        try:
            from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule

            self._emotion_analyzer = EmotionModule()
        except Exception as e:
            logger.debug("情感分析器初始化跳过: %s", e)
            self._emotion_analyzer = None

    def build_voice_context(
        self,
        asr_result: Optional[Dict[str, Any]] = None,
        tts_result: Optional[Dict[str, Any]] = None,
        audio_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建语音上下文

        Args:
            asr_result: ASR 转写结果
            tts_result: TTS 合成结果
            audio_metadata: 音频元数据

        Returns:
            语音上下文字典
        """
        from datetime import datetime, timezone

        context = VoiceContext(
            text="",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        if asr_result:
            context.text = asr_result.get("text", "")
            context.confidence = asr_result.get("confidence", 0.0)
            context.language = asr_result.get("language", "zh")
            context.engine = asr_result.get("engine", "unknown")
            context.duration_ms = asr_result.get("duration_ms", 0)

        if tts_result:
            # TTS 结果作为元数据附加
            context.audio_metadata = {
                "tts_engine": tts_result.get("engine", "unknown"),
                "tts_voice": tts_result.get("voice", "default"),
                "tts_duration_ms": tts_result.get("duration_ms", 0),
                "audio_size_bytes": tts_result.get("audio_size_bytes", 0),
            }

        if audio_metadata:
            if context.audio_metadata:
                context.audio_metadata.update(audio_metadata)
            else:
                context.audio_metadata = audio_metadata

        # 分析情感
        if context.text:
            context.emotion = self.analyze_emotion(context.text)

        self._current_context = context
        return context.to_dict()

    def analyze_emotion(self, text: str) -> Dict[str, Any]:
        """分析语音情感

        Args:
            text: 要分析的文本

        Returns:
            情感分析结果
        """
        if not text or not self._emotion_analyzer:
            return {
                "primary_emotion": "neutral",
                "confidence": 0.0,
                "secondary_emotions": [],
            }

        try:
            emotion_state = self._emotion_analyzer.analyze_text_emotion(text)
            if emotion_state:
                return {
                    "primary_emotion": emotion_state.primary_emotion.value,
                    "confidence": emotion_state.intensity,
                    "secondary_emotions": (
                        [e.value for e in emotion_state.secondary_emotions]
                        if hasattr(emotion_state, "secondary_emotions")
                        else []
                    ),
                    "valence": emotion_state.valence,
                    "arousal": emotion_state.arousal,
                }
        except Exception as e:
            logger.debug("情感分析失败: %s", e)

        return {
            "primary_emotion": "neutral",
            "confidence": 0.0,
            "secondary_emotions": [],
        }

    def inject_metadata(
        self,
        context_pool: Any,
        voice_context: Dict[str, Any],
    ):
        """注入语音元数据到上下文池

        Args:
            context_pool: ContextPool 实例
            voice_context: 语音上下文字典
        """
        try:
            from neurova.context_pool import ContextInput, ContextSource

            # 构建语音上下文内容
            content_parts = []

            # ASR 信息
            if voice_context.get("text"):
                content_parts.append(f"语音识别文本: {voice_context['text']}")

            if voice_context.get("confidence", 0) > 0:
                content_parts.append(f"识别置信度: {voice_context['confidence']:.2f}")

            if voice_context.get("language"):
                content_parts.append(f"语言: {voice_context['language']}")

            if voice_context.get("engine"):
                content_parts.append(f"识别引擎: {voice_context['engine']}")

            # 情感信息
            emotion = voice_context.get("emotion")
            if emotion and emotion.get("primary_emotion") != "neutral":
                content_parts.append(
                    f"语音情感: {emotion['primary_emotion']} " f"(置信度: {emotion.get('confidence', 0):.2f})"
                )

            # 音频元数据
            audio_meta = voice_context.get("audio_metadata")
            if audio_meta:
                if audio_meta.get("tts_engine"):
                    content_parts.append(f"TTS引擎: {audio_meta['tts_engine']}")
                if audio_meta.get("tts_voice"):
                    content_parts.append(f"TTS音色: {audio_meta['tts_voice']}")

            if content_parts:
                content = "\n".join(content_parts)

                # 添加语音上下文到 ContextPool
                context_pool.add_context(
                    ContextInput(
                        source=ContextSource.MULTIMODAL,
                        content=content,
                        priority=70,  # 语音上下文中等优先级
                        metadata={
                            "type": "voice_context",
                            "confidence": voice_context.get("confidence", 0),
                            "language": voice_context.get("language", ""),
                            "engine": voice_context.get("engine", ""),
                        },
                    )
                )

                logger.debug("语音上下文已注入: %s 项信息", len(content_parts))

            # 语音情感独立注入到 ContextSource.EMOTION
            emotion = voice_context.get("emotion")
            if emotion and emotion.get("primary_emotion") != "neutral":
                emotion_content = (
                    f"语音情感状态: {emotion['primary_emotion']} " f"(强度: {emotion.get('confidence', 0):.2f})"
                )
                if emotion.get("valence"):
                    valence_desc = "正面" if emotion["valence"] > 0 else "负面"
                    emotion_content += f", 效价: {valence_desc}"
                if emotion.get("arousal"):
                    arousal_desc = "激动" if emotion["arousal"] > 0.5 else "平静"
                    emotion_content += f", 唤醒度: {arousal_desc}"

                context_pool.add_context(
                    ContextInput(
                        source=ContextSource.EMOTION,
                        content=emotion_content,
                        priority=60,  # 情感上下文中等偏低优先级
                        metadata={
                            "type": "voice_emotion",
                            "primary_emotion": emotion["primary_emotion"],
                            "confidence": emotion.get("confidence", 0),
                            "valence": emotion.get("valence", 0),
                            "arousal": emotion.get("arousal", 0),
                        },
                    )
                )
                logger.debug("语音情感已注入 EMOTION 上下文: %s", emotion['primary_emotion'])

        except Exception as e:
            logger.warning("注入语音上下文失败: %s", e)

    def get_voice_context(self) -> Optional[Dict[str, Any]]:
        """获取当前语音上下文

        Returns:
            语音上下文字典，如果没有则返回 None
        """
        if self._current_context:
            return self._current_context.to_dict()
        return None

    def clear_voice_context(self):
        """清除当前语音上下文"""
        self._current_context = None


# 单例管理
_voice_context_module_instance: Optional[VoiceContextModule] = None


def get_voice_context_module() -> VoiceContextModule:
    """获取 VoiceContextModule 单例"""
    global _voice_context_module_instance
    if _voice_context_module_instance is None:
        _voice_context_module_instance = VoiceContextModule()
    return _voice_context_module_instance


def reset_voice_context_module():
    """重置 VoiceContextModule 单例"""
    global _voice_context_module_instance
    _voice_context_module_instance = None
