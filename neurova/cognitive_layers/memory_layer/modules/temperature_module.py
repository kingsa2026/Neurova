"""
TemperatureModule — 温度管理模块

管理记忆的温度（活跃度），影响记忆检索的优先级
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TemperatureModule:
    """
    温度管理模块
    
    基于艾宾浩斯遗忘曲线管理记忆温度：
    - 新记忆温度高
    - 频繁访问的记忆温度保持高
    - 长时间未访问的记忆温度衰减
    """
    
    def __init__(
        self,
        decay_rate: float = 0.1,
        access_boost: float = 0.3,
        min_temperature: float = 0.01,
        max_temperature: float = 1.0,
    ):
        """
        Args:
            decay_rate: 衰减速率
            access_boost: 访问提升量
            min_temperature: 最低温度
            max_temperature: 最高温度
        """
        self._decay_rate = decay_rate
        self._access_boost = access_boost
        self._min_temperature = min_temperature
        self._max_temperature = max_temperature
        
        self._temperatures: Dict[str, float] = {}  # memory_id -> temperature
        self._last_access: Dict[str, float] = {}  # memory_id -> timestamp
        self._access_counts: Dict[str, int] = {}  # memory_id -> count
        self._lock = threading.RLock()
        self._initialized = False
    
    @property
    def name(self) -> str:
        """模块名称"""
        return "temperature_module"
    
    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("TemperatureModule initialized")
        return True
    
    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("TemperatureModule shutdown")
    
    def get_temperature(self, memory_id: str) -> float:
        """
        获取记忆温度
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            当前温度 [min_temperature, max_temperature]
        """
        with self._lock:
            if memory_id not in self._temperatures:
                return self._max_temperature  # 新记忆默认最高温度
            
            # 计算衰减后的温度
            base_temp = self._temperatures[memory_id]
            last_access = self._last_access.get(memory_id, time.time())
            elapsed = time.time() - last_access
            
            # 应用衰减
            decayed_temp = base_temp * math.exp(-self._decay_rate * elapsed / 3600)  # 每小时衰减
            
            return max(self._min_temperature, min(self._max_temperature, decayed_temp))
    
    def set_temperature(self, memory_id: str, temperature: float) -> None:
        """设置记忆温度"""
        with self._lock:
            self._temperatures[memory_id] = max(
                self._min_temperature,
                min(self._max_temperature, temperature),
            )
            self._last_access[memory_id] = time.time()
    
    def access(self, memory_id: str) -> float:
        """
        记录访问并提升温度
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            访问后的温度
        """
        with self._lock:
            current_temp = self.get_temperature(memory_id)
            
            # 提升温度
            new_temp = min(self._max_temperature, current_temp + self._access_boost)
            
            self._temperatures[memory_id] = new_temp
            self._last_access[memory_id] = time.time()
            self._access_counts[memory_id] = self._access_counts.get(memory_id, 0) + 1
            
            return new_temp
    
    def batch_get_temperatures(self, memory_ids: List[str]) -> Dict[str, float]:
        """批量获取温度"""
        return {mid: self.get_temperature(mid) for mid in memory_ids}
    
    def get_hot_memories(self, threshold: float = 0.5, limit: int = 10) -> List[str]:
        """
        获取热门记忆
        
        Args:
            threshold: 温度阈值
            limit: 返回数量限制
            
        Returns:
            记忆ID列表
        """
        with self._lock:
            hot = []
            for memory_id in list(self._temperatures.keys()):
                temp = self.get_temperature(memory_id)
                if temp >= threshold:
                    hot.append((memory_id, temp))
            
            # 按温度排序
            hot.sort(key=lambda x: x[1], reverse=True)
            return [mid for mid, _ in hot[:limit]]
    
    def get_cold_memories(self, threshold: float = 0.2, limit: int = 10) -> List[str]:
        """获取冷门记忆"""
        with self._lock:
            cold = []
            for memory_id in list(self._temperatures.keys()):
                temp = self.get_temperature(memory_id)
                if temp <= threshold:
                    cold.append((memory_id, temp))
            
            cold.sort(key=lambda x: x[1])
            return [mid for mid, _ in cold[:limit]]
    
    def remove_memory(self, memory_id: str) -> None:
        """移除记忆温度记录"""
        with self._lock:
            self._temperatures.pop(memory_id, None)
            self._last_access.pop(memory_id, None)
            self._access_counts.pop(memory_id, None)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            temps = list(self._temperatures.values())
            
            if not temps:
                return {
                    "total_memories": 0,
                    "avg_temperature": 0,
                    "hot_count": 0,
                    "cold_count": 0,
                }
            
            return {
                "total_memories": len(temps),
                "avg_temperature": sum(temps) / len(temps),
                "min_temperature": min(temps),
                "max_temperature": max(temps),
                "hot_count": sum(1 for t in temps if t >= 0.5),
                "cold_count": sum(1 for t in temps if t <= 0.2),
                "decay_rate": self._decay_rate,
                "access_boost": self._access_boost,
            }
