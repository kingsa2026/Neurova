"""
SelfManagerModule — 自我管理模块

管理 Agent 的自我认知和自我调节
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class SelfModel:
    """自我模型"""

    agent_id: str
    capabilities: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    goals: List[str] = field(default_factory=list)
    values: List[str] = field(default_factory=list)
    confidence: float = 0.7  # 自我效能感
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "capabilities": self.capabilities,
            "limitations": self.limitations,
            "goals": self.goals,
            "values": self.values,
            "confidence": self.confidence,
            "updated_at": self.updated_at,
        }


class SelfManagerModule:
    """
    自我管理模块

    管理 Agent 的自我认知，支持：
    - 自我模型维护
    - 自我效能评估
    - 自我调节
    """

    def __init__(self, agent_id: str = "default"):
        """
        Args:
            agent_id: Agent ID
        """
        self._agent_id = agent_id
        self._lock = threading.RLock()
        self._initialized = False

        # 自我模型
        self._self_model = SelfModel(agent_id=agent_id)

        # 自我反思历史
        self._reflections: List[Dict[str, Any]] = []

        # 自我效能记录
        self._efficacy_history: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        """模块名称"""
        return "self_manager_module"

    @property
    def self_model(self) -> SelfModel:
        """自我模型"""
        return self._self_model

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("SelfManagerModule initialized for agent '%s'", self._agent_id)
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("SelfManagerModule shutdown")

    def add_capability(self, capability: str) -> None:
        """添加能力"""
        with self._lock:
            if capability not in self._self_model.capabilities:
                self._self_model.capabilities.append(capability)
                self._self_model.updated_at = time.time()

    def remove_capability(self, capability: str) -> bool:
        """移除能力"""
        with self._lock:
            if capability in self._self_model.capabilities:
                self._self_model.capabilities.remove(capability)
                self._self_model.updated_at = time.time()
                return True
            return False

    def add_limitation(self, limitation: str) -> None:
        """添加限制"""
        with self._lock:
            if limitation not in self._self_model.limitations:
                self._self_model.limitations.append(limitation)
                self._self_model.updated_at = time.time()

    def remove_limitation(self, limitation: str) -> bool:
        """移除限制"""
        with self._lock:
            if limitation in self._self_model.limitations:
                self._self_model.limitations.remove(limitation)
                self._self_model.updated_at = time.time()
                return True
            return False

    def set_goal(self, goal: str) -> None:
        """设置目标"""
        with self._lock:
            if goal not in self._self_model.goals:
                self._self_model.goals.append(goal)
                self._self_model.updated_at = time.time()

    def remove_goal(self, goal: str) -> bool:
        """移除目标"""
        with self._lock:
            if goal in self._self_model.goals:
                self._self_model.goals.remove(goal)
                self._self_model.updated_at = time.time()
                return True
            return False

    def update_confidence(self, confidence: float) -> None:
        """更新自我效能感"""
        with self._lock:
            self._self_model.confidence = max(0.0, min(1.0, confidence))
            self._self_model.updated_at = time.time()

    def record_reflection(
        self,
        situation: str,
        reflection: str,
        outcome: str,
        lessons: List[str],
    ) -> None:
        """记录自我反思"""
        with self._lock:
            self._reflections.append(
                {
                    "situation": situation,
                    "reflection": reflection,
                    "outcome": outcome,
                    "lessons": lessons,
                    "timestamp": time.time(),
                }
            )

            # 限制历史长度
            if len(self._reflections) > 100:
                self._reflections = self._reflections[-100:]

    def record_efficacy(
        self,
        task: str,
        success: bool,
        confidence_before: float,
        confidence_after: float,
    ) -> None:
        """记录自我效能"""
        with self._lock:
            self._efficacy_history.append(
                {
                    "task": task,
                    "success": success,
                    "confidence_before": confidence_before,
                    "confidence_after": confidence_after,
                    "timestamp": time.time(),
                }
            )

            # 更新置信度
            self._self_model.confidence = confidence_after
            self._self_model.updated_at = time.time()

            # 限制历史长度
            if len(self._efficacy_history) > 100:
                self._efficacy_history = self._efficacy_history[-100:]

    def get_recent_reflections(self, count: int = 5) -> List[Dict[str, Any]]:
        """获取最近的反思"""
        with self._lock:
            return self._reflections[-count:]

    def get_success_rate(self) -> float:
        """获取成功率"""
        with self._lock:
            if not self._efficacy_history:
                return 0.5

            success_count = sum(1 for e in self._efficacy_history if e["success"])
            return success_count / len(self._efficacy_history)

    def can_handle_task(self, task_requirements: List[str]) -> Dict[str, Any]:
        """
        评估是否能处理任务

        Args:
            task_requirements: 任务需求列表

        Returns:
            评估结果
        """
        with self._lock:
            capabilities = set(self._self_model.capabilities)
            limitations = set(self._self_model.limitations)
            requirements = set(task_requirements)

            met = requirements & capabilities
            unmet = requirements - capabilities
            blocked = requirements & limitations

            coverage = len(met) / len(requirements) if requirements else 1.0

            return {
                "can_handle": coverage >= 0.7 and len(blocked) == 0,
                "coverage": coverage,
                "met_requirements": list(met),
                "unmet_requirements": list(unmet),
                "blocked_requirements": list(blocked),
                "confidence": self._self_model.confidence,
            }

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "agent_id": self._agent_id,
                "capabilities_count": len(self._self_model.capabilities),
                "limitations_count": len(self._self_model.limitations),
                "goals_count": len(self._self_model.goals),
                "confidence": self._self_model.confidence,
                "reflections_count": len(self._reflections),
                "efficacy_records": len(self._efficacy_history),
                "success_rate": self.get_success_rate(),
            }
