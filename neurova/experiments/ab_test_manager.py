"""
Neurova A/B Testing Framework for Multi-Agent Coordination
A/B 测试框架，用于评估 coordination rules 的效果

"""

import asyncio
import math
import random
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import json
from enum import Enum

from neurova.core.logger import get_logger

logger = get_logger(__name__)

class ExperimentGroup(str, Enum):
    """Experiment groups"""
    CONTROL = "control"      # No coordination rules
    TREATMENT = "treatment"  # With coordination rules

@dataclass
class ExperimentConfig:
    """Experiment configuration"""
    name: str
    description: str
    groups: List[ExperimentGroup]
    traffic_split: Dict[ExperimentGroup, float]  # Must sum to 1.0
    metrics: List[str]
    duration_days: int
    min_sample_size: int = 100

    def validate(self) -> bool:
        """Validate experiment config"""
        total = sum(self.traffic_split.values())
        if abs(total - 1.0) > 0.01:
            logger.error(f"Traffic split must sum to 1.0, got {total}")
            return False

        for group in self.groups:
            if group not in self.traffic_split:
                logger.error(f"Missing traffic split for group {group}")
                return False

        return True

@dataclass
class ExperimentResult:
    """Single experiment result"""
    experiment_name: str
    start_time: datetime
    end_time: Optional[datetime] = None
    completed: bool = False

    # Per-group statistics
    group_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Raw data
    samples: List[Dict[str, Any]] = field(default_factory=list)

    def add_sample(
        self,
        group: ExperimentGroup,
        metrics: Dict[str, Any],
        context: Dict[str, Any],
    ) -> None:
        """Add sample to experiment"""
        sample = {
            "timestamp": datetime.utcnow().isoformat(),
            "group": group.value,
            "metrics": metrics,
            "context": context,
        }

        self.samples.append(sample)

        # Update group stats
        if group.value not in self.group_stats:
            self.group_stats[group.value] = {
                "count": 0,
                "metrics_sum": {m: 0.0 for m in metrics.keys()},
            }

        stats = self.group_stats[group.value]
        stats["count"] += 1

        for metric_name, metric_value in metrics.items():
            stats["metrics_sum"][metric_name] += metric_value

    def compute_statistics(self) -> Dict[str, Any]:
        """Compute per-group statistics"""
        stats = {}

        for group, data in self.group_stats.items():
            count = data["count"]
            if count == 0:
                continue

            avg_metrics = {
                key: value / count
                for key, value in data["metrics_sum"].items()
            }

            stats[group] = {
                "sample_count": count,
                "average_metrics": avg_metrics,
            }

        return stats

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "experiment_name": self.experiment_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "completed": self.completed,
            "statistics": self.compute_statistics(),
            "total_samples": len(self.samples),
        }

class ABTestManager:
    """
    A/B test manager for multi-agent coordination

    Features:
    - Traffic splitting based on agent_id hash
    - Automatic experiment lifecycle management
    - Statistical significance calculation
    - Result aggregation and reporting

    Usage:
      manager = await get_ab_test_manager()

      # Define experiment
      config = ExperimentConfig(
          name="coordination_rules_v1",
          description="Test GLANCE_YIELD_RULES effectiveness",
          groups=[ExperimentGroup.CONTROL, ExperimentGroup.TREATMENT],
          traffic_split={
              ExperimentGroup.CONTROL: 0.5,
              ExperimentGroup.TREATMENT: 0.5,
          },
          metrics=["task_completion_rate", "avg_turn_latency_ms"],
          duration_days=7,
          min_sample_size=100,
      )

      # Start experiment
      await manager.start_experiment(config)

      # Assign agent to group
      group = await manager.get_experiment_group("agent_123", "coordination_rules_v1")

      # Record metrics
      await manager.record_metric(
          experiment_name="coordination_rules_v1",
          group=group,
          metrics={"task_completion_rate": 0.8, "avg_turn_latency_ms": 150},
          context={"task_type": "coding"},
      )

      # End experiment after duration
      await manager.end_experiment("coordination_rules_v1")

      # Get results
      results = await manager.get_experiment_results("coordination_rules_v1")
    """

    def __init__(self):
        self._experiments: Dict[str, ExperimentConfig] = {}
        self._results: Dict[str, ExperimentResult] = {}
        self._active_assignments: Dict[str, str] = {}  # agent_id -> experiment_name

        logger.info("ABTestManager initialized")

    async def start_experiment(self, config: ExperimentConfig) -> bool:
        """Start new experiment"""
        # Validate config
        if not config.validate():
            logger.error(f"Invalid experiment config: {config.name}")
            return False

        # Check if experiment already exists
        if config.name in self._experiments:
            logger.warning(f"Experiment {config.name} already exists")
            return False

        # Store config
        self._experiments[config.name] = config

        # Initialize result tracker
        self._results[config.name] = ExperimentResult(
            experiment_name=config.name,
            start_time=datetime.utcnow(),
        )

        logger.info(
            f"Started experiment: {config.name} - "
            f"{len(config.groups)} groups, "
            f"duration={config.duration_days} days"
        )

        return True

    async def get_experiment_group(
        self,
        agent_id: str,
        experiment_name: str,
    ) -> Optional[ExperimentGroup]:
        """
        Assign agent to experiment group based on hash

        Uses consistent hashing to ensure same agent always gets same group
        """
        if experiment_name not in self._experiments:
            logger.error(f"Unknown experiment: {experiment_name}")
            return None

        config = self._experiments[experiment_name]

        # Check cache first
        cached_group = self._active_assignments.get(agent_id)
        if cached_group == experiment_name:
            # Return previously assigned group
            # (In production, would store in persistent storage)
            pass

        # Compute hash
        hash_value = self._hash_agent_id(agent_id, experiment_name)

        # Determine group based on traffic split
        cumulative = 0.0
        for group, probability in config.traffic_split.items():
            cumulative += probability
            if hash_value < cumulative:
                logger.debug(
                    f"Assigned {agent_id} to {group.value} "
                    f"in experiment {experiment_name}"
                )
                return group

        # Fallback to first group
        return config.groups[0]

    def _hash_agent_id(self, agent_id: str, experiment_name: str) -> float:
        """Hash agent_id + experiment_name to [0, 1)"""
        import hashlib

        combined = f"{agent_id}:{experiment_name}"
        hash_bytes = hashlib.md5(combined.encode()).hexdigest()
        hash_int = int(hash_bytes[:8], 16)

        return hash_int / 0xFFFFFFFF

    async def record_metric(
        self,
        experiment_name: str,
        group: ExperimentGroup,
        metrics: Dict[str, Any],
        context: Dict[str, Any],
    ) -> None:
        """Record metric for experiment"""
        if experiment_name not in self._results:
            logger.error(f"Unknown experiment: {experiment_name}")
            return

        result = self._results[experiment_name]
        result.add_sample(group, metrics, context)

        logger.debug(
            f"Recorded metric for {experiment_name}: "
            f"group={group.value}, samples={len(result.samples)}"
        )

    async def end_experiment(self, experiment_name: str) -> bool:
        """End experiment and mark as completed"""
        if experiment_name not in self._results:
            logger.error(f"Unknown experiment: {experiment_name}")
            return False

        result = self._results[experiment_name]
        result.end_time = datetime.utcnow()
        result.completed = True

        logger.info(f"Ended experiment: {experiment_name}")

        return True

    async def get_experiment_results(self, experiment_name: str) -> Optional[Dict[str, Any]]:
        """Get experiment results"""
        if experiment_name not in self._results:
            return None

        result = self._results[experiment_name]

        # Check if completed
        if not result.completed:
            logger.warning(f"Experiment {experiment_name} not yet completed")
            return None

        # Compute statistics
        stats = result.compute_statistics()

        # Calculate statistical significance (Welch t-test, sample-size honest)
        config = self._experiments.get(experiment_name)
        significance = self._calculate_significance(
            stats,
            samples=result.samples,
            metrics=list(config.metrics) if config else None,
            minSampleSize=int(config.min_sample_size) if config else 100,
        )

        return {
            **result.to_dict(),
            "statistical_significance": significance,
        }

    def _calculate_significance(
        self,
        stats: Dict[str, Any],
        samples: Optional[List[Dict[str, Any]]] = None,
        metrics: Optional[List[str]] = None,
        minSampleSize: int = 100,
    ) -> Dict[str, Any]:
        """两组均值差 Welch t 检验；样本不足先报不足，不拿恒真式冒充显著。

        原实现 `ratio = max(a,b)/max(a,b)` 恒等于 1，`significant` 永远为真——
        这正是"看起来有检验、实际什么都没检"的形状。现在：
        - 任一组样本数 < min_sample_size → `insufficient_sample`；
        - 对配置里第一个两组都有的指标算 Welch t 与双侧 p；
        - 方差都为 0 时按均值是否相等给 p=0/1，避免 0/0。
        """
        if len(stats) < 2:
            return {"significant": False, "reason": "insufficient_groups"}
        groups = list(stats.keys())
        group1, group2 = groups[0], groups[1]
        count1 = int(stats[group1]["sample_count"])
        count2 = int(stats[group2]["sample_count"])
        if count1 < minSampleSize or count2 < minSampleSize:
            return {
                "significant": False,
                "reason": "insufficient_sample",
                "min_sample_size": int(minSampleSize),
                "group1_count": count1,
                "group2_count": count2,
            }
        if not samples:
            return {
                "significant": False,
                "reason": "no_raw_samples",
                "group1_count": count1,
                "group2_count": count2,
            }

        common = [
            name for name in (metrics or [])
            if name in stats[group1]["average_metrics"]
            and name in stats[group2]["average_metrics"]
        ]
        if not common:
            common = sorted(
                set(stats[group1]["average_metrics"])
                & set(stats[group2]["average_metrics"])
            )
        for metric in common:
            values1 = self._metricValues(samples, group1, metric)
            values2 = self._metricValues(samples, group2, metric)
            if len(values1) < 2 or len(values2) < 2:
                continue
            mean1 = sum(values1) / len(values1)
            mean2 = sum(values2) / len(values2)
            var1 = self._variance(values1, mean1)
            var2 = self._variance(values2, mean2)
            standardError = math.sqrt(var1 / len(values1) + var2 / len(values2))
            if standardError == 0.0:
                pValue = 0.0 if abs(mean1 - mean2) > 1e-12 else 1.0
            else:
                tStatistic = (mean1 - mean2) / standardError
                pValue = math.erfc(abs(tStatistic) / math.sqrt(2))
            return {
                "significant": bool(pValue < 0.05),
                "reason": "welch_t_test",
                "metric": metric,
                "group1_mean": round(mean1, 6),
                "group2_mean": round(mean2, 6),
                "delta": round(mean1 - mean2, 6),
                "p_value": round(pValue, 6),
                "group1_count": count1,
                "group2_count": count2,
            }
        return {
            "significant": False,
            "reason": "no_comparable_metric",
            "group1_count": count1,
            "group2_count": count2,
        }

    @staticmethod
    def _metricValues(samples: List[Dict[str, Any]], group: str, metric: str) -> List[float]:
        values: List[float] = []
        for sample in samples:
            if sample.get("group") != group:
                continue
            value = (sample.get("metrics") or {}).get(metric)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(float(value))
        return values

    @staticmethod
    def _variance(values: List[float], mean: float) -> float:
        if len(values) < 2:
            return 0.0
        return sum((value - mean) ** 2 for value in values) / (len(values) - 1)

    def list_experiments(self) -> List[Dict[str, Any]]:
        """List all experiments"""
        experiments = []

        for name, config in self._experiments.items():
            result = self._results.get(name)

            experiments.append({
                "name": name,
                "description": config.description,
                "status": "completed" if result and result.completed else "active",
                "groups": [g.value for g in config.groups],
                "sample_count": len(result.samples) if result else 0,
            })

        return experiments

    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive A/B test report"""
        experiments = self.list_experiments()

        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "total_experiments": len(experiments),
            "experiments": experiments,
            "detailed_results": {},
        }

        # Add detailed results for completed experiments
        for exp in experiments:
            if exp["status"] == "completed":
                result = self._results.get(exp["name"])
                if result:
                    report["detailed_results"][exp["name"]] = result.to_dict()

        return report

    def save_report(self, filepath: str) -> None:
        """Save A/B test report to file"""
        report = self.generate_report()

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"A/B test report saved to {filepath}")

# Global instance management
_ab_test_manager_instance: Optional[ABTestManager] = None
_ab_test_manager_lock = asyncio.Lock()

async def get_ab_test_manager() -> ABTestManager:
    """Get global ABTestManager instance"""
    global _ab_test_manager_instance

    if _ab_test_manager_instance is None:
        async with _ab_test_manager_lock:
            if _ab_test_manager_instance is None:
                _ab_test_manager_instance = ABTestManager()

    return _ab_test_manager_instance

async def reset_ab_test_manager() -> None:
    """Reset ABTestManager instance (for testing)"""
    global _ab_test_manager_instance
    _ab_test_manager_instance = None
