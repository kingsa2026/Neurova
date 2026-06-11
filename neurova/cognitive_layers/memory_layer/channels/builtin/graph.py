"""
GraphChannel — 图通道（关系图谱）

通过记忆间的关系图谱进行检索。
"""
from typing import Any, Dict, List, Optional

from ..base import BaseChannel, ChannelMetadata, ChannelResult


class GraphChannel(BaseChannel):
    """图通道：基于关系图谱检索关联记忆"""

    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="graph",
            display_name="图通道",
            description="基于记忆关系图谱检索关联记忆",
            capabilities=["graph", "relation"],
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
                relations = mem.get("metadata", {}).get("relations", [])
                content = mem.get("content", "")
                # 关系数量作为分数
                rel_count = len(relations) if isinstance(relations, list) else 0
                score = min(1.0, rel_count * 0.1) * weight

                scored.append(ChannelResult(
                    memory_id=mem.get("id", ""),
                    content=content,
                    score=score,
                    channel="graph",
                    metadata={"relation_count": rel_count},
                ))

            scored.sort(key=lambda m: m.score, reverse=True)
            return scored[:limit]

        except Exception as e:
            self._logger.debug(f"图通道检索失败: {e}")
            return []
