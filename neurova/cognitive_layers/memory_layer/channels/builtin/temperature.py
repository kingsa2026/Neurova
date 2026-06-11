"""
TemperatureChannel — 温度通道（热记忆优先）

检索温度最高的记忆，模拟"热记忆优先浮现"。
"""
from typing import Any, Dict, List, Optional

from ..base import BaseChannel, ChannelMetadata, ChannelResult


class TemperatureChannel(BaseChannel):
    """温度通道：按温度（活跃度）排序检索记忆"""

    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="temperature",
            display_name="温度通道",
            description="按记忆温度（活跃度）排序检索热记忆",
            capabilities=["temperature", "recency"],
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
            scored = []

            for mem in all_memories:
                temp = float(mem.get("temperature", 50))
                content = mem.get("content", "")
                score = (temp / 100.0) * weight

                scored.append(ChannelResult(
                    memory_id=mem.get("id", ""),
                    content=content,
                    score=score,
                    channel="temperature",
                    metadata={"temperature": temp},
                ))

            scored.sort(key=lambda m: m.score, reverse=True)
            return scored[:limit]

        except Exception as e:
            self._logger.debug(f"温度通道检索失败: {e}")
            return []
