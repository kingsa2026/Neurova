"""
TKGModule — 时序知识图谱模块

管理时序知识图谱
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TKGModule:
    """
    时序知识图谱模块

    管理时序知识图谱，支持：
    - 时序事实存储
    - 时间窗口查询
    - 事实冲突检测
    """

    def __init__(self, time_window_hours: float = 24.0):
        """
        Args:
            time_window_hours: 默认时间窗口（小时）
        """
        self._time_window_hours = time_window_hours
        self._lock = threading.RLock()
        self._initialized = False

        # 事实存储: fact_id -> fact_data
        self._facts: Dict[str, Dict[str, Any]] = {}

        # 时间索引: timestamp -> [fact_ids]
        self._time_index: Dict[int, List[str]] = {}

        # 实体索引: entity -> [fact_ids]
        self._entity_index: Dict[str, List[str]] = {}

    @property
    def name(self) -> str:
        """模块名称"""
        return "tkg_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("TKGModule initialized")
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("TKGModule shutdown")

    def add_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float = 1.0,
        valid_from: Optional[float] = None,
        valid_until: Optional[float] = None,
    ) -> str:
        """
        添加时序事实

        Args:
            subject: 主语
            predicate: 谓语
            obj: 宾语
            confidence: 置信度
            valid_from: 有效期开始
            valid_until: 有效期结束

        Returns:
            事实ID
        """
        fact_id = f"{subject}_{predicate}_{obj}_{int(time.time() * 1000)}"
        current_time = time.time()

        fact = {
            "fact_id": fact_id,
            "subject": subject,
            "predicate": predicate,
            "object": obj,
            "confidence": confidence,
            "created_at": current_time,
            "valid_from": valid_from or current_time,
            "valid_until": valid_until,
            "status": "active",
        }

        with self._lock:
            self._facts[fact_id] = fact

            # 更新时间索引
            time_key = int(current_time)
            if time_key not in self._time_index:
                self._time_index[time_key] = []
            self._time_index[time_key].append(fact_id)

            # 更新实体索引
            for entity in [subject, obj]:
                if entity not in self._entity_index:
                    self._entity_index[entity] = []
                self._entity_index[entity].append(fact_id)

        return fact_id

    def get_fact(self, fact_id: str) -> Optional[Dict[str, Any]]:
        """获取事实"""
        with self._lock:
            return self._facts.get(fact_id)

    def query_facts(
        self,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        obj: Optional[str] = None,
        time_from: Optional[float] = None,
        time_until: Optional[float] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        查询事实

        Args:
            subject: 主语过滤
            predicate: 谓语过滤
            obj: 宾语过滤
            time_from: 开始时间
            time_until: 结束时间
            limit: 返回数量限制

        Returns:
            事实列表
        """
        with self._lock:
            results = []

            for fact in self._facts.values():
                # 检查状态
                if fact["status"] != "active":
                    continue

                # 检查时间有效性
                current_time = time.time()
                if fact.get("valid_until") and fact["valid_until"] < current_time:
                    continue

                # 检查过滤条件
                if subject and fact["subject"] != subject:
                    continue
                if predicate and fact["predicate"] != predicate:
                    continue
                if obj and fact["object"] != obj:
                    continue

                # 检查时间范围
                if time_from and fact["created_at"] < time_from:
                    continue
                if time_until and fact["created_at"] > time_until:
                    continue

                results.append(fact)

            # 按时间排序
            results.sort(key=lambda x: x["created_at"], reverse=True)
            return results[:limit]

    def query_by_entity(
        self,
        entity: str,
        time_window_hours: Optional[float] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """按实体查询"""
        with self._lock:
            fact_ids = self._entity_index.get(entity, [])

            time_window = time_window_hours or self._time_window_hours
            cutoff_time = time.time() - (time_window * 3600)

            results = []
            for fact_id in fact_ids:
                fact = self._facts.get(fact_id)
                if fact and fact["created_at"] >= cutoff_time and fact["status"] == "active":
                    results.append(fact)

            results.sort(key=lambda x: x["created_at"], reverse=True)
            return results[:limit]

    def query_recent(
        self,
        hours: float = 24.0,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """查询最近的事实"""
        cutoff_time = time.time() - (hours * 3600)

        with self._lock:
            results = [
                fact
                for fact in self._facts.values()
                if fact["created_at"] >= cutoff_time and fact["status"] == "active"
            ]

            results.sort(key=lambda x: x["created_at"], reverse=True)
            return results[:limit]

    def invalidate_fact(self, fact_id: str) -> bool:
        """使事实失效"""
        with self._lock:
            fact = self._facts.get(fact_id)
            if fact is None:
                return False

            fact["status"] = "invalidated"
            fact["invalidated_at"] = time.time()
            return True

    def detect_conflicts(
        self,
        subject: str,
        predicate: str,
        obj: str,
    ) -> List[Dict[str, Any]]:
        """检测冲突"""
        with self._lock:
            conflicts = []

            for fact in self._facts.values():
                if fact["status"] != "active":
                    continue

                # 检查是否存在矛盾
                if fact["subject"] == subject and fact["predicate"] == predicate and fact["object"] != obj:
                    conflicts.append(fact)

            return conflicts

    def get_entities(self, limit: int = 100) -> List[str]:
        """获取所有实体"""
        with self._lock:
            return list(self._entity_index.keys())[:limit]

    def get_predicates(self) -> List[str]:
        """获取所有谓语"""
        with self._lock:
            predicates = set()
            for fact in self._facts.values():
                predicates.add(fact["predicate"])
            return list(predicates)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            active_count = sum(1 for f in self._facts.values() if f["status"] == "active")

            return {
                "total_facts": len(self._facts),
                "active_facts": active_count,
                "invalidated_facts": len(self._facts) - active_count,
                "entities_count": len(self._entity_index),
                "predicates_count": len(self.get_predicates()),
                "time_window_hours": self._time_window_hours,
            }
