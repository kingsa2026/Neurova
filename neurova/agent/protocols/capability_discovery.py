# -*- coding: utf-8 -*-
"""
Agent 能力发现协议模块

提供 Agent 能力注册、查询和匹配功能：
1. 能力注册与更新
2. 能力查询（支持模糊匹配）
3. 能力矩阵构建
4. 任务-能力匹配
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


logger = logging.getLogger(__name__)


class CapabilityCategory(str, Enum):
    """能力类别枚举"""

    COGNITION = "cognition"  # 认知能力
    EXECUTION = "execution"  # 执行能力
    ANALYSIS = "analysis"  # 分析能力
    CREATION = "creation"  # 创造能力
    COMMUNICATION = "communication"  # 沟通能力
    LEARNING = "learning"  # 学习能力
    REASONING = "reasoning"  # 推理能力
    PLANNING = "planning"  # 规划能力
    CREATIVE = "creative"  # 创意能力
    TECHNICAL = "technical"  # 技术能力
    DOMAIN = "domain"  # 领域知识


class CapabilityLevel(str, Enum):
    """能力等级枚举"""

    BEGINNER = "beginner"  # 初级
    INTERMEDIATE = "intermediate"  # 中级
    ADVANCED = "advanced"  # 高级
    EXPERT = "expert"  # 专家
    MASTER = "master"  # 大师

    @property
    def value_int(self) -> int:
        """获取等级数值"""
        level_map = {
            CapabilityLevel.BEGINNER: 1,
            CapabilityLevel.INTERMEDIATE: 2,
            CapabilityLevel.ADVANCED: 3,
            CapabilityLevel.EXPERT: 4,
            CapabilityLevel.MASTER: 5,
        }
        return level_map.get(self, 1)


@dataclass
class Capability:
    """单个能力定义"""

    name: str  # 能力名称
    category: CapabilityCategory  # 能力类别
    level: CapabilityLevel = CapabilityLevel.INTERMEDIATE  # 能力等级
    description: str = ""  # 能力描述
    keywords: List[str] = field(default_factory=list)  # 关键词（用于搜索）
    examples: List[str] = field(default_factory=list)  # 示例场景
    metrics: Dict[str, float] = field(default_factory=dict)  # 性能指标

    def matches_query(self, query: str) -> bool:
        """检查是否匹配查询"""
        query_lower = query.lower()

        # 检查名称
        if query_lower in self.name.lower():
            return True

        # 检查关键词
        for keyword in self.keywords:
            if query_lower in keyword.lower():
                return True

        # 检查描述
        if query_lower in self.description.lower():
            return True

        return False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "category": self.category.value if isinstance(self.category, CapabilityCategory) else self.category,
            "level": self.level.value if isinstance(self.level, CapabilityLevel) else self.level,
            "description": self.description,
            "keywords": self.keywords,
            "examples": self.examples,
            "metrics": self.metrics,
        }


@dataclass
class AgentCapability:
    """Agent 能力集合"""

    agent_id: str
    agent_name: str = ""
    capabilities: List[Capability] = field(default_factory=list)
    registered_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "online"  # online/offline/busy
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 统计信息
    total_tasks: int = 0
    successful_tasks: int = 0
    average_response_time: float = 0.0

    @property
    def success_rate(self) -> float:
        """任务成功率"""
        if self.total_tasks == 0:
            return 0.0
        return self.successful_tasks / self.total_tasks

    def add_capability(self, capability: Capability) -> None:
        """添加能力"""
        # 检查是否已存在
        for i, existing in enumerate(self.capabilities):
            if existing.name == capability.name:
                self.capabilities[i] = capability
                self.updated_at = time.time()
                return
        self.capabilities.append(capability)
        self.updated_at = time.time()

    def remove_capability(self, name: str) -> bool:
        """移除能力"""
        for i, cap in enumerate(self.capabilities):
            if cap.name == name:
                self.capabilities.pop(i)
                self.updated_at = time.time()
                return True
        return False

    def get_capability(self, name: str) -> Optional[Capability]:
        """获取指定能力"""
        for cap in self.capabilities:
            if cap.name == name:
                return cap
        return None

    def get_capabilities_by_category(self, category: CapabilityCategory) -> List[Capability]:
        """获取指定类别的所有能力"""
        return [cap for cap in self.capabilities if cap.category == category]

    def has_capability(self, name: str, min_level: CapabilityLevel = None) -> bool:
        """检查是否具有指定能力"""
        cap = self.get_capability(name)
        if cap is None:
            return False
        if min_level is not None:
            return cap.level.value_int >= min_level.value_int
        return True

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "capabilities": [cap.to_dict() for cap in self.capabilities],
            "registered_at": self.registered_at,
            "updated_at": self.updated_at,
            "status": self.status,
            "metadata": self.metadata,
            "stats": {
                "total_tasks": self.total_tasks,
                "successful_tasks": self.successful_tasks,
                "success_rate": self.success_rate,
                "average_response_time": self.average_response_time,
            },
        }


@dataclass
class CapabilityMatch:
    """能力匹配结果"""

    agent_capability: AgentCapability
    matched_capabilities: List[Tuple[Capability, float]]  # (能力, 匹配度)
    overall_score: float  # 总体匹配度 0-1
    missing_capabilities: List[str]  # 缺失的能力
    recommendation: str = ""  # 建议

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "agent_id": self.agent_capability.agent_id,
            "agent_name": self.agent_capability.agent_name,
            "matched_capabilities": [
                {"name": cap.name, "level": cap.level.value, "score": score} for cap, score in self.matched_capabilities
            ],
            "overall_score": self.overall_score,
            "missing_capabilities": self.missing_capabilities,
            "recommendation": self.recommendation,
        }


class CapabilityDiscovery:
    """Agent 能力发现服务"""

    def __init__(self):
        self._registry: Dict[str, AgentCapability] = {}  # agent_id -> AgentCapability
        self._category_index: Dict[CapabilityCategory, Set[str]] = {cat: set() for cat in CapabilityCategory}
        self._keyword_index: Dict[str, Set[str]] = {}  # keyword -> set of agent_ids

    def register_agent(self, capability: AgentCapability) -> None:
        """注册 Agent 能力"""
        self._registry[capability.agent_id] = capability
        self._update_index(capability)
        logger.info("Agent 能力已注册: %s (%s 个能力)", capability.agent_id, len(capability.capabilities))

    def unregister_agent(self, agent_id: str) -> bool:
        """取消注册 Agent"""
        if agent_id in self._registry:
            cap = self._registry.pop(agent_id)
            self._remove_from_index(cap)
            logger.info("Agent 能力已取消注册: %s", agent_id)
            return True
        return False

    def update_agent_capability(self, capability: AgentCapability) -> None:
        """更新 Agent 能力"""
        if capability.agent_id in self._registry:
            old_cap = self._registry[capability.agent_id]
            self._remove_from_index(old_cap)
        self.register_agent(capability)

    def get_agent_capability(self, agent_id: str) -> Optional[AgentCapability]:
        """获取 Agent 能力"""
        return self._registry.get(agent_id)

    def list_agents(self, status: str = None) -> List[AgentCapability]:
        """列出所有 Agent（可选状态过滤）"""
        agents = list(self._registry.values())
        if status:
            agents = [a for a in agents if a.status == status]
        return agents

    def find_agents_by_capability(
        self,
        capability_name: str,
        min_level: CapabilityLevel = None,
    ) -> List[Tuple[AgentCapability, Capability]]:
        """根据能力名称查找 Agent"""
        results = []

        for agent_cap in self._registry.values():
            cap = agent_cap.get_capability(capability_name)
            if cap is None:
                continue
            if min_level and cap.level.value_int < min_level.value_int:
                continue
            results.append((agent_cap, cap))

        # 按能力等级排序
        results.sort(key=lambda x: x[1].level.value_int, reverse=True)
        return results

    def find_agents_by_category(
        self,
        category: CapabilityCategory,
        min_level: CapabilityLevel = None,
    ) -> List[AgentCapability]:
        """根据能力类别查找 Agent"""
        agent_ids = self._category_index.get(category, set())
        results = []

        for agent_id in agent_ids:
            agent_cap = self._registry.get(agent_id)
            if agent_cap:
                # 检查是否有满足最低等级要求的能力
                caps = agent_cap.get_capabilities_by_category(category)
                if min_level:
                    caps = [c for c in caps if c.level.value_int >= min_level.value_int]
                if caps:
                    results.append(agent_cap)

        return results

    def search_agents(self, query: str) -> List[AgentCapability]:
        """搜索 Agent（通过关键词匹配）"""
        query_lower = query.lower()
        matched_ids: Set[str] = set()

        # 精确匹配 agent_id
        if query_lower in self._registry:
            return [self._registry[query_lower]]

        # 搜索关键词索引
        for keyword, agent_ids in self._keyword_index.items():
            if query_lower in keyword.lower():
                matched_ids.update(agent_ids)

        # 搜索能力名称和描述
        for agent_id, agent_cap in self._registry.items():
            for cap in agent_cap.capabilities:
                if cap.matches_query(query):
                    matched_ids.add(agent_id)
                    break

        return [self._registry[aid] for aid in matched_ids if aid in self._registry]

    def match_task_requirements(
        self,
        required_capabilities: List[Tuple[str, CapabilityLevel]],
    ) -> List[CapabilityMatch]:
        """匹配任务需求与 Agent 能力

        Args:
            required_capabilities: 需求列表 [(能力名称, 最低等级), ...]

        Returns:
            匹配结果列表，按总体匹配度排序
        """
        matches = []

        for agent_cap in self._registry.values():
            if agent_cap.status != "online":
                continue

            matched_caps = []
            missing_caps = []
            total_score = 0.0

            for req_name, min_level in required_capabilities:
                cap = agent_cap.get_capability(req_name)
                if cap is None:
                    missing_caps.append(req_name)
                    continue

                # 计算匹配度
                level_diff = cap.level.value_int - min_level.value_int
                score = min(1.0, 0.5 + (level_diff * 0.15))  # 等级差每高1级 +0.15
                matched_caps.append((cap, score))
                total_score += score

            # 计算总体匹配度
            if required_capabilities:
                overall = total_score / len(required_capabilities)
            else:
                overall = 0.0

            # 生成建议
            recommendation = self._generate_recommendation(overall, matched_caps, missing_caps)

            match = CapabilityMatch(
                agent_capability=agent_cap,
                matched_capabilities=matched_caps,
                overall_score=overall,
                missing_capabilities=missing_caps,
                recommendation=recommendation,
            )
            matches.append(match)

        # 按匹配度排序
        matches.sort(key=lambda x: x.overall_score, reverse=True)
        return matches

    def get_capability_matrix(self) -> Dict[str, Any]:
        """获取能力矩阵视图"""
        matrix = {
            "agents": [],
            "categories": [cat.value for cat in CapabilityCategory],
            "levels": [level.value for level in CapabilityLevel],
            "matrix": {},  # agent_id -> {category -> level}
        }

        for agent_cap in self._registry.values():
            agent_data = {
                "agent_id": agent_cap.agent_id,
                "agent_name": agent_cap.agent_name,
                "status": agent_cap.status,
            }
            matrix["agents"].append(agent_data)

            # 构建能力矩阵
            agent_matrix = {}
            for cap in agent_cap.capabilities:
                cat = cap.category.value if isinstance(cap.category, CapabilityCategory) else cap.category
                agent_matrix[cat] = cap.level.value_int

            matrix["matrix"][agent_cap.agent_id] = agent_matrix

        return matrix

    def _update_index(self, capability: AgentCapability) -> None:
        """更新索引"""
        for cap in capability.capabilities:
            # 更新类别索引
            cat = cap.category if isinstance(cap.category, CapabilityCategory) else CapabilityCategory(cap.category)
            self._category_index[cat].add(capability.agent_id)

            # 更新关键词索引
            for keyword in cap.keywords:
                if keyword not in self._keyword_index:
                    self._keyword_index[keyword] = set()
                self._keyword_index[keyword].add(capability.agent_id)

    def _remove_from_index(self, capability: AgentCapability) -> None:
        """从索引中移除"""
        for cap in capability.capabilities:
            cat = cap.category if isinstance(cap.category, CapabilityCategory) else CapabilityCategory(cap.category)
            self._category_index[cat].discard(capability.agent_id)

            for keyword in cap.keywords:
                if keyword in self._keyword_index:
                    self._keyword_index[keyword].discard(capability.agent_id)

    def _generate_recommendation(
        self,
        overall: float,
        matched: List[Tuple[Capability, float]],
        missing: List[str],
    ) -> str:
        """生成推荐建议"""
        if overall >= 0.8:
            return "强烈推荐：该 Agent 完全满足任务需求"
        elif overall >= 0.6:
            return "推荐：该 Agent 基本满足需求"
        elif overall >= 0.4:
            return "可考虑：需要额外补充缺失能力"
        else:
            if missing:
                return f"不推荐：缺少关键能力 {', '.join(missing)}"
            return "不推荐：该 Agent 不满足任务需求"


# 全局能力发现服务实例
_global_discovery: Optional[CapabilityDiscovery] = None


def get_capability_discovery() -> CapabilityDiscovery:
    """获取全局能力发现服务"""
    global _global_discovery
    if _global_discovery is None:
        _global_discovery = CapabilityDiscovery()
    return _global_discovery
