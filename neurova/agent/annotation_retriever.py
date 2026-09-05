"""AnnotationRetrieverAdapter - 标注检索器适配器（P2 标注闭环消费侧）

把人工标注（AnnotationStore）接入 MemoryRetrievalChain 检索链，
作为最高优先级检索器（priority 5）：人工修正的精准答案权威性
高于一切自动检索源（Unified/MoE/Knowledge）。

- 命中 → memories 承载精准答案（content=answer，title=question，
  metadata 标 annotation 溯源），quality=1.0（人工定标）
- 未命中 → 空结果（quality=0，链继续走后续检索器）
- store 故障 → FAILED 空结果（不拖垮链）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class AnnotationRetrieverAdapter:
    """标注检索器：人工标注 → 记忆条目（最高权威检索源）。"""

    def __init__(self, store, user: Optional[Dict[str, Any]] = None):
        """
        参数:
            store: AnnotationStore 实例（需可配 match_annotation 命中）
            user: 当前用户字典（预留透传）
        """
        self._store = store
        self._user = user
        self._name = "AnnotationRetriever"
        self._priority = 5  # 最高权威：人工修正 > 一切自动检索源

    @property
    def name(self) -> str:
        return self._name

    @property
    def priority(self) -> int:
        return self._priority

    async def retrieve(self, context) -> Any:
        """执行标注检索（归一精确 → 归一子串兜底）。"""
        from neurova.agent.memory_retrieval_chain import RetrievalQuality, RetrievalResult

        try:
            from neurova.core.annotation_store import match_annotation

            ann = match_annotation(self._store, context.query)
            if ann is None:
                return RetrievalResult(
                    memories=[],
                    source=self._name,
                    quality=0.0,
                    quality_level=RetrievalQuality.FAILED,
                    retrieval_time=0.0,
                    metadata={"annotation": False},
                )

            memory_entry = {
                "content": ann.get("answer", ""),
                "title": ann.get("question", ""),
                "metadata": {
                    "annotation": True,
                    "annotation_id": ann.get("id", ""),
                    "source": "annotation",
                },
            }
            return RetrievalResult(
                memories=[memory_entry],
                source=self._name,
                quality=1.0,  # 人工定标
                quality_level=RetrievalQuality.EXCELLENT,
                retrieval_time=0.0,
                metadata={"annotation": True},
            )
        except Exception as e:  # noqa: BLE001 — store 故障不拖垮检索链
            logger.warning("标注检索失败（隔离为空结果）: %s", e)
            return RetrievalResult(
                memories=[],
                source=self._name,
                quality=0.0,
                quality_level=RetrievalQuality.FAILED,
                retrieval_time=0.0,
                metadata={"annotation": False, "error": str(e)},
            )


def register_annotation_retriever(chain, store=None) -> bool:
    """chat_pipeline 装配点：把标注适配器挂到检索链最高优先级。

    与 KnowledgeRetrieverAdapter 同位接入；store 缺省取进程级单例。
    返回 True 表示注册成功（失败抛给调用方 try/except 降级跳过）。
    """
    if store is None:
        from neurova.core import annotation_store as ann_mod

        store = ann_mod.get_annotation_store()
    adapter = AnnotationRetrieverAdapter(store)
    chain.add_retriever(adapter)
    return True
