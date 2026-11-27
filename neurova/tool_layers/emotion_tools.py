# -*- coding: utf-8 -*-
"""emotion_analyze 工具族——从 neurova.tool_executor 拆出。

`_builtin_dispatch["emotion_analyze"]="_execute_emotion_analyze"` 不变；
优先 Agent.memory_manager._emotion_analyzer，否则
`get_emotion_analyzer_instance()`；不可用/异常回退 `_fallback_emotion_analyze`。
不顶层 import `neurova.tool_executor`。
"""
from typing import Dict

from neurova.core.logger import get_logger

__all__ = ["EmotionToolsMixin"]

logger = get_logger(__name__)


class EmotionToolsMixin:
    """emotion_analyze built-in; `_agent` 由 ToolExecutor 提供。"""

    async def _execute_emotion_analyze(self, params: Dict) -> Dict:
        """执行情感分析"""
        try:
            text = params.get("text", "")
            if not text:
                return {"error": "缺少分析文本"}

            # 优先使用 Agent 的 memory_manager 中的情感分析器
            emotion_analyzer = None
            if hasattr(self._agent, "memory_manager") and self._agent.memory_manager:
                emotion_analyzer = getattr(self._agent.memory_manager, "_emotion_analyzer", None)

            # 如果没有，使用全局实例
            if not emotion_analyzer:
                try:
                    from neurova.cognitive_layers.memory_layer.emotion import get_emotion_analyzer_instance

                    emotion_analyzer = get_emotion_analyzer_instance()
                except ImportError:
                    logger.warning("情感分析器模块不可用，使用简化实现")
                    return self._fallback_emotion_analyze(text)

            # 执行情感分析
            result = emotion_analyzer.analyze(text)

            return {
                "success": True,
                "primary_emotion": result.get("primary_emotion", "neutral"),
                "confidence": result.get("confidence", 0.0),
                "emotions": result.get("emotions", {}),
                "tags": result.get("tags", []),
                "score": result.get("score", 0.0),
                "text": text,
            }
        except Exception as e:
            logger.error("情感分析执行失败: %s", e)
            return self._fallback_emotion_analyze(text)

    def _fallback_emotion_analyze(self, text: str) -> Dict:
        """简化情感分析回退实现"""
        text_lower = text.lower()

        # 简单关键词匹配
        emotion_keywords = {
            "happy": ["开心", "高兴", "快乐", "愉快", "欣喜", "happy", "joy", "glad"],
            "sad": ["伤心", "难过", "悲伤", "忧伤", "sad", "sorrow", "unhappy"],
            "angry": ["生气", "愤怒", "恼火", "angry", "furious", "mad"],
            "surprise": ["惊讶", "惊喜", "意外", "surprise", "amazed"],
            "fear": ["害怕", "恐惧", "担心", "afraid", "fear", "scared"],
            "disgust": ["厌恶", "讨厌", "恶心", "disgust", "dislike"],
        }

        detected_emotion = "neutral"
        max_score = 0.0

        for emotion, keywords in emotion_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    score = 0.7 + (0.3 * (1.0 / (len(text) + 1)))
                    if score > max_score:
                        max_score = score
                        detected_emotion = emotion

        if detected_emotion == "neutral":
            return {
                "success": True,
                "primary_emotion": "neutral",
                "confidence": 0.5,
                "emotions": {"neutral": 1.0},
                "tags": ["neutral"],
                "score": 0.0,
                "text": text,
            }

        return {
            "success": True,
            "primary_emotion": detected_emotion,
            "confidence": max_score,
            "emotions": {detected_emotion: max_score, "neutral": 1.0 - max_score},
            "tags": [detected_emotion],
            "score": max_score - 0.5,
            "text": text,
        }
