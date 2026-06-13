"""
ForgettingRecoveryModule — 遗忘恢复模块

处理记忆的遗忘和恢复机制
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ForgettingRecoveryModule:
    """
    遗忘恢复模块

    管理记忆的遗忘和恢复，支持：
    - 遗忘曲线管理
    - 记忆恢复触发
    - 间隔重复调度
    """

    def __init__(
        self,
        forgetting_rate: float = 0.1,
        recovery_boost: float = 0.5,
        min_retention: float = 0.01,
    ):
        """
        Args:
            forgetting_rate: 遗忘速率
            recovery_boost: 恢复提升量
            min_retention: 最低保留率
        """
        self._forgetting_rate = forgetting_rate
        self._recovery_boost = recovery_boost
        self._min_retention = min_retention

        self._lock = threading.RLock()
        self._initialized = False

        # 记忆保留率
        self._retention: Dict[str, float] = {}  # memory_id -> retention [0, 1]

        # 上次访问时间
        self._last_access: Dict[str, float] = {}  # memory_id -> timestamp

        # 复习历史
        self._review_history: Dict[str, List[float]] = {}  # memory_id -> [review_timestamps]

    @property
    def name(self) -> str:
        """模块名称"""
        return "forgetting_recovery_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("ForgettingRecoveryModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("ForgettingRecoveryModule shutdown")

    def register_memory(
        self,
        memory_id: str,
        initial_retention: float = 1.0,
    ) -> None:
        """
        注册记忆

        Args:
            memory_id: 记忆ID
            initial_retention: 初始保留率
        """
        with self._lock:
            self._retention[memory_id] = max(self._min_retention, min(1.0, initial_retention))
            self._last_access[memory_id] = time.time()
            self._review_history[memory_id] = [time.time()]

    def get_retention(self, memory_id: str) -> float:
        """
        获取当前保留率

        Args:
            memory_id: 记忆ID

        Returns:
            当前保留率 [min_retention, 1.0]
        """
        with self._lock:
            if memory_id not in self._retention:
                return 0.0

            base_retention = self._retention[memory_id]
            last_access = self._last_access.get(memory_id, time.time())

            # 计算遗忘衰减
            elapsed_hours = (time.time() - last_access) / 3600
            decay = math.exp(-self._forgetting_rate * elapsed_hours)

            current_retention = base_retention * decay
            return max(self._min_retention, current_retention)

    def access_memory(self, memory_id: str) -> float:
        """
        访问记忆（恢复）

        Args:
            memory_id: 记忆ID

        Returns:
            访问后的保留率
        """
        with self._lock:
            current_retention = self.get_retention(memory_id)

            # 恢复提升
            new_retention = min(1.0, current_retention + self._recovery_boost)

            self._retention[memory_id] = new_retention
            self._last_access[memory_id] = time.time()

            # 记录复习
            if memory_id not in self._review_history:
                self._review_history[memory_id] = []
            self._review_history[memory_id].append(time.time())

            return new_retention

    def schedule_review(
        self,
        memory_id: str,
        target_retention: float = 0.8,
    ) -> Optional[float]:
        """
        计划下次复习时间

        Args:
            memory_id: 记忆ID
            target_retention: 目标保留率

        Returns:
            建议的复习时间间隔（秒），如果不需要复习返回 None
        """
        current_retention = self.get_retention(memory_id)

        if current_retention >= target_retention:
            return None  # 不需要复习

        # 计算需要多少时间后复习才能维持目标保留率
        # R = R0 * e^(-kt) => t = -ln(R/R0) / k
        if current_retention <= 0:
            return 0  # 立即复习

        ratio = target_retention / current_retention
        if ratio <= 1:
            return None

        hours_until_review = -math.log(1 / ratio) / self._forgetting_rate
        return hours_until_review * 3600  # 转换为秒

    def get_forgetting_memories(
        self,
        threshold: float = 0.3,
        limit: int = 10,
    ) -> List[Tuple[str, float]]:
        """
        获取即将遗忘的记忆

        Args:
            threshold: 保留率阈值
            limit: 返回数量限制

        Returns:
            [(memory_id, retention), ...]
        """
        with self._lock:
            candidates = []

            for memory_id in self._retention:
                retention = self.get_retention(memory_id)
                if retention < threshold:
                    candidates.append((memory_id, retention))

            # 按保留率排序
            candidates.sort(key=lambda x: x[1])
            return candidates[:limit]

    def batch_review(self, memory_ids: List[str]) -> Dict[str, float]:
        """批量复习"""
        results = {}
        for memory_id in memory_ids:
            results[memory_id] = self.access_memory(memory_id)
        return results

    def get_review_history(self, memory_id: str) -> List[float]:
        """获取复习历史"""
        with self._lock:
            return list(self._review_history.get(memory_id, []))

    def remove_memory(self, memory_id: str) -> None:
        """移除记忆"""
        with self._lock:
            self._retention.pop(memory_id, None)
            self._last_access.pop(memory_id, None)
            self._review_history.pop(memory_id, None)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            if not self._retention:
                return {
                    "total_memories": 0,
                    "avg_retention": 0,
                    "forgetting_rate": self._forgetting_rate,
                }

            retentions = [self.get_retention(mid) for mid in self._retention]

            return {
                "total_memories": len(self._retention),
                "avg_retention": sum(retentions) / len(retentions),
                "min_retention": min(retentions),
                "max_retention": max(retentions),
                "below_threshold": sum(1 for r in retentions if r < 0.3),
                "forgetting_rate": self._forgetting_rate,
                "recovery_boost": self._recovery_boost,
            }
