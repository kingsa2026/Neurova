"""
睡眠整合模块

在"睡眠"阶段对记忆进行整合：
- 语义相似度聚类
- 合并高度相似的记忆（减少冗余）
- 温度衰减（遗忘低价值记忆）
- 压缩和归档
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any

logger = logging.getLogger(__name__)


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    if len(vec_a) != len(vec_b):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    
    return dot_product / (norm_a * norm_b)


@dataclass
class MemoryRecord:
    """记忆记录"""
    id: str
    content: str
    embedding: List[float] = field(default_factory=list)
    temperature: float = 50.0
    importance: float = 0.5
    emotion_score: float = 0.0
    recall_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    categories: List[str] = field(default_factory=list)
    is_archived: bool = False
    merged_from: List[str] = field(default_factory=list)


@dataclass
class MergeResult:
    """合并结果"""
    merged_id: str
    merged_content: str
    source_ids: List[str]
    avg_temperature: float
    avg_importance: float
    combined_categories: List[str]


class SleepConsolidation:
    """睡眠整合引擎
    
    模拟睡眠期间的记忆整合过程：
    1. 语义相似度聚类
    2. 高相似度记忆合并
    3. 温度衰减（遗忘）
    4. 归档低活跃度记忆
    """
    
    def __init__(self, 
                 similarity_threshold: float = 0.7,
                 archive_threshold: float = 20.0,
                 decay_rate: float = 0.1):
        """初始化睡眠整合引擎
        
        Args:
            similarity_threshold: 语义相似度阈值（高于此值的记忆合并）
            archive_threshold: 归档温度阈值
            decay_rate: 睡眠期间的温度衰减率
        """
        self.similarity_threshold = similarity_threshold
        self.archive_threshold = archive_threshold
        self.decay_rate = decay_rate
        
        logger.debug(f"SleepConsolidation 初始化: "
                    f"similarity={similarity_threshold}, "
                    f"archive={archive_threshold}")
    
    def cluster_by_similarity(self, memories: List[MemoryRecord]) -> List[List[MemoryRecord]]:
        """基于语义相似度聚类
        
        使用简单的贪心聚类算法：
        1. 遍历所有记忆
        2. 找到与当前记忆最相似的簇
        3. 如果相似度超过阈值，加入该簇
        4. 否则创建新簇
        
        Args:
            memories: 记忆列表
            
        Returns:
            List[List[MemoryRecord]]: 聚类结果
        """
        if not memories:
            return []
        
        clusters: List[List[MemoryRecord]] = []
        
        for memory in memories:
            best_cluster = None
            best_similarity = 0.0
            
            # 找到最相似的簇
            for cluster in clusters:
                # 使用簇中心（第一个元素）计算相似度
                if cluster[0].embedding and memory.embedding:
                    sim = cosine_similarity(cluster[0].embedding, memory.embedding)
                    if sim > best_similarity:
                        best_similarity = sim
                        best_cluster = cluster
            
            # 如果相似度超过阈值，加入簇
            if best_cluster is not None and best_similarity >= self.similarity_threshold:
                best_cluster.append(memory)
            else:
                # 创建新簇
                clusters.append([memory])
        
        logger.debug(f"聚类结果: {len(memories)} 条记忆 → {len(clusters)} 个簇")
        return clusters
    
    def merge_cluster(self, cluster: List[MemoryRecord]) -> MergeResult:
        """合并一个簇中的记忆
        
        合并策略：
        - 内容：取最长的内容（包含最多信息）
        - 温度：取平均值
        - 重要性：取最高值
        - 分类：合并所有分类（去重）
        
        Args:
            cluster: 同一簇中的记忆
            
        Returns:
            MergeResult: 合并结果
        """
        if not cluster:
            raise ValueError("空簇无法合并")
        
        if len(cluster) == 1:
            mem = cluster[0]
            return MergeResult(
                merged_id=mem.id,
                merged_content=mem.content,
                source_ids=[mem.id],
                avg_temperature=mem.temperature,
                avg_importance=mem.importance,
                combined_categories=mem.categories.copy(),
            )
        
        # 取最长的内容
        longest = max(cluster, key=lambda m: len(m.content))
        
        # 计算平均值
        avg_temp = sum(m.temperature for m in cluster) / len(cluster)
        avg_importance = sum(m.importance for m in cluster) / len(cluster)
        
        # 合并分类（去重）
        all_categories = list(set(
            cat for m in cluster for cat in m.categories
        ))
        
        # 生成合并ID
        merged_id = f"merged_{cluster[0].id}_{len(cluster)}"
        
        # 记录来源
        source_ids = [m.id for m in cluster]
        
        result = MergeResult(
            merged_id=merged_id,
            merged_content=longest.content,
            source_ids=source_ids,
            avg_temperature=avg_temp,
            avg_importance=avg_importance,
            combined_categories=all_categories,
        )
        
        logger.debug(f"合并簇: {len(cluster)} 条记忆 → {merged_id}")
        return result
    
    def apply_sleep_decay(self, memories: List[MemoryRecord]) -> List[MemoryRecord]:
        """应用睡眠期间的温度衰减
        
        睡眠期间，所有记忆的温度都会降低。
        低温度的记忆会被标记为归档。
        
        Args:
            memories: 记忆列表
            
        Returns:
            List[MemoryRecord]: 更新后的记忆列表
        """
        for memory in memories:
            # 基础衰减
            decay = self.decay_rate * memory.temperature
            
            # 重要性保护
            importance_protection = 1.0 - 0.5 * memory.importance
            
            # 最终衰减
            actual_decay = decay * importance_protection
            memory.temperature = max(0.0, memory.temperature - actual_decay)
            
            # 归档检查
            if memory.temperature < self.archive_threshold:
                memory.is_archived = True
                logger.debug(f"记忆 {memory.id} 已归档 (温度: {memory.temperature:.1f})")
        
        return memories
    
    def consolidate(self, memories: List[MemoryRecord]) -> Tuple[List[MemoryRecord], List[MergeResult]]:
        """执行完整的睡眠整合流程
        
        步骤：
        1. 聚类相似记忆
        2. 合并每个簇
        3. 应用温度衰减
        4. 返回整合后的记忆和合并记录
        
        Args:
            memories: 记忆列表
            
        Returns:
            Tuple[List[MemoryRecord], List[MergeResult]]: 
                整合后的记忆列表, 合并记录列表
        """
        logger.info(f"开始睡眠整合: {len(memories)} 条记忆")
        
        # 1. 聚类
        clusters = self.cluster_by_similarity(memories)
        
        # 2. 合并
        merged_memories = []
        merge_results = []
        
        for cluster in clusters:
            merge_result = self.merge_cluster(cluster)
            merge_results.append(merge_result)
            
            # 创建合并后的记忆记录
            merged_memory = MemoryRecord(
                id=merge_result.merged_id,
                content=merge_result.merged_content,
                temperature=merge_result.avg_temperature,
                importance=merge_result.avg_importance,
                categories=merge_result.combined_categories,
                merged_from=merge_result.source_ids,
                created_at=datetime.now(),
            )
            
            # 保留嵌入（使用第一个记忆的嵌入）
            if cluster[0].embedding:
                merged_memory.embedding = cluster[0].embedding
            
            merged_memories.append(merged_memory)
        
        # 3. 温度衰减
        merged_memories = self.apply_sleep_decay(merged_memories)
        
        # 4. 统计
        active_count = sum(1 for m in merged_memories if not m.is_archived)
        archived_count = sum(1 for m in merged_memories if m.is_archived)
        
        logger.info(f"睡眠整合完成: "
                   f"合并 {len(memories)} → {len(merged_memories)} 条记忆, "
                   f"活跃 {active_count}, 归档 {archived_count}")
        
        return merged_memories, merge_results