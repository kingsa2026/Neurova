# -*- coding: utf-8 -*-
"""TKG（时效知识图谱）检索适配器（补课 5.2）。

TemporalKnowledgeGraph 此前是全仓零实例化的孤岛模块——本适配器把它
接入 MemoryRetrievalChain 作为补充知识源。

- priority=26：在 KnowledgeRetriever(25) 之后、Cache(30) 之前
  （记忆 >> 知识库 >> TKG 事实 >> 缓存）
- 检索调 query_current()（只取当前有效事实，时效语义由 TKG 自管）
- 事实转 dict：{id, content: "subject predicate object", ...}
"""
import asyncio
import time
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class TKGRetrieverAdapter:
    """适配 TemporalKnowledgeGraph，作为检索链的事实级补充源。"""

    def __init__(self, tkg):
        """
        参数:
            tkg: TemporalKnowledgeGraph 实例（需有 query_current 方法）
        """
        self._tkg = tkg
        self._name = "TKGRetriever"
        self._priority = 26

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    async def retrieve(self, context) -> Any:
        """执行 TKG 事实检索"""
        from neurova.agent.memory_retrieval_chain import RetrievalResult, RetrievalQuality

        start_time = time.monotonic()

        try:
            # query_tkg_for_context：关键词抽取 + 时效窗口 + 置信度排序，
            # 直接返回 dict 列表（query_current 只按 S/P/O 精确匹配，不适合文本查询）
            result = self._tkg.query_tkg_for_context(context.query, max_facts=context.limit)
            if asyncio.iscoroutine(result):
                facts = await result
            else:
                facts = result

            elapsed = time.monotonic() - start_time

            if not facts:
                return RetrievalResult(
                    memories=[],
                    source=self._name,
                    quality=0.0,
                    quality_level=RetrievalQuality.FAILED,
                    retrieval_time=elapsed,
                    metadata={"retriever_type": "tkg", "hits": 0},
                )

            memories = [self._fact_to_dict(f) for f in facts[: context.limit]]
            quality = self.get_quality_score(memories, context.query)
            quality_level = self._quality_from_score(quality)

            return RetrievalResult(
                memories=memories,
                source=self._name,
                quality=quality,
                quality_level=quality_level,
                retrieval_time=elapsed,
                metadata={"retriever_type": "tkg", "hits": len(memories)},
            )

        except Exception as e:
            logger.error("TKGRetriever failed: %s", e)
            raise

    @staticmethod
    def _fact_to_dict(fact: Any) -> Dict[str, Any]:
        """TemporalFact（dict 或对象）→ 检索链标准 memory dict。"""
        if isinstance(fact, dict):
            subject = fact.get("subject", "")
            predicate = fact.get("predicate", "")
            object_ = fact.get("object", "")
            fid = fact.get("id", "")
            created = fact.get("valid_from", "")
        else:
            subject = getattr(fact, "subject", "")
            predicate = getattr(fact, "predicate", "")
            object_ = getattr(fact, "object", "")
            fid = getattr(fact, "id", "")
            created = getattr(fact, "valid_from", "") or ""
        content = " ".join(p for p in (subject, predicate, object_) if p)
        return {
            "id": fid,
            "content": content,
            "type": "tkg_fact",
            "created_at": str(created),
        }

    def get_quality_score(self, results: List[Dict[str, Any]], query: str) -> float:
        """评估 TKG 检索质量：数量 + subject/predicate/object 关键词相关度"""
        if not results:
            return 0.0

        count_score = min(len(results) / 10, 1.0)

        query_keywords = set((query or "").lower().split())
        relevance_score = 0.0
        if query_keywords:
            total_overlap = 0.0
            n = 0
            for item in results:
                content = (item.get("content") or "").lower()
                combined = set(content.split())
                overlap = len(query_keywords.intersection(combined))
                if combined:
                    total_overlap += overlap / len(query_keywords)
                n += 1
            if n:
                relevance_score = total_overlap / n

        return min(count_score * 0.3 + relevance_score * 0.7, 1.0)

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
