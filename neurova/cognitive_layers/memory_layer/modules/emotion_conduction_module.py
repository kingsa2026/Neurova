"""
EmotionConductionModule — 情感传导模块

管理情感在记忆之间的传导和影响
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EmotionConductionModule:
    """
    情感传导模块
    
    管理情感在记忆之间的传导，支持：
    - 情感传播：一个记忆的情感影响相关记忆
    - 情感聚合：多个记忆的情感综合
    - 情感衰减：传导的情感随距离衰减
    """
    
    def __init__(
        self,
        conduction_rate: float = 0.3,
        decay_factor: float = 0.8,
        max_hops: int = 3,
    ):
        """
        Args:
            conduction_rate: 传导率
            decay_factor: 衰减因子
            max_hops: 最大传导跳数
        """
        self._conduction_rate = conduction_rate
        self._decay_factor = decay_factor
        self._max_hops = max_hops
        
        self._lock = threading.RLock()
        self._initialized = False
        
        # 记忆情感值
        self._emotion_values: Dict[str, float] = {}  # memory_id -> emotion value [-1, 1]
        
        # 记忆关联图
        self._associations: Dict[str, List[str]] = {}  # memory_id -> [related_ids]
    
    @property
    def name(self) -> str:
        """模块名称"""
        return "emotion_conduction_module"
    
    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("EmotionConductionModule initialized")
        return True
    
    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("EmotionConductionModule shutdown")
    
    def set_emotion(self, memory_id: str, emotion_value: float) -> None:
        """
        设置记忆的情感值
        
        Args:
            memory_id: 记忆ID
            emotion_value: 情感值 [-1, 1]
        """
        with self._lock:
            self._emotion_values[memory_id] = max(-1.0, min(1.0, emotion_value))
    
    def get_emotion(self, memory_id: str) -> float:
        """获取记忆的情感值"""
        with self._lock:
            return self._emotion_values.get(memory_id, 0.0)
    
    def add_association(self, memory_id_1: str, memory_id_2: str) -> None:
        """
        添加记忆关联
        
        Args:
            memory_id_1: 记忆1 ID
            memory_id_2: 记忆2 ID
        """
        with self._lock:
            if memory_id_1 not in self._associations:
                self._associations[memory_id_1] = []
            if memory_id_2 not in self._associations[memory_id_1]:
                self._associations[memory_id_1].append(memory_id_2)
            
            if memory_id_2 not in self._associations:
                self._associations[memory_id_2] = []
            if memory_id_1 not in self._associations[memory_id_2]:
                self._associations[memory_id_2].append(memory_id_1)
    
    def conduct_emotion(
        self,
        source_id: str,
        emotion_value: float,
    ) -> Dict[str, float]:
        """
        从源记忆传导情感
        
        Args:
            source_id: 源记忆ID
            emotion_value: 情感值
            
        Returns:
            受影响的记忆及其情感变化
        """
        with self._lock:
            # 设置源记忆情感
            self._emotion_values[source_id] = emotion_value
            
            # BFS 传导
            affected = {}
            visited = {source_id}
            queue = [(source_id, emotion_value, 0)]  # (id, emotion, hops)
            
            while queue:
                current_id, current_emotion, hops = queue.pop(0)
                
                if hops >= self._max_hops:
                    continue
                
                # 获取关联记忆
                related_ids = self._associations.get(current_id, [])
                
                for related_id in related_ids:
                    if related_id in visited:
                        continue
                    
                    visited.add(related_id)
                    
                    # 计算传导后的情感
                    conducted_emotion = current_emotion * self._conduction_rate * (self._decay_factor ** hops)
                    
                    # 更新情感值（加权平均）
                    existing = self._emotion_values.get(related_id, 0.0)
                    new_emotion = existing * 0.7 + conducted_emotion * 0.3
                    self._emotion_values[related_id] = max(-1.0, min(1.0, new_emotion))
                    
                    affected[related_id] = self._emotion_values[related_id]
                    
                    # 继续传导
                    queue.append((related_id, conducted_emotion, hops + 1))
            
            return affected
    
    def aggregate_emotion(self, memory_ids: List[str]) -> float:
        """
        聚合多个记忆的情感
        
        Args:
            memory_ids: 记忆ID列表
            
        Returns:
            聚合后的情感值
        """
        with self._lock:
            if not memory_ids:
                return 0.0
            
            emotions = [self._emotion_values.get(mid, 0.0) for mid in memory_ids]
            
            # 使用加权平均，极端情感权重更高
            weights = [abs(e) + 0.1 for e in emotions]
            total_weight = sum(weights)
            
            if total_weight == 0:
                return 0.0
            
            weighted_sum = sum(e * w for e, w in zip(emotions, weights))
            return weighted_sum / total_weight
    
    def get_positive_memories(self, threshold: float = 0.3, limit: int = 10) -> List[str]:
        """获取正面情感记忆"""
        with self._lock:
            positive = [
                (mid, val) for mid, val in self._emotion_values.items()
                if val > threshold
            ]
            positive.sort(key=lambda x: x[1], reverse=True)
            return [mid for mid, _ in positive[:limit]]
    
    def get_negative_memories(self, threshold: float = -0.3, limit: int = 10) -> List[str]:
        """获取负面情感记忆"""
        with self._lock:
            negative = [
                (mid, val) for mid, val in self._emotion_values.items()
                if val < threshold
            ]
            negative.sort(key=lambda x: x[1])
            return [mid for mid, _ in negative[:limit]]
    
    def get_neutral_memories(self, threshold: float = 0.2, limit: int = 10) -> List[str]:
        """获取中性情感记忆"""
        with self._lock:
            neutral = [
                (mid, val) for mid, val in self._emotion_values.items()
                if abs(val) <= threshold
            ]
            return [mid for mid, _ in neutral[:limit]]
    
    def remove_memory(self, memory_id: str) -> None:
        """移除记忆"""
        with self._lock:
            self._emotion_values.pop(memory_id, None)
            self._associations.pop(memory_id, None)
            
            # 清理其他记忆的关联
            for related_ids in self._associations.values():
                if memory_id in related_ids:
                    related_ids.remove(memory_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            if not self._emotion_values:
                return {
                    "total_memories": 0,
                    "avg_emotion": 0,
                    "positive_count": 0,
                    "negative_count": 0,
                }
            
            values = list(self._emotion_values.values())
            
            return {
                "total_memories": len(self._emotion_values),
                "avg_emotion": sum(values) / len(values),
                "positive_count": sum(1 for v in values if v > 0.3),
                "negative_count": sum(1 for v in values if v < -0.3),
                "neutral_count": sum(1 for v in values if abs(v) <= 0.3),
                "total_associations": sum(len(ids) for ids in self._associations.values()) // 2,
            }
