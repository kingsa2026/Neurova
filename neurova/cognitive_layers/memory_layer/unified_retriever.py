"""
统一检索器 — 替代 MoE + RecallEngine + HebbManager 三路并行

深度模块设计：小接口（retrieve），深实现（整合多个检索源）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .cognitive_storage_engine import CognitiveStorageEngine, UnifiedMemoryNode

logger = logging.getLogger(__name__)


class UnifiedRetriever:
    """
    统一检索器 — 替代 MoE + RecallEngine + HebbManager 三路并行

    核心思想：
      1. 新数据：直接使用 CognitiveStorageEngine
      2. 旧数据：包装旧检索器作为子组件
      3. 去重排序：统一结果格式，去重，按分数排序
    """

    def __init__(
        self,
        engine: CognitiveStorageEngine,
        moe_router=None,
        recall_engine=None,
        hebb_manager=None,
    ):
        """
        初始化统一检索器

        Args:
            engine: CognitiveStorageEngine 实例
            moe_router: MoE 路由器（可选）
            recall_engine: RecallEngine 实例（可选）
            hebb_manager: HebbManager 实例（可选）
        """
        self.engine = engine
        self._moe = moe_router
        self._recall = recall_engine
        self._hebb = hebb_manager

        logger.info(
            "UnifiedRetriever 初始化完成，"
            f"MoE: {'是' if moe_router else '否'}, "
            f"Recall: {'是' if recall_engine else '否'}, "
            f"Hebb: {'是' if hebb_manager else '否'}"
        )

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        include_patterns: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        统一检索入口

        Args:
            query: 查询文本
            limit: 返回数量限制
            include_patterns: 是否包含结晶经验

        Returns:
            去重排序后的记忆列表
        """
        results: List[Dict[str, Any]] = []

        # 方案A：直接用 CognitiveStorageEngine（新数据）
        engine_results = self.engine.retrieve(query, limit=limit)
        results.extend([self._node_to_dict(n) for n in engine_results])

        # 方案B：兼容旧检索器（迁移期间）
        if self._moe:
            try:
                moe_results = self._moe.retrieve(query)
                results.extend(moe_results)
            except Exception as e:
                logger.warning("MoE 检索失败: %s", e)

        if self._recall:
            try:
                recall_results = self._recall.recall_flat(query, limit=limit)
                # RecalledMemory 对象需要转换为字典格式
                for rm in recall_results:
                    if hasattr(rm, "to_dict"):
                        results.append(rm.to_dict())
                    else:
                        results.append(rm)
            except Exception as e:
                logger.warning("Recall 检索失败: %s", e)

        if self._hebb:
            try:
                hebbs = self._hebb.retrieve_neurova_hebb(query)
                hebb_results = [self._hebb.convert_to_recall_format(h) for h in hebbs]
                results.extend(hebb_results)
            except Exception as e:
                logger.warning("Hebb 检索失败: %s", e)

        # 去重 + 排序
        return self._dedup_rank(results, limit)

    def _node_to_dict(self, node: UnifiedMemoryNode) -> Dict[str, Any]:
        """
        将 UnifiedMemoryNode 转换为标准字典格式

        Args:
            node: UnifiedMemoryNode 实例

        Returns:
            标准字典格式
        """
        return {
            "id": node.id,
            "content": node.content,
            "score": node.temperature,
            "source": node.memory_type.value,
            "temperature": node.temperature,
            "category": node.category,
            "metadata": node.metadata,
        }

    def _dedup_rank(
        self,
        results: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        去重并排序结果

        Args:
            results: 原始结果列表
            limit: 返回数量限制

        Returns:
            去重排序后的结果
        """
        seen: set = set()
        unique: List[Dict[str, Any]] = []

        for r in results:
            # 使用内容前100字符作为去重键
            key = r.get("content", "")[:100]
            if key not in seen:
                seen.add(key)
                unique.append(r)

        # 按分数降序排序
        unique.sort(key=lambda x: x.get("score", 0), reverse=True)

        return unique[:limit]
