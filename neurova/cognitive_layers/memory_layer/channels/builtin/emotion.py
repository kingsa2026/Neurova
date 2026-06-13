"""
EmotionChannel — 情感通道（情感相似度）

检索与查询文本情感相似的记忆。
"""

from typing import List

from ..base import BaseChannel, ChannelMetadata, ChannelResult


class EmotionChannel(BaseChannel):
    """情感通道：基于情感相似度检索记忆"""

    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="emotion",
            display_name="情感通道",
            description="检索与查询情感相似的记忆",
            capabilities=["emotion", "sentiment"],
        )

    async def retrieve(self, query: str, limit: int = 10, weight: float = 1.0, **kwargs) -> List[ChannelResult]:
        memory_manager = kwargs.get("memory_manager")
        if not memory_manager:
            return []

        try:
            # 分析查询情感
            emotion_module = getattr(memory_manager, "emotion_module", None)
            if not emotion_module:
                return []

            emotion_state = emotion_module.analyze_text_emotion(query)
            if not emotion_state or getattr(emotion_state, "primary_emotion", None) is None:
                return []

            primary = emotion_state.primary_emotion
            if hasattr(primary, "value") and primary.value == "neutral":
                return []

            # 获取同情感类型的记忆
            memory_ids = emotion_module.get_emotional_memories(
                emotion_type=primary,
                min_intensity=0.3,
                limit=limit,
            )

            results = []
            for mid in memory_ids:
                mem_obj = memory_manager._memories.get(mid)
                if not mem_obj:
                    continue

                mem_emotion = emotion_module.get_emotion(mid)
                intensity = getattr(mem_emotion, "intensity", 0.5) if mem_emotion else 0.5

                results.append(
                    ChannelResult(
                        memory_id=mid,
                        content=mem_obj.content,
                        score=intensity * weight,
                        channel="emotion",
                        metadata={
                            "emotion": getattr(primary, "value", str(primary)),
                            "intensity": intensity,
                        },
                    )
                )

            return results

        except Exception as e:
            self._logger.debug("情感通道检索失败: %s", e)
            return []
