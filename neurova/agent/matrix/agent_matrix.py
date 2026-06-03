# -*- coding: utf-8 -*-
"""
Agent 能力矩阵模块

提供 Agent 能力的可视化和分析功能。
"""

import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from ..protocols.capability_discovery import (
    CapabilityDiscovery,
    AgentCapability,
    CapabilityCategory,
    CapabilityLevel,
    Capability,
    get_capability_discovery,
)

logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    """Agent 状态"""
    ONLINE = "online"       # 在线
    OFFLINE = "offline"     # 离线
    BUSY = "busy"           # 忙碌
    IDLE = "idle"           # 空闲
    ERROR = "error"         # 错误


@dataclass
class RadarChartData:
    """雷达图数据"""
    labels: List[str]           # 维度标签
    datasets: List[Dict[str, Any]]  # 数据集
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "labels": self.labels,
            "datasets": self.datasets,
        }


@dataclass
class AgentMatrixData:
    """Agent 能力矩阵数据"""
    agent_id: str
    agent_name: str
    status: AgentStatus
    
    # 能力数据
    capabilities: List[Dict[str, Any]]  # 能力列表
    radar_chart: RadarChartData         # 雷达图数据
    
    # 统计信息
    total_capabilities: int
    average_level: float
    strongest_category: str
    weakest_category: str
    
    # 任务统计
    total_tasks: int
    successful_tasks: int
    success_rate: float
    average_response_time: float
    
    # 实时状态
    current_task: Optional[str] = None
    workload: float = 0.0  # 0-1 表示负载
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "status": self.status.value if isinstance(self.status, AgentStatus) else self.status,
            "capabilities": self.capabilities,
            "radar_chart": self.radar_chart.to_dict(),
            "stats": {
                "total_capabilities": self.total_capabilities,
                "average_level": self.average_level,
                "strongest_category": self.strongest_category,
                "weakest_category": self.weakest_category,
            },
            "task_stats": {
                "total_tasks": self.total_tasks,
                "successful_tasks": self.successful_tasks,
                "success_rate": self.success_rate,
                "average_response_time": self.average_response_time,
            },
            "current_state": {
                "current_task": self.current_task,
                "workload": self.workload,
            },
        }


@dataclass
class TaskRecommendation:
    """任务推荐"""
    agent_id: str
    agent_name: str
    match_score: float           # 匹配度 0-1
    recommended_capabilities: List[str]
    missing_capabilities: List[str]
    estimated_time: float        # 预计时间（秒）
    confidence: float            # 置信度 0-1
    reason: str                  # 推荐理由
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "match_score": self.match_score,
            "recommended_capabilities": self.recommended_capabilities,
            "missing_capabilities": self.missing_capabilities,
            "estimated_time": self.estimated_time,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class AgentMatrix:
    """Agent 能力矩阵"""
    
    def __init__(self, discovery: CapabilityDiscovery = None):
        """
        初始化能力矩阵
        
        Args:
            discovery: 能力发现服务实例
        """
        self._discovery = discovery or get_capability_discovery()
    
    def get_agent_matrix(self, agent_id: str) -> Optional[AgentMatrixData]:
        """
        获取指定 Agent 的能力矩阵
        
        Args:
            agent_id: Agent ID
            
        Returns:
            Agent 能力矩阵数据
        """
        agent_cap = self._discovery.get_agent_capability(agent_id)
        if agent_cap is None:
            return None
        
        return self._build_matrix_data(agent_cap)
    
    def get_all_agents_matrix(self) -> List[AgentMatrixData]:
        """
        获取所有 Agent 的能力矩阵
        
        Returns:
            Agent 能力矩阵列表
        """
        matrices = []
        for agent_cap in self._discovery.list_agents():
            matrix = self._build_matrix_data(agent_cap)
            if matrix:
                matrices.append(matrix)
        return matrices
    
    def get_matrix_summary(self) -> Dict[str, Any]:
        """
        获取能力矩阵总览
        
        Returns:
            矩阵总览数据
        """
        agents = self._discovery.list_agents()
        
        # 统计信息
        total_agents = len(agents)
        online_agents = len([a for a in agents if a.status == "online"])
        busy_agents = len([a for a in agents if a.status == "busy"])
        
        # 能力统计
        all_categories: Dict[str, List[float]] = {}
        for agent in agents:
            for cap in agent.capabilities:
                cat = cap.category.value if isinstance(cap.category, CapabilityCategory) else cap.category
                if cat not in all_categories:
                    all_categories[cat] = []
                all_categories[cat].append(cap.level.value_int)
        
        category_stats = {}
        for cat, levels in all_categories.items():
            category_stats[cat] = {
                "average_level": sum(levels) / len(levels) if levels else 0,
                "agent_count": len(levels),
            }
        
        return {
            "summary": {
                "total_agents": total_agents,
                "online_agents": online_agents,
                "busy_agents": busy_agents,
            },
            "category_stats": category_stats,
            "agents": [self._build_matrix_data(a).to_dict() for a in agents],
        }
    
    def recommend_agents(
        self,
        required_capabilities: List[str],
        min_match_score: float = 0.5,
        max_results: int = 5,
    ) -> List[TaskRecommendation]:
        """
        推荐适合任务的 Agent
        
        Args:
            required_capabilities: 所需能力列表
            min_match_score: 最小匹配度
            max_results: 最大结果数
            
        Returns:
            推荐的 Agent 列表
        """
        recommendations = []
        
        for agent_cap in self._discovery.list_agents():
            if agent_cap.status != "online":
                continue
            
            matched = []
            missing = []
            total_score = 0.0
            
            for req_cap in required_capabilities:
                cap = agent_cap.get_capability(req_cap)
                if cap:
                    matched.append(cap.name)
                    total_score += cap.level.value_int / 5.0  # 归一化到 0-1
                else:
                    missing.append(req_cap)
            
            if not required_capabilities:
                match_score = 0.0
            else:
                match_score = total_score / len(required_capabilities)
            
            if match_score >= min_match_score:
                # 计算预计时间和置信度
                if agent_cap.average_response_time > 0:
                    estimated_time = agent_cap.average_response_time * (1 + len(missing) * 0.5)
                else:
                    estimated_time = 300  # 默认 5 分钟
                
                confidence = match_score * agent_cap.success_rate if agent_cap.success_rate > 0 else match_score * 0.8
                
                # 生成推荐理由
                if match_score >= 0.8:
                    reason = "该 Agent 完全满足任务所需能力"
                elif match_score >= 0.6:
                    reason = f"该 Agent 具备 {len(matched)}/{len(required_capabilities)} 项所需能力"
                else:
                    reason = f"该 Agent 具备部分能力，但缺少: {', '.join(missing[:2])}"
                
                recommendations.append(TaskRecommendation(
                    agent_id=agent_cap.agent_id,
                    agent_name=agent_cap.agent_name,
                    match_score=match_score,
                    recommended_capabilities=matched,
                    missing_capabilities=missing,
                    estimated_time=estimated_time,
                    confidence=confidence,
                    reason=reason,
                ))
        
        # 按匹配度排序
        recommendations.sort(key=lambda x: x.match_score, reverse=True)
        return recommendations[:max_results]
    
    def compare_agents(
        self,
        agent_ids: List[str],
    ) -> Dict[str, Any]:
        """
        对比多个 Agent 的能力
        
        Args:
            agent_ids: Agent ID 列表
            
        Returns:
            对比结果
        """
        agents_data = []
        
        for agent_id in agent_ids:
            agent_cap = self._discovery.get_agent_capability(agent_id)
            if agent_cap:
                matrix = self._build_matrix_data(agent_cap)
                if matrix:
                    agents_data.append(matrix.to_dict())
        
        if not agents_data:
            return {"error": "未找到指定的 Agent"}
        
        # 计算各维度的最佳 Agent
        categories = list(CapabilityCategory)
        best_by_category = {}
        
        for cat in categories:
            cat_name = cat.value
            best_agent = None
            best_level = 0
            
            for agent in agents_data:
                for cap in agent.get("capabilities", []):
                    if cap.get("category") == cat_name:
                        level = cap.get("level", {}).get("value_int", 0)
                        if level > best_level:
                            best_level = level
                            best_agent = agent.get("agent_id")
            
            if best_agent:
                best_by_category[cat_name] = {
                    "agent_id": best_agent,
                    "level": best_level,
                }
        
        return {
            "agents": agents_data,
            "best_by_category": best_by_category,
            "comparison_date": time.time(),
        }
    
    def _build_matrix_data(self, agent_cap: AgentCapability) -> Optional[AgentMatrixData]:
        """构建能力矩阵数据"""
        if not agent_cap.capabilities:
            return None
        
        # 按类别聚合能力
        category_levels: Dict[str, List[float]] = {}
        for cap in agent_cap.capabilities:
            cat = cap.category.value if isinstance(cap.category, CapabilityCategory) else cap.category
            if cat not in category_levels:
                category_levels[cat] = []
            category_levels[cat].append(cap.level.value_int)
        
        # 计算各类别的平均等级
        category_avg = {
            cat: sum(levels) / len(levels) if levels else 0
            for cat, levels in category_levels.items()
        }
        
        # 找出最强和最弱类别
        strongest = max(category_avg.items(), key=lambda x: x[1]) if category_avg else ("N/A", 0)
        weakest = min(category_avg.items(), key=lambda x: x[1]) if category_avg else ("N/A", 0)
        
        # 计算平均等级
        all_levels = [cap.level.value_int for cap in agent_cap.capabilities]
        avg_level = sum(all_levels) / len(all_levels) if all_levels else 0
        
        # 构建雷达图数据
        radar_labels = list(category_avg.keys())
        radar_values = list(category_avg.values())
        
        # 归一化到 0-100
        radar_values_normalized = [v / 5.0 * 100 for v in radar_values]
        
        radar_chart = RadarChartData(
            labels=radar_labels,
            datasets=[
                {
                    "label": agent_cap.agent_name,
                    "data": radar_values_normalized,
                    "backgroundColor": "rgba(54, 162, 235, 0.2)",
                    "borderColor": "rgba(54, 162, 235, 1)",
                    "borderWidth": 2,
                }
            ],
        )
        
        # 转换能力列表
        capabilities = []
        for cap in agent_cap.capabilities:
            cat = cap.category.value if isinstance(cap.category, CapabilityCategory) else cap.category
            capabilities.append({
                "name": cap.name,
                "category": cat,
                "level": cap.level.value if isinstance(cap.level, CapabilityLevel) else cap.level,
                "level_int": cap.level.value_int,
                "description": cap.description,
                "metrics": cap.metrics,
            })
        
        return AgentMatrixData(
            agent_id=agent_cap.agent_id,
            agent_name=agent_cap.agent_name,
            status=AgentStatus(agent_cap.status),
            capabilities=capabilities,
            radar_chart=radar_chart,
            total_capabilities=len(agent_cap.capabilities),
            average_level=avg_level,
            strongest_category=strongest[0],
            weakest_category=weakest[0],
            total_tasks=agent_cap.total_tasks,
            successful_tasks=agent_cap.successful_tasks,
            success_rate=agent_cap.success_rate,
            average_response_time=agent_cap.average_response_time,
        )


class MatrixRenderer:
    """能力矩阵渲染器"""
    
    # 颜色配置
    CATEGORY_COLORS = {
        "cognition": "#FF6384",
        "execution": "#36A2EB",
        "analysis": "#FFCE56",
        "creation": "#4BC0C0",
        "communication": "#9966FF",
        "learning": "#FF9F40",
        "reasoning": "#FF6384",
        "planning": "#C9CBCF",
        "creative": "#4BC0C0",
        "technical": "#36A2EB",
        "domain": "#9966FF",
    }
    
    # 状态颜色
    STATUS_COLORS = {
        "online": "#4BC0C0",
        "offline": "#C9CBCF",
        "busy": "#FF6384",
        "idle": "#36A2EB",
        "error": "#FF0000",
    }
    
    @classmethod
    def render_radar_chart_config(
        cls,
        matrix_data: AgentMatrixData,
    ) -> Dict[str, Any]:
        """
        渲染雷达图配置（Chart.js 格式）
        
        Args:
            matrix_data: Agent 能力矩阵数据
            
        Returns:
            Chart.js 雷达图配置
        """
        return {
            "type": "radar",
            "data": matrix_data.radar_chart.to_dict(),
            "options": {
                "responsive": True,
                "maintainAspectRatio": True,
                "scale": {
                    "ticks": {
                        "beginAtZero": True,
                        "max": 100,
                        "stepSize": 20,
                    },
                },
                "plugins": {
                    "legend": {
                        "position": "bottom",
                    },
                    "tooltip": {
                        "callbacks": {
                            "label": "function(context) { return context.label + ': ' + context.raw.toFixed(1) + '%'; }",
                        },
                    },
                },
            },
        }
    
    @classmethod
    def render_capability_bars(
        cls,
        matrix_data: AgentMatrixData,
    ) -> List[Dict[str, Any]]:
        """
        渲染能力条形图数据
        
        Args:
            matrix_data: Agent 能力矩阵数据
            
        Returns:
            条形图数据列表
        """
        bars = []
        
        for cap in matrix_data.capabilities:
            cat = cap.get("category", "unknown")
            color = cls.CATEGORY_COLORS.get(cat, "#999999")
            level_int = cap.get("level_int", 0)
            
            bars.append({
                "name": cap.get("name", ""),
                "category": cat,
                "level": level_int,
                "percentage": level_int / 5.0 * 100,
                "color": color,
            })
        
        # 按等级排序
        bars.sort(key=lambda x: x["level"], reverse=True)
        return bars
    
    @classmethod
    def render_status_indicator(
        cls,
        status: AgentStatus,
    ) -> Dict[str, Any]:
        """
        渲染状态指示器
        
        Args:
            status: Agent 状态
            
        Returns:
            状态指示器数据
        """
        status_str = status.value if isinstance(status, AgentStatus) else status
        color = cls.STATUS_COLORS.get(status_str, "#999999")
        
        labels = {
            "online": "在线",
            "offline": "离线",
            "busy": "忙碌",
            "idle": "空闲",
            "error": "错误",
        }
        
        return {
            "status": status_str,
            "label": labels.get(status_str, status_str),
            "color": color,
            "pulse": status_str == "online",
        }


# 全局能力矩阵实例
_global_matrix: Optional[AgentMatrix] = None


def get_agent_matrix() -> AgentMatrix:
    """获取全局能力矩阵"""
    global _global_matrix
    if _global_matrix is None:
        _global_matrix = AgentMatrix()
    return _global_matrix
