"""
睡眠整合适配器 — 对接 CognitiveStorageEngine

桥接 SleepConsolidation（使用 MemoryRecord）和
CognitiveStorageEngine（使用 UnifiedMemoryNode）。

深度模块设计：小接口（run_consolidation），深实现（双向转换+批量更新）。
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any

from .cognitive_storage_engine import CognitiveStorageEngine, UnifiedMemoryNode
from .sleep import SleepConsolidation, MemoryRecord, MergeResult

logger = logging.getLogger(__name__)


class SleepConsolidationAdapter:
    """
    睡眠整合适配器 — 对接 CognitiveStorageEngine

    核心职责：
      1. 从 CognitiveStorageEngine 读取记忆 → 转为 MemoryRecord
      2. 运行 SleepConsolidation 整合流程
      3. 将整合结果写回 CognitiveStorageEngine（更新/归档/合并）
    """

    def __init__(
        self,
        engine: CognitiveStorageEngine,
        similarity_threshold: float = 0.7,
        archive_threshold: float = 20.0,
        decay_rate: float = 0.1,
    ):
        """
        初始化适配器

        Args:
            engine: CognitiveStorageEngine 实例
            similarity_threshold: 语义相似度阈值
            archive_threshold: 归档温度阈值（0-100）
            decay_rate: 衰减率
        """
        self.engine = engine
        self.consolidation = SleepConsolidation(
            similarity_threshold=similarity_threshold,
            archive_threshold=archive_threshold,
            decay_rate=decay_rate,
        )
        logger.info(
            f"SleepConsolidationAdapter 初始化: "
            f"archive_threshold={archive_threshold}"
        )

    def run_consolidation(
        self,
        limit: int = 1000,
        memory_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        执行完整的睡眠整合流程

        Args:
            limit: 最大处理记忆数
            memory_types: 要处理的记忆类型过滤（None = 全部）

        Returns:
            整合统计信息
        """
        # 1. 从引擎读取记忆
        raw_nodes = self._fetch_memories(limit, memory_types)
        if not raw_nodes:
            return {"status": "no_memories", "processed": 0}

        # 2. 转为 MemoryRecord
        records = [self._node_to_record(n) for n in raw_nodes]

        # 3. 运行整合
        consolidated, merge_results = self.consolidation.consolidate(records)

        # 4. 写回结果
        stats = self._apply_results(raw_nodes, consolidated, merge_results)

        logger.info(
            f"睡眠整合完成: 处理 {stats['processed']} 条, "
            f"合并 {stats['merged']} 条, 归档 {stats['archived']} 条"
        )
        return stats

    def _fetch_memories(
        self,
        limit: int,
        memory_types: Optional[List[str]],
    ) -> List[UnifiedMemoryNode]:
        """从引擎获取记忆"""
        filters = {}
        if memory_types:
            # 只取第一个类型过滤（SQLite 查询限制）
            filters["memory_type"] = memory_types[0]

        nodes = self.engine.retrieve("", limit=limit, filters=filters or None)
        return nodes

    def _node_to_record(self, node: UnifiedMemoryNode) -> MemoryRecord:
        """UnifiedMemoryNode → MemoryRecord"""
        return MemoryRecord(
            id=node.id,
            content=node.content,
            embedding=node.embedding or [],
            temperature=node.temperature,
            importance=node.metadata.get("importance", 0.5),
            emotion_score=node.metadata.get("emotion_score", 0.0),
            recall_count=node.access_count,
            created_at=node.created_at,
            categories=[node.category],
        )

    def _record_to_node(self, record: MemoryRecord) -> UnifiedMemoryNode:
        """MemoryRecord → UnifiedMemoryNode"""
        return UnifiedMemoryNode(
            id=record.id,
            content=record.content,
            embedding=record.embedding if record.embedding else None,
            temperature=record.temperature,
            category=record.categories[0] if record.categories else "general",
            access_count=record.recall_count,
            metadata={
                "importance": record.importance,
                "emotion_score": record.emotion_score,
                "merged_from": record.merged_from,
                "is_archived": record.is_archived,
            },
        )

    def _apply_results(
        self,
        original_nodes: List[UnifiedMemoryNode],
        consolidated: List[MemoryRecord],
        merge_results: List[MergeResult],
    ) -> Dict[str, Any]:
        """将整合结果写回引擎"""
        original_ids = {n.id for n in original_nodes}
        consolidated_ids = {r.id for r in consolidated}
        merged_source_ids = set()
        for mr in merge_results:
            merged_source_ids.update(mr.source_ids)

        archived_count = 0
        merged_count = 0
        updated_count = 0

        # 处理合并后的记忆
        for record in consolidated:
            node = self._record_to_node(record)

            if record.is_archived:
                # 归档：更新温度和元数据
                node.layer = node.layer  # 保持原层
                node.metadata["is_archived"] = True
                self.engine.store(node)
                archived_count += 1
            elif record.merged_from:
                # 合并记忆：存储新节点
                self.engine.store(node)
                merged_count += 1
            else:
                # 普通记忆：更新温度
                self.engine.store(node)
                updated_count += 1

        # 删除被合并的源记忆（从 L0 buffer 中移除）
        for node in original_nodes:
            if node.id in merged_source_ids and node.id not in consolidated_ids:
                # 标记为已合并
                node.metadata["merged_into"] = "consolidated"
                node.temperature = 0.0

        return {
            "status": "completed",
            "processed": len(original_nodes),
            "consolidated": len(consolidated),
            "merged": merged_count,
            "archived": archived_count,
            "updated": updated_count,
            "merge_operations": len(merge_results),
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取适配器统计信息"""
        engine_stats = self.engine.get_statistics()
        consolidation_stats = self.consolidation.__dict__
        return {
            "engine": engine_stats,
            "consolidation": {
                "similarity_threshold": consolidation_stats.get("similarity_threshold"),
                "archive_threshold": consolidation_stats.get("archive_threshold"),
                "decay_rate": consolidation_stats.get("decay_rate"),
            },
        }
