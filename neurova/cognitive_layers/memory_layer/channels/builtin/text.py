"""
TextChannel — 文本通道（语义相似度）

基于关键词/TF-IDF 的文本匹配检索。
"""
from typing import Any, Dict, List, Optional

from ..base import BaseChannel, ChannelMetadata, ChannelResult


class TextChannel(BaseChannel):
    """文本通道：基于文本相似度检索记忆"""

    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="text",
            display_name="文本通道",
            description="基于文本关键词匹配和语义相似度检索记忆",
            capabilities=["text", "semantic", "keyword"],
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
            query_lower = query.lower()
            query_words = set(query_lower.split())
            scored = []

            for mem in all_memories:
                content = mem.get("content", "")
                content_lower = content.lower()

                # 关键词匹配得分
                if not query_words:
                    score = 0.1 * weight
                else:
                    matched = sum(1 for w in query_words if w in content_lower)
                    score = (matched / len(query_words)) * weight

                scored.append(ChannelResult(
                    memory_id=mem.get("id", ""),
                    content=content,
                    score=score,
                    channel="text",
                    metadata={"match_type": "keyword"},
                ))

            scored.sort(key=lambda m: m.score, reverse=True)
            return scored[:limit]

        except Exception as e:
            self._logger.debug(f"文本通道检索失败: {e}")
            return []
