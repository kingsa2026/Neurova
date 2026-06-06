"""
技能进化引擎

驱动技能的自动进化和优化
"""

from __future__ import annotations

import datetime
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class EvolutionStrategy(str, Enum):
    """进化策略"""
    PERFORMANCE = "performance"  # 基于性能优化
    ADAPTATION = "adaptation"  # 适应新场景
    CONSOLIDATION = "consolidation"  # 巩固成功模式
    EXPLORATION = "exploration"  # 探索新方法


class EvolutionStatus(str, Enum):
    """进化状态"""
    IDLE = "idle"
    ANALYZING = "analyzing"
    EVOLVING = "evolving"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class EvolutionGoal:
    """进化目标"""
    goal_id: str
    description: str
    strategy: EvolutionStrategy
    target_metric: str
    target_value: float
    current_value: float = 0.0
    priority: int = 1  # 1-5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "strategy": self.strategy.value,
            "target_metric": self.target_metric,
            "target_value": self.target_value,
            "current_value": self.current_value,
            "priority": self.priority,
        }


@dataclass
class EvolutionResult:
    """进化结果"""
    skill_id: str
    strategy: EvolutionStrategy
    status: EvolutionStatus
    improvements: List[str]
    metrics_before: Dict[str, float]
    metrics_after: Dict[str, float]
    started_at: datetime.datetime
    completed_at: Optional[datetime.datetime] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "strategy": self.strategy.value,
            "status": self.status.value,
            "improvements": self.improvements,
            "metrics_before": self.metrics_before,
            "metrics_after": self.metrics_after,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
        }


class EvolutionEngine:
    """
    技能进化引擎
    
    分析技能表现，制定进化策略，驱动技能自动优化。
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._goals: Dict[str, List[EvolutionGoal]] = {}  # skill_id -> goals
        self._history: Dict[str, List[EvolutionResult]] = {}  # skill_id -> history
        self._current_status: Dict[str, EvolutionStatus] = {}
        self._metrics: Dict[str, Dict[str, float]] = {}  # skill_id -> metrics
    
    def set_goal(
        self,
        skill_id: str,
        description: str,
        strategy: EvolutionStrategy,
        target_metric: str,
        target_value: float,
        priority: int = 1,
    ) -> EvolutionGoal:
        """设置进化目标"""
        goal_id = f"{skill_id}_{strategy.value}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        goal = EvolutionGoal(
            goal_id=goal_id,
            description=description,
            strategy=strategy,
            target_metric=target_metric,
            target_value=target_value,
            priority=priority,
        )
        
        with self._lock:
            if skill_id not in self._goals:
                self._goals[skill_id] = []
            self._goals[skill_id].append(goal)
            self._goals[skill_id].sort(key=lambda g: g.priority, reverse=True)
        
        logger.info(f"Set evolution goal for skill '{skill_id}': {description}")
        return goal
    
    def get_goals(self, skill_id: str) -> List[EvolutionGoal]:
        """获取技能的进化目标"""
        with self._lock:
            return self._goals.get(skill_id, [])
    
    def update_metrics(self, skill_id: str, metrics: Dict[str, float]) -> None:
        """更新技能指标"""
        with self._lock:
            if skill_id not in self._metrics:
                self._metrics[skill_id] = {}
            self._metrics[skill_id].update(metrics)
            
            # 更新目标进度
            for goal in self._goals.get(skill_id, []):
                if goal.target_metric in metrics:
                    goal.current_value = metrics[goal.target_metric]
    
    def analyze_evolution_potential(self, skill_id: str) -> Dict[str, Any]:
        """分析技能的进化潜力"""
        with self._lock:
            goals = self._goals.get(skill_id, [])
            metrics = self._metrics.get(skill_id, {})
            
            if not goals:
                return {"skill_id": skill_id, "potential": "none", "reason": "no goals set"}
            
            # 计算每个目标的差距
            gaps = []
            for goal in goals:
                if goal.target_metric in metrics:
                    current = metrics[goal.target_metric]
                    gap = goal.target_value - current
                    gaps.append({
                        "goal": goal.description,
                        "strategy": goal.strategy.value,
                        "gap": gap,
                        "progress": current / goal.target_value if goal.target_value > 0 else 0,
                    })
            
            # 确定最佳进化策略
            if gaps:
                best = max(gaps, key=lambda g: abs(g["gap"]))
                return {
                    "skill_id": skill_id,
                    "potential": "high" if abs(best["gap"]) > 0.2 else "medium",
                    "recommended_strategy": best["strategy"],
                    "gaps": gaps,
                }
            
            return {"skill_id": skill_id, "potential": "low", "reason": "goals already met"}
    
    def start_evolution(
        self,
        skill_id: str,
        strategy: EvolutionStrategy,
        metrics_before: Optional[Dict[str, float]] = None,
    ) -> EvolutionResult:
        """
        开始进化过程
        
        Args:
            skill_id: 技能ID
            strategy: 进化策略
            metrics_before: 进化前的指标
            
        Returns:
            进化结果
        """
        with self._lock:
            if self._current_status.get(skill_id) == EvolutionStatus.EVOLVING:
                raise ValueError(f"Skill '{skill_id}' is already evolving")
            
            self._current_status[skill_id] = EvolutionStatus.EVOLVING
        
        started_at = datetime.datetime.now(datetime.timezone.utc)
        
        result = EvolutionResult(
            skill_id=skill_id,
            strategy=strategy,
            status=EvolutionStatus.ANALYZING,
            improvements=[],
            metrics_before=metrics_before or self._metrics.get(skill_id, {}),
            metrics_after={},
            started_at=started_at,
        )
        
        try:
            # 模拟进化过程
            result.status = EvolutionStatus.EVOLVING
            
            # 根据策略生成改进
            if strategy == EvolutionStrategy.PERFORMANCE:
                result.improvements.append("Optimized core algorithm")
                result.improvements.append("Reduced memory usage")
            elif strategy == EvolutionStrategy.ADAPTATION:
                result.improvements.append("Added new input format support")
                result.improvements.append("Improved error handling")
            elif strategy == EvolutionStrategy.CONSOLIDATION:
                result.improvements.append("Consolidated successful patterns")
                result.improvements.append("Updated documentation")
            elif strategy == EvolutionStrategy.EXPLORATION:
                result.improvements.append("Experimented with new approach")
                result.improvements.append("Added alternative implementation")
            
            # 模拟指标改进
            result.metrics_after = {
                k: v * 1.1 for k, v in result.metrics_before.items()
            }
            
            result.status = EvolutionStatus.COMPLETED
            result.completed_at = datetime.datetime.now(datetime.timezone.utc)
            
        except Exception as e:
            result.status = EvolutionStatus.FAILED
            result.error_message = str(e)
            logger.error(f"Evolution failed for skill '{skill_id}': {e}")
        
        finally:
            with self._lock:
                self._current_status[skill_id] = result.status
                if skill_id not in self._history:
                    self._history[skill_id] = []
                self._history[skill_id].append(result)
        
        logger.info(f"Evolution {result.status.value} for skill '{skill_id}'")
        return result
    
    def get_evolution_history(self, skill_id: str) -> List[EvolutionResult]:
        """获取进化历史"""
        with self._lock:
            return self._history.get(skill_id, [])
    
    def get_status(self, skill_id: str) -> EvolutionStatus:
        """获取当前进化状态"""
        with self._lock:
            return self._current_status.get(skill_id, EvolutionStatus.IDLE)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total_evolutions = sum(len(h) for h in self._history.values())
            successful = sum(
                1 for h in self._history.values()
                for r in h if r.status == EvolutionStatus.COMPLETED
            )
            
            return {
                "skills_with_goals": len(self._goals),
                "total_goals": sum(len(g) for g in self._goals.values()),
                "total_evolutions": total_evolutions,
                "successful_evolutions": successful,
                "success_rate": successful / total_evolutions if total_evolutions > 0 else 0,
            }


# 全局单例
_evolution_engine: Optional[EvolutionEngine] = None
_engine_lock = threading.Lock()


def get_evolution_engine() -> EvolutionEngine:
    """获取全局进化引擎单例"""
    global _evolution_engine
    if _evolution_engine is None:
        with _engine_lock:
            if _evolution_engine is None:
                _evolution_engine = EvolutionEngine()
    return _evolution_engine


def reset_evolution_engine() -> None:
    """重置全局进化引擎（用于测试）"""
    global _evolution_engine
    with _engine_lock:
        _evolution_engine = None
