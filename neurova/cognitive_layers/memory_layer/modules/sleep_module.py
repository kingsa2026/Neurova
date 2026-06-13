"""
SleepModule — 睡眠整理模块

模拟睡眠过程中的记忆整理和巩固
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class SleepModule:
    """
    睡眠整理模块

    模拟睡眠过程中的记忆处理：
    - 记忆巩固：强化重要记忆
    - 记忆整合：合并相似记忆
    - 记忆清理：删除不重要的记忆
    - 梦境回放：随机组合记忆片段
    """

    def __init__(
        self,
        consolidation_threshold: float = 0.7,
        cleanup_threshold: float = 0.2,
        dream_probability: float = 0.1,
    ):
        """
        Args:
            consolidation_threshold: 巩固阈值
            cleanup_threshold: 清理阈值
            dream_probability: 梦境发生概率
        """
        self._consolidation_threshold = consolidation_threshold
        self._cleanup_threshold = cleanup_threshold
        self._dream_probability = dream_probability

        self._lock = threading.RLock()
        self._initialized = False
        self._is_sleeping = False

        # 睡眠统计
        self._consolidation_count = 0
        self._cleanup_count = 0
        self._dream_count = 0

        # 回调
        self._on_consolidate: Optional[Callable] = None
        self._on_cleanup: Optional[Callable] = None
        self._on_dream: Optional[Callable] = None

    @property
    def name(self) -> str:
        """模块名称"""
        return "sleep_module"

    @property
    def is_sleeping(self) -> bool:
        """是否正在睡眠"""
        return self._is_sleeping

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("SleepModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._is_sleeping = False
        self._initialized = False
        logger.info("SleepModule shutdown")

    def start_sleep(self) -> bool:
        """
        开始睡眠

        Returns:
            是否成功开始
        """
        with self._lock:
            if self._is_sleeping:
                return False

            self._is_sleeping = True
            logger.info("Sleep started")
            return True

    def end_sleep(self) -> Dict[str, int]:
        """
        结束睡眠

        Returns:
            睡眠期间的处理统计
        """
        with self._lock:
            self._is_sleeping = False

            stats = {
                "consolidated": self._consolidation_count,
                "cleaned": self._cleanup_count,
                "dreams": self._dream_count,
            }

            # 重置计数
            self._consolidation_count = 0
            self._cleanup_count = 0
            self._dream_count = 0

            logger.info("Sleep ended: %s", stats)
            return stats

    def consolidate_memory(
        self,
        memory_id: str,
        memory_data: Dict[str, Any],
        importance: float,
    ) -> bool:
        """
        巩固记忆

        Args:
            memory_id: 记忆ID
            memory_data: 记忆数据
            importance: 重要性分数

        Returns:
            是否巩固
        """
        if not self._is_sleeping:
            return False

        if importance < self._consolidation_threshold:
            return False

        with self._lock:
            self._consolidation_count += 1

            if self._on_consolidate:
                try:
                    self._on_consolidate(memory_id, memory_data, importance)
                except Exception as e:
                    logger.warning("Consolidation callback failed: %s", e)

            logger.debug("Consolidated memory '%.2f' (importance=%s)", memory_id, importance)
            return True

    def cleanup_memory(
        self,
        memory_id: str,
        importance: float,
    ) -> bool:
        """
        清理记忆

        Args:
            memory_id: 记忆ID
            importance: 重要性分数

        Returns:
            是否清理
        """
        if not self._is_sleeping:
            return False

        if importance > self._cleanup_threshold:
            return False

        with self._lock:
            self._cleanup_count += 1

            if self._on_cleanup:
                try:
                    self._on_cleanup(memory_id, importance)
                except Exception as e:
                    logger.warning("Cleanup callback failed: %s", e)

            logger.debug("Cleaned up memory '%.2f' (importance=%s)", memory_id, importance)
            return True

    def dream(
        self,
        memory_ids: List[str],
        memory_contents: List[Any],
    ) -> Optional[Dict[str, Any]]:
        """
        梦境回放 - 随机组合记忆片段

        Args:
            memory_ids: 参与梦境的记忆ID列表
            memory_contents: 对应的记忆内容

        Returns:
            梦境产物，如果没有发生梦境返回 None
        """
        if not self._is_sleeping:
            return None

        # 随机决定是否发生梦境
        if random.random() > self._dream_probability:
            return None

        with self._lock:
            self._dream_count += 1

            # 随机选择2-3个记忆进行组合
            count = min(len(memory_ids), random.randint(2, 3))
            indices = random.sample(range(len(memory_ids)), count)

            selected_ids = [memory_ids[i] for i in indices]
            selected_contents = [memory_contents[i] for i in indices]

            dream_result = {
                "type": "dream",
                "source_memories": selected_ids,
                "combined_content": selected_contents,
                "created_at": time.time(),
            }

            if self._on_dream:
                try:
                    self._on_dream(dream_result)
                except Exception as e:
                    logger.warning("Dream callback failed: %s", e)

            logger.debug("Dream generated from memories: %s", selected_ids)
            return dream_result

    def process_memories(
        self,
        memories: List[Dict[str, Any]],
    ) -> Dict[str, List[str]]:
        """
        批量处理记忆

        Args:
            memories: 记忆列表，每个包含 id, importance, content

        Returns:
            处理结果：consolidated, cleaned, dreamed
        """
        if not self._is_sleeping:
            return {"consolidated": [], "cleaned": [], "dreamed": []}

        consolidated = []
        cleaned = []

        for memory in memories:
            memory_id = memory.get("id", "")
            importance = memory.get("importance", 0.5)

            if importance >= self._consolidation_threshold:
                if self.consolidate_memory(memory_id, memory, importance):
                    consolidated.append(memory_id)
            elif importance <= self._cleanup_threshold:
                if self.cleanup_memory(memory_id, importance):
                    cleaned.append(memory_id)

        # 尝试梦境
        dreamed = []
        if len(memories) >= 2:
            dream = self.dream(
                [m.get("id", "") for m in memories],
                [m.get("content") for m in memories],
            )
            if dream:
                dreamed = dream.get("source_memories", [])

        return {
            "consolidated": consolidated,
            "cleaned": cleaned,
            "dreamed": dreamed,
        }

    def set_callbacks(
        self,
        on_consolidate: Optional[Callable] = None,
        on_cleanup: Optional[Callable] = None,
        on_dream: Optional[Callable] = None,
    ) -> None:
        """设置回调函数"""
        self._on_consolidate = on_consolidate
        self._on_cleanup = on_cleanup
        self._on_dream = on_dream

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "is_sleeping": self._is_sleeping,
            "consolidation_threshold": self._consolidation_threshold,
            "cleanup_threshold": self._cleanup_threshold,
            "dream_probability": self._dream_probability,
            "last_session": {
                "consolidated": self._consolidation_count,
                "cleaned": self._cleanup_count,
                "dreams": self._dream_count,
            },
        }
