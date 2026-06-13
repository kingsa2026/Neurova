"""
CategoryChannel — 分类通道（同类别记忆）

检索与查询推断类别相同的记忆。
"""

from typing import List

from ..base import BaseChannel, ChannelMetadata, ChannelResult


class CategoryChannel(BaseChannel):
    """分类通道：按类别匹配检索记忆"""

    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="category",
            display_name="分类通道",
            description="按记忆类别匹配检索同类记忆",
            capabilities=["category", "classification"],
        )

    async def retrieve(self, query: str, limit: int = 10, weight: float = 1.0, **kwargs) -> List[ChannelResult]:
        memory_manager = kwargs.get("memory_manager")
        if not memory_manager:
            return []

        try:
            all_memories = memory_manager.get_all_memories()
            scored = []

            for mem in all_memories:
                category = mem.get("category", "general")
                content = mem.get("content", "")
                # 类别匹配得分
                score = 0.5 * weight if category != "general" else 0.2 * weight

                scored.append(
                    ChannelResult(
                        memory_id=mem.get("id", ""),
                        content=content,
                        score=score,
                        channel="category",
                        metadata={"category": category},
                    )
                )

            scored.sort(key=lambda m: m.score, reverse=True)
            return scored[:limit]

        except Exception as e:
            self._logger.debug("分类通道检索失败: %s", e)
            return []
