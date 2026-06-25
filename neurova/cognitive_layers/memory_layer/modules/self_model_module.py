"""
SelfModelModule — 自我模型模块

维护 Agent 的自我认知模型
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import threading
import time
from typing import Any, Dict, List

logger = get_logger(__name__)


class SelfModelModule:
    """
    自我模型模块

    维护 Agent 的自我认知，包括：
    - 能力边界认知
    - 知识边界认知
    - 行为模式认知
    """

    def __init__(self, agent_id: str = "default"):
        """
        Args:
            agent_id: Agent ID
        """
        self._agent_id = agent_id
        self._lock = threading.RLock()
        self._initialized = False

        # 能力认知
        self._known_capabilities: Dict[str, float] = {}  # capability -> confidence

        # 知识边界
        self._knowledge_domains: Dict[str, float] = {}  # domain -> expertise_level

        # 行为模式
        self._behavior_patterns: List[Dict[str, Any]] = []

        # 自我评估历史
        self._assessments: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        """模块名称"""
        return "self_model_module"

    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("SelfModelModule initialized for agent '%s'", self._agent_id)
        return True

    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("SelfModelModule shutdown")

    def update_capability(self, capability: str, confidence: float) -> None:
        """更新能力认知"""
        with self._lock:
            self._known_capabilities[capability] = max(0.0, min(1.0, confidence))

    def get_capability_confidence(self, capability: str) -> float:
        """获取能力置信度"""
        with self._lock:
            return self._known_capabilities.get(capability, 0.5)

    def update_knowledge(self, domain: str, expertise_level: float) -> None:
        """更新知识领域"""
        with self._lock:
            self._knowledge_domains[domain] = max(0.0, min(1.0, expertise_level))

    def get_expertise(self, domain: str) -> float:
        """获取领域专业度"""
        with self._lock:
            return self._knowledge_domains.get(domain, 0.3)

    def add_behavior_pattern(self, pattern: Dict[str, Any]) -> None:
        """添加行为模式"""
        with self._lock:
            self._behavior_patterns.append(
                {
                    **pattern,
                    "recorded_at": time.time(),
                }
            )

            # 限制历史长度
            if len(self._behavior_patterns) > 100:
                self._behavior_patterns = self._behavior_patterns[-100:]

    def get_behavior_patterns(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取行为模式"""
        with self._lock:
            return self._behavior_patterns[-limit:]

    def assess_task(self, task_description: str, requirements: List[str]) -> Dict[str, Any]:
        """
        评估任务

        Args:
            task_description: 任务描述
            requirements: 任务需求

        Returns:
            评估结果
        """
        with self._lock:
            # 检查相关能力
            capability_matches = []
            for req in requirements:
                for cap, conf in self._known_capabilities.items():
                    if req.lower() in cap.lower() or cap.lower() in req.lower():
                        capability_matches.append((req, cap, conf))

            # 计算能力覆盖
            covered_reqs = set(match[0] for match in capability_matches)
            coverage = len(covered_reqs) / len(requirements) if requirements else 1.0

            # 计算平均置信度
            avg_confidence = (
                sum(match[2] for match in capability_matches) / len(capability_matches) if capability_matches else 0.5
            )

            assessment = {
                "task": task_description,
                "coverage": coverage,
                "confidence": avg_confidence,
                "capability_matches": capability_matches,
                "timestamp": time.time(),
            }

            self._assessments.append(assessment)
            if len(self._assessments) > 50:
                self._assessments = self._assessments[-50:]

            return assessment

    def get_self_description(self) -> str:
        """获取自我描述"""
        with self._lock:
            parts = [f"Agent ID: {self._agent_id}"]

            if self._known_capabilities:
                caps = sorted(self._known_capabilities.items(), key=lambda x: x[1], reverse=True)
                cap_str = ", ".join(f"{c}({v:.1f})" for c, v in caps[:5])
                parts.append(f"主要能力: {cap_str}")

            if self._knowledge_domains:
                domains = sorted(self._knowledge_domains.items(), key=lambda x: x[1], reverse=True)
                domain_str = ", ".join(f"{d}({v:.1f})" for d, v in domains[:5])
                parts.append(f"知识领域: {domain_str}")

            return "\n".join(parts)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "agent_id": self._agent_id,
                "capabilities_count": len(self._known_capabilities),
                "knowledge_domains_count": len(self._knowledge_domains),
                "behavior_patterns_count": len(self._behavior_patterns),
                "assessments_count": len(self._assessments),
                "avg_capability_confidence": (
                    sum(self._known_capabilities.values()) / len(self._known_capabilities)
                    if self._known_capabilities
                    else 0
                ),
                "avg_expertise": (
                    sum(self._knowledge_domains.values()) / len(self._knowledge_domains)
                    if self._knowledge_domains
                    else 0
                ),
            }
