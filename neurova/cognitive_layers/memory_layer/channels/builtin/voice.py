"""
VoiceChannel — 语音通道（语音转写记忆检索）

检索语音转写记忆（用户通过语音说过的内容）。
"""
from typing import Any, Dict, List, Optional

from ..base import BaseChannel, ChannelMetadata, ChannelResult


class VoiceChannel(BaseChannel):
    """语音通道：检索语音转写记忆"""

    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="voice",
            display_name="语音通道",
            description="检索语音转写记忆",
            capabilities=["voice", "asr", "transcription"],
        )

    async def retrieve(
        self,
        query: str,
        limit: int = 10,
        weight: float = 1.0,
        **kwargs
    ) -> List[ChannelResult]:
        memory_manager = kwargs.get("memory_manager")
        if not memory_manager:
            return []

        try:
            all_memories = memory_manager.get_all_memories()
            voice_memories = []

            for mem in all_memories:
                mem_type = mem.get("memory_type", "")
                meta = mem.get("metadata", {})
                content = mem.get("content", "")

                # 筛选语音转写记忆
                if mem_type == "asr_transcription" or meta.get("record"):
                    if query.lower() in content.lower() or not query.strip():
                        record_data = meta.get("record", {})
                        confidence = record_data.get("confidence", 0.5)

                        score = (confidence * 0.7 + 0.3) * weight

                        voice_memories.append(ChannelResult(
                            memory_id=mem.get("id", ""),
                            content=content,
                            score=score,
                            channel="voice",
                            metadata={
                                "confidence": confidence,
                                "engine": record_data.get("engine", "unknown"),
                                "language": record_data.get("language", "unknown"),
                                "emotion": record_data.get("emotion_label"),
                            },
                        ))

            voice_memories.sort(key=lambda m: m.score, reverse=True)
            return voice_memories[:limit]

        except Exception as e:
            self._logger.debug(f"语音通道检索失败: {e}")
            return []
