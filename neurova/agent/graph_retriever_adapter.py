"""GraphRetriever 适配器（工单 013，灭 B04）——多跳事实在对话链上的一等位置。

责任链契约与同级检索器一致：`name` / `priority` / `async retrieve(context)` /
`get_quality_score`。priority 27 落在时效事实（26）与缓存（30）之间：
多跳推出来的说法比单条时效事实更间接，权威性不该更高，但它带的是别处给不出的关系。

数据源是 `GraphFactWalker`（底座递归 CTE），不是 JSON 属性图——所以这条分支与
时效分支读同一份真相，命中还会回写注入账（G07）；不回写就等于用量账缺一条路。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List


class GraphRetrieverAdapter:
    """把多跳走查的终点事实转成检索链标准 memory dict。"""

    def __init__(self, walker: Any):
        self._walker = walker
        self._name = "GraphRetriever"
        self._priority = 27

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    async def retrieve(self, context) -> Any:
        from neurova.agent.memory_retrieval_chain import RetrievalQuality, RetrievalResult

        start = time.monotonic()
        hops = self._walker.walkFromQuery(context.query, limit=context.limit)
        elapsed = time.monotonic() - start
        if not hops:
            return RetrievalResult(
                memories=[], source=self._name, quality=0.0,
                quality_level=RetrievalQuality.FAILED, retrieval_time=elapsed,
                metadata={"retriever_type": "graph", "hits": 0},
            )

        memories = [self._hopToDict(h) for h in hops[: context.limit]]
        self._recordInjection([h["id"] for h in hops[: context.limit]])
        quality = self.get_quality_score(memories, context.query)
        return RetrievalResult(
            memories=memories, source=self._name, quality=quality,
            quality_level=self._qualityFromScore(quality), retrieval_time=elapsed,
            metadata={"retriever_type": "graph", "hits": len(memories)},
        )

    def _recordInjection(self, factIds: List[str]) -> None:
        """注入账写不回来自读面——但缺了它，图这条路用得多不多就永远没人知道。"""
        store = getattr(self._walker, "factStore", None)
        if store is None or not factIds:
            return
        store.recordInjection(factIds)

    @staticmethod
    def _hopToDict(hop: Dict[str, Any]) -> Dict[str, Any]:
        """内容带完整路径：只给终点三元组，读的人无法知道它是**沿着谁**推出来的。"""
        return {
            "id": hop["id"],
            "content": hop["path"],
            "type": "graph_fact",
            "hops": hop["hop"],
            "created_at": "",
        }

    def get_quality_score(self, results: List[Dict[str, Any]], query: str) -> float:
        """跳数越近越可信（每多一跳就多一次"客体等于主体名"的巧合风险）。"""
        if not results:
            return 0.0
        closest = min(int(r.get("hops", 2)) for r in results)
        score = 0.85 - 0.15 * max(closest - 2, 0)
        return round(max(min(score, 1.0), 0.1), 4)

    @staticmethod
    def _qualityFromScore(score: float):
        from neurova.agent.memory_retrieval_chain import RetrievalQuality

        if score >= 0.8:
            return RetrievalQuality.EXCELLENT
        if score >= 0.5:
            return RetrievalQuality.GOOD
        return RetrievalQuality.FAIR
