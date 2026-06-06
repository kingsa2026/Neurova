"""
MetaCognition - Agent元认知模块

提供自我监控、自我反思、自我优化能力。
让Agent能够"思考自己的思考"。
线程安全，每个Agent拥有独立的元认知实例。

Neurova 2.0 改进：
- 集成 ExperienceKnowledgeBase，将反思结果保存到经验知识库
- 支持经验复用，在类似场景下调用历史经验

...
"""

from dataclasses import dataclass
import datetime
import logging
import threading
import time
import typing

from neurova.skills.models import ExperienceRecord

# cognitive_layers imports
import neurova.cognitive_layers.meta_cognition_layer.root_cause_analyzer
import neurova.cognitive_layers.meta_cognition_layer.tool_history

# skills imports
import neurova.skills.auto_skill_improver
import neurova.skills.experience_knowledge_base
import neurova.skills.models

@dataclass
class HealthMetrics:
    """健康指标"""
    timestamp: datetime.datetime
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    response_time_ms: float = 0.0
    success_rate: float = 0.0
    error_count: int = 0
    active_tasks: int = 0
    queue_size: int = 0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "response_time_ms": self.response_time_ms,
            "success_rate": self.success_rate,
            "error_count": self.error_count,
            "active_tasks": self.active_tasks,
            "queue_size": self.queue_size,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HealthMetrics":
        return cls(
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            cpu_usage=data.get("cpu_usage", 0.0),
            memory_usage=data.get("memory_usage", 0.0),
            response_time_ms=data.get("response_time_ms", 0.0),
            success_rate=data.get("success_rate", 0.0),
            error_count=data.get("error_count", 0),
            active_tasks=data.get("active_tasks", 0),
            queue_size=data.get("queue_size", 0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ReflectionReport:
    """反思报告"""
    report_id: str
    timestamp: datetime.datetime
    trigger: str
    observations: List[str] = None
    insights: List[str] = None
    action_items: List[str] = None
    confidence: float = 0.0
    impact_score: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.observations is None:
            self.observations = []
        if self.insights is None:
            self.insights = []
        if self.action_items is None:
            self.action_items = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp.isoformat(),
            "trigger": self.trigger,
            "observations": self.observations,
            "insights": self.insights,
            "action_items": self.action_items,
            "confidence": self.confidence,
            "impact_score": self.impact_score,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReflectionReport":
        return cls(
            report_id=data["report_id"],
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            trigger=data["trigger"],
            observations=data.get("observations", []),
            insights=data.get("insights", []),
            action_items=data.get("action_items", []),
            confidence=data.get("confidence", 0.0),
            impact_score=data.get("impact_score", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class OptimizationReport:
    """优化报告"""
    report_id: str
    timestamp: datetime.datetime
    target: str
    optimizations: List[Dict[str, Any]] = None
    improvements: List[Dict[str, Any]] = None
    before_metrics: Dict[str, float] = None
    after_metrics: Dict[str, float] = None
    improvement_percentage: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.optimizations is None:
            self.optimizations = []
        if self.improvements is None:
            self.improvements = []
        if self.before_metrics is None:
            self.before_metrics = {}
        if self.after_metrics is None:
            self.after_metrics = {}
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp.isoformat(),
            "target": self.target,
            "optimizations": self.optimizations,
            "improvements": self.improvements,
            "before_metrics": self.before_metrics,
            "after_metrics": self.after_metrics,
            "improvement_percentage": self.improvement_percentage,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OptimizationReport":
        return cls(
            report_id=data["report_id"],
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            target=data["target"],
            optimizations=data.get("optimizations", []),
            improvements=data.get("improvements", []),
            before_metrics=data.get("before_metrics", {}),
            after_metrics=data.get("after_metrics", {}),
            improvement_percentage=data.get("improvement_percentage", 0.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SkillEvolutionReport:
    """技能进化报告"""
    report_id: str
    timestamp: datetime.datetime
    skill_id: str
    evolution_type: str
    changes: List[Dict[str, Any]] = None
    performance_before: Dict[str, float] = None
    performance_after: Dict[str, float] = None
    success: bool = False
    reason: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.changes is None:
            self.changes = []
        if self.performance_before is None:
            self.performance_before = {}
        if self.performance_after is None:
            self.performance_after = {}
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp.isoformat(),
            "skill_id": self.skill_id,
            "evolution_type": self.evolution_type,
            "changes": self.changes,
            "performance_before": self.performance_before,
            "performance_after": self.performance_after,
            "success": self.success,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillEvolutionReport":
        return cls(
            report_id=data["report_id"],
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            skill_id=data["skill_id"],
            evolution_type=data["evolution_type"],
            changes=data.get("changes", []),
            performance_before=data.get("performance_before", {}),
            performance_after=data.get("performance_after", {}),
            success=data.get("success", False),
            reason=data.get("reason", ""),
            metadata=data.get("metadata", {}),
        )

class MetaCognition:
    """Agent元认知模块：自我监控、自我反思、自我优化、技能进化"""

    def __init__(
        self,
        memory_manager: Any = None,
        tool_history: Any = None,
        root_cause_analyzer: Any = None,
        self_reflection: Any = None,
        self_optimization: Any = None,
        skills_manager: Any = None,
        experience_knowledge_base: Any = None,
        auto_skill_improver: Any = None,
        monitor_interval: int = 300,
        reflect_interval: int = 600,
        optimize_interval: int = 1800,
    ):
        self._memory_manager = memory_manager
        self._tool_history = tool_history
        self._root_cause_analyzer = root_cause_analyzer
        self._self_reflection = self_reflection
        self._self_optimization = self_optimization
        self._skills_manager = skills_manager
        self._experience_kb = experience_knowledge_base
        self._auto_skill_improver = auto_skill_improver
        self._monitor_interval = monitor_interval
        self._reflect_interval = reflect_interval
        self._optimize_interval = optimize_interval
        self._last_monitor_time = 0.0
        self._last_reflect_time = 0.0
        self._last_optimize_time = 0.0
        self._last_evolve_time = 0.0
        self._health_metrics: List[HealthMetrics] = []
        self._reflection_reports: List[ReflectionReport] = []
        self._optimization_reports: List[OptimizationReport] = []
        self._skill_reports: List[SkillEvolutionReport] = []
        self._stats = {"monitors": 0, "reflections": 0, "optimizations": 0, "evolutions": 0, "anomalies": 0}
        self._lock = threading.RLock()
        logger.info("MetaCognition initialized")

    def monitor(self, agent_state: Optional[Dict[str, Any]] = None) -> HealthMetrics:
        with self._lock:
            try:
                metrics = self._collect_health_metrics(agent_state)
                self._health_metrics.append(metrics)
                if len(self._health_metrics) > 1000:
                    self._health_metrics = self._health_metrics[-500:]
                self._stats["monitors"] += 1
                self._last_monitor_time = time.time()
                self._check_health_alerts(metrics)
                return metrics
            except Exception as e:
                logger.error(f"monitor failed: {e}")
                return HealthMetrics(timestamp=datetime.datetime.now(datetime.timezone.utc), metadata={"error": str(e)})

    def reflect(self, trigger: str = "periodic") -> ReflectionReport:
        with self._lock:
            try:
                report_id = f"ref_{int(time.time() * 1000)}"
                observations, insights, actions = [], [], []
                tool_insights = self._analyze_tool_usage()
                if tool_insights:
                    observations.extend(tool_insights.get("observations", []))
                    insights.extend(tool_insights.get("insights", []))
                    actions.extend(tool_insights.get("action_items", []))
                anomalies = self._detect_tool_anomalies()
                if anomalies:
                    self._stats["anomalies"] += len(anomalies)
                    observations.extend([f"tool anomaly: {a.get('tool_name','')}" for a in anomalies])
                quality = self._evaluate_tool_selection_quality()
                if quality is not None:
                    insights.append(f"tool selection quality: {quality:.2f}")
                    if quality < 0.7:
                        actions.append("improve tool selection strategy")
                mem_patterns = self._analyze_memory_patterns()
                if mem_patterns:
                    observations.extend(mem_patterns.get("observations", []))
                    insights.extend(mem_patterns.get("insights", []))
                sys_anomalies = self._detect_anomalies()
                observations.extend(sys_anomalies)
                gen_insights = self._generate_insights()
                insights.extend(gen_insights)
                confidence = self._calculate_reflection_score(observations, insights, actions)
                report = ReflectionReport(
                    report_id=report_id, timestamp=datetime.datetime.now(datetime.timezone.utc),
                    trigger=trigger, observations=observations, insights=insights,
                    action_items=actions, confidence=confidence,
                    impact_score=len(insights) * 0.1 + len(actions) * 0.05,
                )
                self._reflection_reports.append(report)
                if len(self._reflection_reports) > 100:
                    self._reflection_reports = self._reflection_reports[-50:]
                self._stats["reflections"] += 1
                self._last_reflect_time = time.time()
                return report
            except Exception as e:
                logger.error(f"reflect failed: {e}")
                return ReflectionReport(
                    report_id=f"ref_err_{int(time.time())}", timestamp=datetime.datetime.now(datetime.timezone.utc),
                    trigger=trigger, observations=[f"reflection error: {e}"],
                )

    def set_tool_history(self, tool_history: Any) -> None:
        with self._lock:
            self._tool_history = tool_history

    def set_root_cause_analyzer(self, analyzer: Any) -> None:
        with self._lock:
            self._root_cause_analyzer = analyzer

    def _analyze_tool_usage(self) -> Optional[Dict[str, Any]]:
        if not self._tool_history:
            return None
        try:
            stats = self._tool_history.get_usage_stats()
            if not stats:
                return None
            observations, insights, actions = [], [], []
            for name, s in stats.items():
                if isinstance(s, dict):
                    sr = s.get("success_rate", 0.0)
                    tc = s.get("total_calls", 0)
                    if tc >= 10 and sr < 0.7:
                        observations.append(f"tool {name} low success rate: {sr:.1%}")
                        actions.append(f"investigate tool {name}")
                    elif tc >= 10 and sr > 0.95:
                        insights.append(f"tool {name} excellent: {sr:.1%}")
            degraded = self._tool_history.get_degraded_tools()
            if degraded:
                observations.append(f"{len(degraded)} degraded tools")
            return {"observations": observations, "insights": insights, "action_items": actions}
        except Exception as e:
            logger.error(f"_analyze_tool_usage failed: {e}")
            return None

    def _detect_tool_anomalies(self) -> List[Dict[str, Any]]:
        if not self._tool_history:
            return []
        try:
            anomalies = self._tool_history.detect_anomalies()
            return [a.to_dict() if hasattr(a, "to_dict") else a for a in anomalies]
        except Exception as e:
            logger.error(f"_detect_tool_anomalies failed: {e}")
            return []

    def _evaluate_tool_selection_quality(self) -> Optional[float]:
        if not self._tool_history:
            return None
        try:
            pairs = self._tool_history.find_tool_pairs()
            if not pairs:
                return None
            return min(sum(p[2] for p in pairs) / len(pairs), 1.0)
        except Exception:
            return None

    def write_tool_insight_to_memory(self, insight: Dict[str, Any]) -> bool:
        if not self._memory_manager:
            return False
        try:
            content = f"tool insight: {insight.get('description', '')}"
            meta = {"type": "tool_insight", "tool_name": insight.get("tool_name", ""), "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()}
            if hasattr(self._memory_manager, "remember"):
                self._memory_manager.remember(content=content, memory_type="tool_insight", importance=0.6, metadata=meta)
                return True
            return False
        except Exception:
            return False

    def _collect_health_metrics(self, agent_state: Optional[Dict[str, Any]] = None) -> HealthMetrics:
        try:
            import psutil
            cpu_usage = psutil.cpu_percent(interval=0.1)
            memory_usage = psutil.virtual_memory().percent
        except ImportError:
            cpu_usage, memory_usage = 0.0, 0.0
        state = agent_state or {}
        return HealthMetrics(
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            cpu_usage=cpu_usage, memory_usage=memory_usage,
            response_time_ms=state.get("response_time_ms", 0.0),
            success_rate=state.get("success_rate", 1.0),
            error_count=state.get("error_count", 0),
            active_tasks=state.get("active_tasks", 0),
            queue_size=state.get("queue_size", 0),
        )

    def _analyze_memory_patterns(self) -> Optional[Dict[str, Any]]:
        if not self._memory_manager:
            return None
        try:
            if hasattr(self._memory_manager, "get_stats"):
                stats = self._memory_manager.get_stats()
                if stats:
                    return {"observations": [f"total memories: {stats.get('total_memories', 0)}"], "insights": []}
            return None
        except Exception:
            return None

    def _detect_anomalies(self) -> List[str]:
        anomalies = []
        if self._health_metrics:
            latest = self._health_metrics[-1]
            if latest.cpu_usage > 90: anomalies.append(f"high CPU: {latest.cpu_usage:.1f}%")
            if latest.memory_usage > 90: anomalies.append(f"high memory: {latest.memory_usage:.1f}%")
            if latest.response_time_ms > 10000: anomalies.append(f"slow response: {latest.response_time_ms:.0f}ms")
            if latest.success_rate < 0.8: anomalies.append(f"low success rate: {latest.success_rate:.1%}")
        return anomalies

    def _generate_insights(self) -> List[str]:
        insights = []
        if len(self._reflection_reports) >= 3:
            avg = sum(r.confidence for r in self._reflection_reports[-3:]) / 3
            if avg > 0.8: insights.append("high reflection quality")
            elif avg < 0.5: insights.append("reflection quality needs improvement")
        if self._optimization_reports:
            last = self._optimization_reports[-1]
            if last.improvement_percentage > 10: insights.append("recent optimization effective")
        return insights

    def _optimize_temperature(self) -> Optional[Dict[str, Any]]:
        if not self._health_metrics:
            return None
        latest = self._health_metrics[-1]
        current_temp = 0.7
        if latest.success_rate < 0.8:
            return {"parameter": "temperature", "old": current_temp, "new": max(current_temp - 0.1, 0.1), "reason": "low success rate"}
        elif latest.success_rate > 0.95 and latest.response_time_ms < 5000:
            return {"parameter": "temperature", "old": current_temp, "new": min(current_temp + 0.1, 1.0), "reason": "good performance"}
        return None

    def _prune_memories(self) -> Optional[Dict[str, Any]]:
        if not self._memory_manager:
            return None
        try:
            if hasattr(self._memory_manager, "get_stats"):
                stats = self._memory_manager.get_stats()
                if stats and stats.get("total_memories", 0) > 1000:
                    if hasattr(self._memory_manager, "prune"):
                        pruned = self._memory_manager.prune(max_memories=800)
                        return {"action": "prune_memories", "pruned": pruned}
            return None
        except Exception:
            return None

    def _restructure_associations(self) -> Optional[Dict[str, Any]]:
        if not self._memory_manager or not hasattr(self._memory_manager, "restructure_associations"):
            return None
        try:
            result = self._memory_manager.restructure_associations()
            return {"action": "restructure", "result": result} if result else None
        except Exception:
            return None

    def _optimize_skills(self) -> Optional[Dict[str, Any]]:
        if not self._auto_skill_improver or not self._skills_manager:
            return None
        try:
            if hasattr(self._skills_manager, "get_all_skills"):
                skills = self._skills_manager.get_all_skills()
                improvements = []
                for skill in skills[:3]:
                    if hasattr(skill, "performance_metrics"):
                        imp = self._auto_skill_improver.analyze_skill_performance(skill.skill_id, skill.performance_metrics)
                        improvements.extend(imp)
                if improvements:
                    return {"action": "optimize_skills", "count": len(improvements)}
            return None
        except Exception:
            return None

    def _optimize_tools(self) -> Optional[Dict[str, Any]]:
        if not self._tool_history:
            return None
        try:
            pairs = self._tool_history.find_tool_pairs()
            if pairs:
                return {"action": "optimize_tools", "pairs": len(pairs)}
            return None
        except Exception:
            return None

    def get_tool_health(self, tool_name: str) -> Dict[str, Any]:
        if not self._tool_history:
            return {"status": "unknown", "message": "no tool history"}
        try:
            if hasattr(self._tool_history, "get_usage_stats"):
                stats = self._tool_history.get_usage_stats(tool_name)
                if stats:
                    sr = stats.get("success_rate", 0.0)
                    tc = stats.get("total_calls", 0)
                    if tc == 0: status, msg = "unknown", "no records"
                    elif sr >= 0.9: status, msg = "healthy", "running well"
                    elif sr >= 0.7: status, msg = "warning", "low success rate"
                    elif sr >= 0.5: status, msg = "degraded", "performance decline"
                    else: status, msg = "unhealthy", "serious issues"
                    return {"tool_name": tool_name, "status": status, "success_rate": sr, "total_calls": tc, "message": msg}
            return {"status": "unknown", "message": "no stats available"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _extract_task_patterns(self) -> List[Dict[str, Any]]:
        patterns = []
        if self._reflection_reports:
            recent = self._reflection_reports[-10:]
            obs_count = {}
            for r in recent:
                for o in r.observations:
                    obs_count[o] = obs_count.get(o, 0) + 1
            for obs, cnt in obs_count.items():
                if cnt >= 3:
                    patterns.append({"type": "observation_pattern", "description": obs, "frequency": cnt, "confidence": min(cnt / len(recent), 1.0)})
        if self._tool_history:
            try:
                for t1, t2, conf in self._tool_history.find_tool_pairs()[:3]:
                    patterns.append({"type": "tool_pair", "description": f"{t1}+{t2}", "confidence": conf})
            except Exception:
                pass
        return patterns

    def _auto_generate_skill(self, task_patterns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not self._skills_manager or not task_patterns:
            return None
        frequent = [p for p in task_patterns if p.get("frequency", 0) >= 3]
        if not frequent:
            return None
        p = frequent[0]
        return {"action": "auto_generate", "description": f"auto skill: {p['description']}", "confidence": p.get("confidence", 0.5)}

    def _optimize_existing_skills(self, skill_id: str) -> Optional[Dict[str, Any]]:
        if not self._auto_skill_improver or not self._skills_manager:
            return None
        try:
            if hasattr(self._skills_manager, "get_skill"):
                skill = self._skills_manager.get_skill(skill_id)
                if skill and hasattr(skill, "performance_metrics"):
                    imp = self._auto_skill_improver.analyze_skill_performance(skill_id, skill.performance_metrics)
                    if imp:
                        return {"action": "optimize_skill", "skill_id": skill_id, "improvements": [i.description for i in imp]}
            return None
        except Exception:
            return None

    def _prune_low_quality_skills(self) -> List[Dict[str, Any]]:
        if not self._skills_manager:
            return []
        pruned = []
        try:
            if hasattr(self._skills_manager, "get_all_skills"):
                for skill in self._skills_manager.get_all_skills():
                    if hasattr(skill, "success_rate") and skill.success_rate < 0.3:
                        pruned.append({"action": "prune_skill", "skill_id": skill.skill_id, "success_rate": skill.success_rate})
        except Exception:
            pass
        return pruned

    def _calculate_reflection_score(self, observations: List[str], insights: List[str], actions: List[str]) -> float:
        score = 0.0
        if observations: score += min(len(observations) * 0.1, 0.3)
        if insights: score += min(len(insights) * 0.15, 0.4)
        if actions: score += min(len(actions) * 0.1, 0.3)
        return min(score, 1.0)

    def _calculate_optimization_score(self, optimizations: List[Dict[str, Any]], improvements: List[Dict[str, Any]]) -> float:
        score = 0.0
        if optimizations: score += min(len(optimizations) * 0.2, 0.5)
        if improvements: score += min(len(improvements) * 0.15, 0.5)
        return min(score, 1.0)

    def _check_health_alerts(self, metrics: HealthMetrics) -> None:
        if metrics.cpu_usage > 90 or metrics.memory_usage > 90 or metrics.success_rate < 0.5:
            self._stats["health_alerts"] = self._stats.get("health_alerts", 0) + 1

    def should_monitor(self) -> bool:
        return time.time() - self._last_monitor_time >= self._monitor_interval

    def should_reflect(self) -> bool:
        return time.time() - self._last_reflect_time >= self._reflect_interval

    def should_optimize(self) -> bool:
        return time.time() - self._last_optimize_time >= self._optimize_interval

    def should_evolve_skills(self) -> bool:
        return time.time() - self._last_evolve_time >= 3600

    def get_health_report(self) -> Dict[str, Any]:
        with self._lock:
            latest = self._health_metrics[-1].to_dict() if self._health_metrics else {}
            return {"latest": latest, "history_count": len(self._health_metrics), "stats": self._stats}

    def get_reflection_report(self) -> Dict[str, Any]:
        with self._lock:
            latest = self._reflection_reports[-1].to_dict() if self._reflection_reports else {}
            return {"latest": latest, "history_count": len(self._reflection_reports)}

    def get_optimization_report(self) -> Dict[str, Any]:
        with self._lock:
            latest = self._optimization_reports[-1].to_dict() if self._optimization_reports else {}
            return {"latest": latest, "history_count": len(self._optimization_reports)}

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._stats)

    def __repr__(self) -> str:
        return f"MetaCognition(monitors={self._stats['monitors']}, reflections={self._stats['reflections']}, optimizations={self._stats['optimizations']})"
