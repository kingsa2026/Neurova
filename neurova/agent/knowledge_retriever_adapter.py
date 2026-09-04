"""KnowledgeRetrieverAdapter - 知识库检索器适配器

将知识库 repository.search_visible_items 接入 MemoryRetrievalChain，
使 Agent 对话时自动检索用户可见知识（隔离透传 + 质量评分）。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class KnowledgeRetrieverAdapter:
    """适配知识库 Repository，作为检索链的一级检索器。

    优先级 25：在 UnifiedRetriever(10)/MoE(20) 之后、Cache(30) 之前，
    即优先保证记忆与 MoE 路由，知识库作为补充知识源。
    """

    def __init__(self, repo, user: Optional[Dict[str, Any]] = None):
        """
        参数:
            repo: 知识库 Repository 实例（需有 search_visible_items 方法）
            user: 当前用户字典（可后续透传覆盖）
        """
        self._repo = repo
        self._user = user
        self._name = "KnowledgeRetriever"
        self._priority = 25  # 中等偏下优先级（记忆 >> 知识）

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    async def retrieve(self, context) -> Any:
        """执行知识库检索（走用户可见性过滤）"""
        from neurova.agent.memory_retrieval_chain import RetrievalResult, RetrievalQuality

        start_time = time.monotonic()

        try:
            # 用户隔离：检索上下文注入 user_id + role（admin 需全可见；metadata 可携带 agent_id）
            user: Optional[Dict[str, Any]] = None
            if getattr(context, "user_id", None):
                user = {"user_id": str(context.user_id)}
                role = (getattr(context, "metadata", None) or {}).get("role")
                if role:
                    user["role"] = str(role)

            metadata = getattr(context, "metadata", None) or {}
            agent_id = metadata.get("agent_id")

            # 调用 repository（兼容同步/async）
            result = self._repo.search_visible_items(
                user=user,
                query=context.query,
                scope="all",
                agent_id=agent_id,
                limit=context.limit,
            )
            if asyncio.iscoroutine(result):
                knowledge_items = await result
            else:
                knowledge_items = result

            elapsed = time.monotonic() - start_time

            if not knowledge_items:
                return RetrievalResult(
                    memories=[],
                    source=self._name,
                    quality=0.0,
                    quality_level=RetrievalQuality.FAILED,
                    retrieval_time=elapsed,
                    metadata={"retriever_type": "knowledge", "hits": 0},
                )

            # 归一化为 memories 载荷（与记忆条目字段一致：content/title 等）
            memories = [self._normalize_item(item) for item in knowledge_items]

            quality = self.get_quality_score(knowledge_items, context.query)
            quality_level = self._quality_from_score(quality)

            return RetrievalResult(
                memories=memories,
                source=self._name,
                quality=quality,
                quality_level=quality_level,
                retrieval_time=elapsed,
                metadata={"retriever_type": "knowledge", "hits": len(memories)},
            )

        except Exception as e:
            logger.error("KnowledgeRetriever failed: %s", e)
            raise

    def get_quality_score(self, results: List[Dict[str, Any]], query: str) -> float:
        """评估知识检索质量：数量 + 标题/内容关键词相关度"""
        if not results:
            return 0.0

        count_score = min(len(results) / 10, 1.0)

        query_keywords = set((query or "").lower().split())
        relevance_score = 0.0
        if query_keywords:
            total_overlap = 0.0
            n = 0
            for item in results:
                title = (item.get("title") or "").lower()
                content = (item.get("content") or "").lower()
                combined = set(title.split()) | set(content.split())
                overlap = len(query_keywords.intersection(combined))
                if combined:
                    total_overlap += overlap / len(query_keywords)
                    n += 1
            relevance_score = total_overlap / n if n else 0.0

        quality = 0.6 * count_score + 0.4 * relevance_score
        return min(max(quality, 0.0), 1.0)

    def _quality_from_score(self, score: float) -> Any:
        """质量分数 → 等级（与 UnifiedRetrieverAdapter 阈值一致）"""
        from neurova.agent.memory_retrieval_chain import RetrievalQuality

        if score >= 0.9:
            return RetrievalQuality.EXCELLENT
        if score >= 0.7:
            return RetrievalQuality.GOOD
        if score >= 0.4:
            return RetrievalQuality.FAIR
        if score > 0.0:
            return RetrievalQuality.POOR
        return RetrievalQuality.FAILED

    # P1-9 来源信任分级: 知识条目 source → origin 闭集映射。
    # fail-safe：未知来源一律 untrusted（外部可写面，绝不静默升权）。
    # kb_builder 是 web_reach 抓取入口 → untrusted；agent 自产/结晶 → agent。
    _ORIGIN_SOURCES_OWNER = {"user_upload", "manual", "local_import"}
    _ORIGIN_SOURCES_AGENT = {"agent_generated", "crystallized"}

    @classmethod
    def _map_origin(cls, source: str) -> str:
        s = (source or "").strip().lower()
        if s in cls._ORIGIN_SOURCES_OWNER:
            return "owner"
        if s in cls._ORIGIN_SOURCES_AGENT:
            return "agent"
        return "untrusted"

    @classmethod
    def _normalize_item(cls, item: Dict[str, Any]) -> Dict[str, Any]:
        """单条知识条目 → 检索链 memories 载荷（含 origin 信任级）"""
        return {
            "memory_id": item.get("knowledge_id"),
            "content": item.get("content") or item.get("title") or "",
            "title": item.get("title", ""),
            "category": item.get("category", "knowledge"),
            "tags": item.get("tags", []),
            "source": item.get("source", "knowledge"),
            "confidence": item.get("confidence", 0.5),
            "visibility": item.get("visibility", "private"),
            "knowledge_id": item.get("knowledge_id"),
            "origin": cls._map_origin(item.get("source", "")),
        }
