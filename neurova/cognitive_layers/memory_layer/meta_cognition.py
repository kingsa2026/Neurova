"""
Meta Cognition - 元认知模块

提供元认知功能，用于监控和评估认知过程。
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CognitiveLoad(str, Enum):
    """认知负荷级别"""

    LOW = "low"  # 低负荷
    MODERATE = "moderate"  # 中等负荷
    HIGH = "high"  # 高负荷
    OVERLOAD = "overload"  # 超负荷


@dataclass
class CognitiveState:
    """认知状态"""

    timestamp: datetime.datetime
    load_level: CognitiveLoad
    load_score: float  # 0-1
    active_tasks: int = 0
    memory_usage: float = 0.0
    response_time_ms: float = 0.0
    error_rate: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "load_level": self.load_level.value,
            "load_score": self.load_score,
            "active_tasks": self.active_tasks,
            "memory_usage": self.memory_usage,
            "response_time_ms": self.response_time_ms,
            "error_rate": self.error_rate,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveState":
        """从字典创建"""
        return cls(
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            load_level=CognitiveLoad(data["load_level"]),
            load_score=data.get("load_score", 0.0),
            active_tasks=data.get("active_tasks", 0),
            memory_usage=data.get("memory_usage", 0.0),
            response_time_ms=data.get("response_time_ms", 0.0),
            error_rate=data.get("error_rate", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ReasoningRecord:
    """推理记录"""

    reasoning_id: str
    timestamp: datetime.datetime
    query: str
    response: str
    reasoning_steps: List[str] = field(default_factory=list)
    confidence: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "reasoning_id": self.reasoning_id,
            "timestamp": self.timestamp.isoformat(),
            "query": self.query[:200],
            "response": self.response[:200],
            "reasoning_steps": self.reasoning_steps,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "metadata": self.metadata,
        }


class MetaCognition:
    """元认知模块

    提供认知过程的监控、评估和优化建议。
    """

    def __init__(
        self,
        agent_id: str = "default",
        max_history_size: int = 1000,
        consolidation_threshold: float = 0.7,
    ):
        """初始化元认知模块

        Args:
            agent_id: Agent ID
            max_history_size: 最大历史记录数
            consolidation_threshold: 整合阈值
        """
        self._agent_id = agent_id
        self._max_history_size = max_history_size
        self._consolidation_threshold = consolidation_threshold

        # 认知状态历史
        self._state_history: deque[CognitiveState] = deque(maxlen=max_history_size)
        self._current_state: Optional[CognitiveState] = None

        # 推理记录
        self._reasoning_history: deque[ReasoningRecord] = deque(maxlen=max_history_size)

        # 优化建议
        self._optimization_suggestions: List[Dict[str, Any]] = []

        # 统计信息
        self._stats = {
            "total_updates": 0,
            "total_reasonings": 0,
            "avg_load_score": 0.0,
            "consolidation_count": 0,
        }

        # 线程安全
        self._lock = threading.RLock()

        logger.info("MetaCognition 初始化完成: agent_id=%s", agent_id)

    def update_state(
        self,
        active_tasks: int = 0,
        memory_usage: float = 0.0,
        response_time_ms: float = 0.0,
        error_rate: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CognitiveState:
        """更新认知状态

        Args:
            active_tasks: 活跃任务数
            memory_usage: 内存使用率 (0-1)
            response_time_ms: 平均响应时间（毫秒）
            error_rate: 错误率 (0-1)
            metadata: 附加元数据

        Returns:
            更新后的认知状态
        """
        with self._lock:
            # 计算负荷分数
            load_score = self._calculate_load_score(active_tasks, memory_usage, response_time_ms, error_rate)

            # 确定负荷级别
            load_level = self._determine_load_level(load_score)

            # 创建新状态
            state = CognitiveState(
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                load_level=load_level,
                load_score=load_score,
                active_tasks=active_tasks,
                memory_usage=memory_usage,
                response_time_ms=response_time_ms,
                error_rate=error_rate,
                metadata=metadata or {},
            )

            # 更新状态
            self._current_state = state
            self._state_history.append(state)

            # 更新统计
            self._stats["total_updates"] += 1
            self._stats["avg_load_score"] = (
                self._stats["avg_load_score"] * (self._stats["total_updates"] - 1) + load_score
            ) / self._stats["total_updates"]

            return state

    def _calculate_load_score(
        self,
        active_tasks: int,
        memory_usage: float,
        response_time_ms: float,
        error_rate: float,
    ) -> float:
        """计算负荷分数

        Args:
            active_tasks: 活跃任务数
            memory_usage: 内存使用率
            response_time_ms: 响应时间
            error_rate: 错误率

        Returns:
            负荷分数 (0-1)
        """
        # 各因素权重
        weights = {
            "tasks": 0.3,
            "memory": 0.25,
            "response_time": 0.25,
            "error_rate": 0.2,
        }

        # 标准化各因素
        task_factor = min(1.0, active_tasks / 10.0)  # 假设10个任务为满负荷
        memory_factor = min(1.0, memory_usage)
        response_factor = min(1.0, response_time_ms / 5000.0)  # 5秒为满负荷
        error_factor = min(1.0, error_rate)

        # 计算加权分数
        load_score = (
            task_factor * weights["tasks"]
            + memory_factor * weights["memory"]
            + response_factor * weights["response_time"]
            + error_factor * weights["error_rate"]
        )

        return min(1.0, max(0.0, load_score))

    def _determine_load_level(self, load_score: float) -> CognitiveLoad:
        """确定负荷级别

        Args:
            load_score: 负荷分数

        Returns:
            负荷级别
        """
        if load_score < 0.3:
            return CognitiveLoad.LOW
        elif load_score < 0.6:
            return CognitiveLoad.MODERATE
        elif load_score < 0.85:
            return CognitiveLoad.HIGH
        else:
            return CognitiveLoad.OVERLOAD

    def get_state(self) -> Optional[CognitiveState]:
        """获取当前认知状态

        Returns:
            当前认知状态
        """
        with self._lock:
            return self._current_state

    def get_history(
        self,
        limit: int = 100,
        since: Optional[datetime.datetime] = None,
    ) -> List[CognitiveState]:
        """获取状态历史

        Args:
            limit: 返回数量限制
            since: 起始时间

        Returns:
            状态历史列表
        """
        with self._lock:
            history = list(self._state_history)

            if since:
                history = [s for s in history if s.timestamp >= since]

            return history[-limit:]

    def assess_cognitive_load(self) -> Dict[str, Any]:
        """评估认知负荷

        Returns:
            评估结果
        """
        with self._lock:
            if not self._current_state:
                return {
                    "status": "no_data",
                    "message": "暂无认知状态数据",
                }

            state = self._current_state

            # 分析趋势
            trend = self._analyze_load_trend()

            # 生成建议
            suggestions = self._generate_load_suggestions(state)

            return {
                "current_load": state.load_level.value,
                "load_score": state.load_score,
                "trend": trend,
                "suggestions": suggestions,
                "details": {
                    "active_tasks": state.active_tasks,
                    "memory_usage": state.memory_usage,
                    "response_time_ms": state.response_time_ms,
                    "error_rate": state.error_rate,
                },
            }

    def _analyze_load_trend(self) -> str:
        """分析负荷趋势

        Returns:
            趋势描述
        """
        if len(self._state_history) < 2:
            return "insufficient_data"

        # 取最近10个状态
        recent_states = list(self._state_history)[-10:]

        if len(recent_states) < 2:
            return "insufficient_data"

        # 计算趋势
        first_half = sum(s.load_score for s in recent_states[: len(recent_states) // 2]) / (len(recent_states) // 2)
        second_half = sum(s.load_score for s in recent_states[len(recent_states) // 2 :]) / (
            len(recent_states) - len(recent_states) // 2
        )

        diff = second_half - first_half

        if diff > 0.1:
            return "increasing"
        elif diff < -0.1:
            return "decreasing"
        else:
            return "stable"

    def _generate_load_suggestions(self, state: CognitiveState) -> List[str]:
        """生成负荷建议

        Args:
            state: 认知状态

        Returns:
            建议列表
        """
        suggestions = []

        if state.load_level == CognitiveLoad.OVERLOAD:
            suggestions.append("系统负荷过高，建议暂停新任务")
            suggestions.append("考虑释放部分内存或重启服务")
        elif state.load_level == CognitiveLoad.HIGH:
            suggestions.append("负荷较高，建议监控系统状态")
            if state.error_rate > 0.1:
                suggestions.append("错误率较高，建议检查系统日志")
        elif state.load_level == CognitiveLoad.MODERATE:
            if state.response_time_ms > 2000:
                suggestions.append("响应时间较长，建议优化查询")
        else:
            suggestions.append("系统运行正常")

        return suggestions

    def should_consolidate(self) -> bool:
        """判断是否应该进行记忆整合

        Returns:
            是否应该整合
        """
        with self._lock:
            if not self._current_state:
                return False

            # 基于负荷和历史数据判断
            load_score = self._current_state.load_score
            history_size = len(self._state_history)

            # 低负荷时适合整合
            if load_score < 0.3 and history_size > 100:
                return True

            # 高负荷时不整合
            if load_score > 0.7:
                return False

            # 基于阈值判断
            return load_score < self._consolidation_threshold

    def get_optimization_suggestions(self) -> List[Dict[str, Any]]:
        """获取优化建议

        Returns:
            优化建议列表
        """
        with self._lock:
            suggestions = []

            # 基于当前状态生成建议
            if self._current_state:
                state = self._current_state

                # 内存优化
                if state.memory_usage > 0.8:
                    suggestions.append(
                        {
                            "type": "memory",
                            "priority": "high",
                            "suggestion": "内存使用率过高，建议清理缓存或释放资源",
                            "current_value": state.memory_usage,
                            "threshold": 0.8,
                        }
                    )

                # 响应时间优化
                if state.response_time_ms > 3000:
                    suggestions.append(
                        {
                            "type": "performance",
                            "priority": "medium",
                            "suggestion": "响应时间较长，建议优化查询或增加缓存",
                            "current_value": state.response_time_ms,
                            "threshold": 3000,
                        }
                    )

                # 错误率优化
                if state.error_rate > 0.05:
                    suggestions.append(
                        {
                            "type": "reliability",
                            "priority": "high",
                            "suggestion": "错误率较高，建议检查系统日志和错误处理",
                            "current_value": state.error_rate,
                            "threshold": 0.05,
                        }
                    )

            # 基于历史模式生成建议
            if len(self._state_history) > 50:
                avg_load = sum(s.load_score for s in self._state_history) / len(self._state_history)
                if avg_load > 0.6:
                    suggestions.append(
                        {
                            "type": "capacity",
                            "priority": "medium",
                            "suggestion": "历史平均负荷较高，建议考虑扩容",
                            "current_value": avg_load,
                            "threshold": 0.6,
                        }
                    )

            return suggestions

    def record_reasoning(
        self,
        query: str,
        response: str,
        reasoning_steps: List[str],
        confidence: float,
        duration_ms: float,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ReasoningRecord:
        """记录推理过程

        Args:
            query: 查询
            response: 响应
            reasoning_steps: 推理步骤
            confidence: 置信度
            duration_ms: 耗时（毫秒）
            success: 是否成功
            metadata: 附加元数据

        Returns:
            推理记录
        """
        with self._lock:
            record = ReasoningRecord(
                reasoning_id=f"reasoning_{int(time.time() * 1000)}",
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                query=query,
                response=response,
                reasoning_steps=reasoning_steps,
                confidence=confidence,
                duration_ms=duration_ms,
                success=success,
                metadata=metadata or {},
            )

            self._reasoning_history.append(record)
            self._stats["total_reasonings"] += 1

            return record

    def get_reasoning_history(self, limit: int = 50) -> List[ReasoningRecord]:
        """获取推理历史

        Args:
            limit: 返回数量限制

        Returns:
            推理历史列表
        """
        with self._lock:
            return list(self._reasoning_history)[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                **self._stats,
                "history_size": len(self._state_history),
                "reasoning_history_size": len(self._reasoning_history),
                "current_load": self._current_state.load_level.value if self._current_state else None,
            }

    def reset(self) -> None:
        """重置元认知模块"""
        with self._lock:
            self._state_history.clear()
            self._current_state = None
            self._reasoning_history.clear()
            self._optimization_suggestions.clear()

            self._stats = {
                "total_updates": 0,
                "total_reasonings": 0,
                "avg_load_score": 0.0,
                "consolidation_count": 0,
            }

            logger.info("MetaCognition 已重置")


# 全局实例管理
_meta_cognition_instances: Dict[str, MetaCognition] = {}
_meta_cognition_lock = threading.Lock()


def get_meta_cognition(agent_id: str = "default") -> MetaCognition:
    """获取元认知模块单例

    Args:
        agent_id: Agent ID

    Returns:
        元认知模块实例
    """
    global _meta_cognition_instances

    with _meta_cognition_lock:
        if agent_id not in _meta_cognition_instances:
            _meta_cognition_instances[agent_id] = MetaCognition(agent_id=agent_id)
        return _meta_cognition_instances[agent_id]


def reset_meta_cognition(agent_id: Optional[str] = None) -> None:
    """重置元认知模块单例

    Args:
        agent_id: Agent ID，为None时重置所有
    """
    global _meta_cognition_instances

    with _meta_cognition_lock:
        if agent_id is None:
            _meta_cognition_instances.clear()
        elif agent_id in _meta_cognition_instances:
            _meta_cognition_instances[agent_id].reset()
            del _meta_cognition_instances[agent_id]


def reset_all_meta_cognition() -> None:
    """重置所有元认知模块单例"""
    reset_meta_cognition(None)
