"""
流程编排器 - Flow Orchestrator

实现 Neurova 认知架构的完整闭环流程：对话 → 上下文 → 记忆 → 工具 → 经验 → 进化 → 元认知
"""

import copy
import datetime
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ────── Enums ──────

class FlowPhase(Enum):
    IDLE = "idle"
    CONVERSATION = "conversation"
    CONTEXT_BUILD = "context_build"
    MEMORY_CACHE = "memory_cache"
    MEMORY_WRITE = "memory_write"
    MEMORY_RETRIEVAL = "memory_retrieval"
    TOOL_INVOCATION = "tool_invocation"
    RESULT_FEEDBACK = "result_feedback"
    EXPERIENCE_ACCUMULATE = "experience_accumulate"
    EVOLUTION = "evolution"
    SLEEP_CONSOLIDATION = "sleep_consolidation"
    CONFLICT_RESOLUTION = "conflict_resolution"
    METACOGNITION = "metacognition"


class Severity(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ────── Data Classes ──────

@dataclass
class FlowEvent:
    event_id: str
    phase: FlowPhase
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    severity: Severity = Severity.INFO
    duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())


@dataclass
class FlowContext:
    session_id: str = ""
    agent_id: str = ""
    user_id: str = ""
    user_input: str = ""
    system_prompt: str = ""
    token_budget: int = 4000
    current_phase: FlowPhase = FlowPhase.IDLE
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    built_context: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    retrieved_memories: List[Dict[str, Any]] = field(default_factory=list)
    cached_memories: List[Dict[str, Any]] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    sleep_results: Optional[Dict[str, Any]] = None
    experiences: List[Dict[str, Any]] = field(default_factory=list)
    evolution_changes: List[Dict[str, Any]] = field(default_factory=list)
    metacognition_report: Dict[str, Any] = field(default_factory=dict)
    _cycle_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "user_input": self.user_input,
            "current_phase": self.current_phase.value,
            "token_budget": self.token_budget,
            "conversation_history_len": len(self.conversation_history),
            "built_context_len": len(self.built_context),
            "metadata": self.metadata,
        }


# ────── FlowTracer ──────

class FlowTracer:
    def __init__(self, max_events: int = 1000):
        self._events: List[FlowEvent] = []
        self._pending: Dict[str, float] = {}
        self._max_events = max_events

    def start_phase(self, phase: FlowPhase) -> str:
        evt_id = f"evt_{phase.value}_{uuid.uuid4().hex[:8]}"
        self._pending[evt_id] = time.time() * 1000
        return evt_id

    def end_phase(self, event_id: str, phase: FlowPhase, success: bool,
                  data: Optional[Dict[str, Any]] = None, error: Optional[str] = None) -> FlowEvent:
        start_ms = self._pending.pop(event_id, time.time() * 1000)
        duration_ms = (time.time() * 1000) - start_ms
        event = FlowEvent(event_id=event_id, phase=phase, data=data or {},
                          duration_ms=duration_ms, success=success, error=error)
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        return event

    def get_phase_timeline(self, phase: FlowPhase) -> List[FlowEvent]:
        return [e for e in self._events if e.phase == phase]

    def get_stats(self) -> Dict[str, Any]:
        if not self._events:
            return {"total_events": 0}
        phases: Dict[str, Dict[str, int]] = {}
        successes = 0
        for e in self._events:
            name = e.phase.value
            if name not in phases:
                phases[name] = {"count": 0, "successes": 0, "failures": 0}
            phases[name]["count"] += 1
            if e.success:
                phases[name]["successes"] += 1
                successes += 1
            else:
                phases[name]["failures"] += 1
        return {"total_events": len(self._events), "phases": phases,
                "success_rate": successes / len(self._events)}


# ────── MessageFlowManager ──────

class MessageFlowManager:
    def __init__(self, max_history: int = 500):
        self._sessions: Dict[str, List[Dict[str, Any]]] = {}
        self._max_history = max_history
        self._counter = 0

    def receive_message(self, session_id: str, role: str, content: str,
                        metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        self._counter += 1
        msg = {"id": f"msg_{self._counter:06d}", "role": role, "content": content,
               "timestamp": datetime.datetime.now().isoformat(), "metadata": metadata or {}}
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].append(msg)
        if len(self._sessions[session_id]) > self._max_history:
            self._sessions[session_id] = self._sessions[session_id][-self._max_history:]
        return msg

    def get_history(self, session_id: str, limit: int = 0) -> List[Dict[str, Any]]:
        history = self._sessions.get(session_id, [])
        return history[-limit:] if limit > 0 else list(history)

    def clear_history(self, session_id: str) -> int:
        if session_id in self._sessions:
            count = len(self._sessions[session_id])
            self._sessions[session_id] = []
            return count
        return 0

    def get_active_sessions(self) -> List[str]:
        return list(self._sessions.keys())


# ────── ContextMemoryBridge ──────

class ContextMemoryBridge:
    def __init__(self, max_cache_entries: int = 100):
        self._cache: OrderedDict = OrderedDict()
        self._max_cache = max_cache_entries
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def build_context(self, flow_ctx: FlowContext, system_prompt: str = "",
                      external_memories: Optional[List[Dict[str, Any]]] = None,
                      external_experiences: Optional[List[Dict[str, Any]]] = None) -> FlowContext:
        cache_key = f"{flow_ctx.agent_id}:{flow_ctx.session_id}"
        if cache_key in self._cache:
            self._hits += 1
            cached = self._cache[cache_key]
            flow_ctx.built_context = copy.deepcopy(cached["built_context"])
            flow_ctx.cached_memories = copy.deepcopy(cached.get("cached_memories", []))
            return flow_ctx

        self._misses += 1
        context_parts: List[Dict[str, Any]] = []
        if system_prompt:
            context_parts.append({"role": "system", "content": system_prompt})
        for msg in flow_ctx.conversation_history:
            context_parts.append(msg)
        if flow_ctx.user_input:
            context_parts.append({"role": "user", "content": flow_ctx.user_input})
        flow_ctx.built_context = context_parts

        cached_items: List[Dict[str, Any]] = []
        if external_memories:
            cached_items.extend(external_memories)
        if external_experiences:
            cached_items.extend(external_experiences)
        flow_ctx.cached_memories = cached_items

        self._cache[cache_key] = {"built_context": copy.deepcopy(context_parts),
                                   "cached_memories": copy.deepcopy(cached_items)}
        while len(self._cache) > self._max_cache:
            self._cache.popitem(last=False)
            self._evictions += 1
        return flow_ctx

    def invalidate_cache(self, agent_id: str, session_id: str) -> None:
        target_key = f"{agent_id}:{session_id}"
        if target_key in self._cache:
            del self._cache[target_key]

    def get_cache_stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {"hits": self._hits, "misses": self._misses,
                "cache_size": len(self._cache), "evictions": self._evictions,
                "hit_rate": self._hits / total if total > 0 else 0.0}

    def _count_tokens(self, text: str) -> int:
        return len(text) // 4


# ────── MemoryCoordinator ──────

class MemoryCoordinator:
    def __init__(self):
        self._memories: List[Dict[str, Any]] = []
        self._buffer: List[Dict[str, Any]] = []
        self._counter = 0
        self._write_count = 0
        self._retrieve_count = 0

    def write(self, content: str, category: str = "general", temperature: float = 50.0,
              is_important: bool = False, buffered: bool = False) -> str:
        self._counter += 1
        mem_id = f"mem_{self._counter:06d}"
        memory = {"id": mem_id, "content": content, "category": category,
                  "temperature": temperature, "is_important": is_important,
                  "created_at": time.time()}
        if buffered:
            self._buffer.append(memory)
        else:
            self._memories.append(memory)
            self._write_count += 1
        return mem_id

    def retrieve(self, query: str, category: Optional[str] = None,
                 limit: int = 10, min_temperature: float = 0.0) -> List[Dict[str, Any]]:
        self._retrieve_count += 1
        results = list(self._memories)
        if category:
            results = [m for m in results if m["category"] == category]
        if min_temperature > 0:
            results = [m for m in results if m["temperature"] >= min_temperature]
        results.sort(key=lambda m: m["temperature"], reverse=True)
        return [copy.deepcopy(m) for m in results[:limit]]

    def flush_all(self) -> int:
        count = len(self._buffer)
        self._memories.extend(self._buffer)
        self._write_count += count
        self._buffer.clear()
        return count

    def get_stats(self) -> Dict[str, Any]:
        return {"total_memories": len(self._memories), "buffer_size": len(self._buffer),
                "write_count": self._write_count, "retrieve_count": self._retrieve_count}


# ────── ToolFeedbackLoop ──────

class ToolFeedbackLoop:
    def __init__(self):
        self._tool_registry: Dict[str, Any] = {}
        self._feedback_history: List[Dict[str, Any]] = []
        self._stats = {"invocations": 0, "successes": 0, "failures": 0}

    def register_tool(self, tool_name: str, func: Any) -> None:
        self._tool_registry[tool_name] = func

    def unregister_tool(self, tool_name: str) -> None:
        self._tool_registry.pop(tool_name, None)

    async def invoke(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        import inspect
        self._stats["invocations"] += 1
        if tool_name not in self._tool_registry:
            self._stats["failures"] += 1
            return {"success": False, "error": f"Tool not found: {tool_name}", "duration_ms": 0.0}
        start = time.time()
        try:
            func = self._tool_registry[tool_name]
            if inspect.iscoroutinefunction(func):
                result = await func(**params)
            else:
                result = func(**params)
            duration_ms = (time.time() - start) * 1000
            self._stats["successes"] += 1
            return {"success": True, "result": result, "duration_ms": duration_ms}
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            self._stats["failures"] += 1
            return {"success": False, "error": str(e), "duration_ms": duration_ms}

    def collect_feedback(self, invocation_result: Dict[str, Any],
                         user_rating: float = 0.5, comment: str = "") -> Dict[str, Any]:
        should_learn = user_rating < 0.5 or not invocation_result.get("success", True)
        feedback = {"tool_name": invocation_result.get("tool_name", ""),
                    "success": invocation_result.get("success", True),
                    "user_rating": user_rating, "comment": comment,
                    "should_learn": should_learn, "timestamp": time.time()}
        self._feedback_history.append(feedback)
        return feedback

    def get_feedback_stats(self) -> Dict[str, Any]:
        invocations = self._stats["invocations"]
        return {"invocations": invocations, "successes": self._stats["successes"],
                "failures": self._stats["failures"],
                "success_rate": self._stats["successes"] / invocations if invocations > 0 else 0.0}


# ────── ExperienceEvolutionEngine ──────

class ExperienceEvolutionEngine:
    def __init__(self):
        self._experiences: List[Dict[str, Any]] = []
        self._counter = 0
        self._skills_with_exps: Dict[str, int] = {}

    def accumulate_experience(self, context: Dict[str, Any], result: Dict[str, Any],
                               success: bool, skill_name: str = "general") -> str:
        self._counter += 1
        exp_id = f"exp_{self._counter:06d}"
        self._experiences.append({"id": exp_id, "context": context, "result": result,
                                   "success": success, "skill_name": skill_name, "timestamp": time.time()})
        self._skills_with_exps[skill_name] = self._skills_with_exps.get(skill_name, 0) + 1
        return exp_id

    def find_similar_experiences(self, query: str, skill_name: Optional[str] = None,
                                  limit: int = 5) -> List[Dict[str, Any]]:
        candidates = self._experiences
        if skill_name:
            candidates = [e for e in candidates if e["skill_name"] == skill_name]
            if not candidates:
                return []
        query_lower = query.lower()
        scored = []
        for exp in candidates:
            text = str(exp.get("context", {})).lower()
            score = sum(1 for word in query_lower.split() if word in text)
            scored.append((score, exp))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored or scored[0][0] == 0:
            return []
        return [copy.deepcopy(e) for _, e in scored[:limit]]

    def evolve(self, skill_name: str, error_info: Dict[str, Any]) -> Dict[str, Any]:
        skill_exps = [e for e in self._experiences if e["skill_name"] == skill_name]
        if not skill_exps:
            return {"evolved": False, "reason": "no_experiences"}
        failures = [e for e in skill_exps if not e.get("success", True)]
        failure_rate = len(failures) / len(skill_exps)
        suggestions = []
        if failure_rate > 0.5:
            suggestions.append("高失败率，建议优化工具参数")
        if len(failures) >= 3:
            suggestions.append("连续失败过多，建议更换工具组合")
        return {"evolved": len(suggestions) > 0, "skill_name": skill_name,
                "total_experiences": len(skill_exps), "failure_rate": failure_rate,
                "suggestions": suggestions}

    def get_evolution_stats(self) -> Dict[str, Any]:
        return {"experiences_recorded": len(self._experiences),
                "skills_with_experiences": list(self._skills_with_exps.keys())}


# ────── SleepConsolidationCoordinator ──────

class SleepConsolidationCoordinator:
    def __init__(self):
        self._merge_threshold: float = 0.7
        self._conflict_resolution_strategy: str = "latest"
        self._dream_reports: List[Dict[str, Any]] = []
        self._stats = {"merges": 0, "conflicts_detected": 0}

    def consolidate_memories(self, memories: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not memories:
            return {"consolidated_memories": [],
                    "report": {"total_processed": 0, "merged_count": 0, "consolidation_quality": 1.0}}
        consolidated = list(memories)
        merged_count = 0
        i = 0
        while i < len(consolidated):
            j = i + 1
            while j < len(consolidated):
                sim = self._calculate_similarity(consolidated[i].get("content", ""),
                                                  consolidated[j].get("content", ""))
                if sim >= self._merge_threshold:
                    consolidated[i] = self._merge_memory_pair(consolidated[i], consolidated[j])
                    consolidated.pop(j)
                    merged_count += 1
                    self._stats["merges"] += 1
                else:
                    j += 1
            i += 1
        quality = max(0.7, 1.0 - (merged_count * 0.1))
        report = {"total_processed": len(memories), "merged_count": merged_count,
                  "consolidation_quality": quality}
        self._dream_reports.append(report)
        return {"consolidated_memories": consolidated, "report": report}

    @staticmethod
    def _tokenize(text: str) -> Set[str]:
        """Tokenize text into character bigrams for CJK-aware comparison."""
        clean = text.replace(" ", "").replace("不", "").replace("没有", "")
        if len(clean) < 2:
            return set(clean)
        return {clean[i:i+2] for i in range(len(clean) - 1)}

    def detect_and_resolve_conflicts(self, new_content: str,
                                      existing_memories: List[Dict[str, Any]]) -> Dict[str, Any]:
        conflicts: List[Dict[str, Any]] = []
        resolutions: List[Dict[str, Any]] = []
        negation_patterns = ["不", "没有", "并非", "never", "not", "don't", "doesn't"]
        for mem in existing_memories:
            existing_content = mem.get("content", "")
            new_has_neg = any(p in new_content for p in negation_patterns)
            old_has_neg = any(p in existing_content for p in negation_patterns)
            new_tokens = self._tokenize(new_content)
            old_tokens = self._tokenize(existing_content)
            overlap = new_tokens & old_tokens
            if new_has_neg != old_has_neg and len(overlap) >= 1:
                self._stats["conflicts_detected"] += 1
                conflicts.append({"existing_id": mem.get("id", ""),
                                   "existing_content": existing_content,
                                   "new_content": new_content})
                strategy = self._conflict_resolution_strategy
                if strategy == "latest":
                    action = "keep_new"
                    merged_content = None
                elif strategy == "keep_both":
                    action = "keep_both"
                    merged_content = None
                elif strategy == "merge":
                    action = "merge"
                    merged_content = f"综合观点：{existing_content}；同时也有：{new_content}"
                elif strategy == "flag":
                    action = "flag"
                    merged_content = None
                else:
                    action = "keep_new"
                    merged_content = None
                resolution = {"existing_id": mem.get("id", ""), "action": action, "strategy": strategy}
                if merged_content:
                    resolution["merged_content"] = merged_content
                resolutions.append(resolution)
        return {"conflicts_found": len(conflicts), "strategy": self._conflict_resolution_strategy,
                "conflicts": conflicts, "resolutions": resolutions}

    def set_merge_threshold(self, threshold: float) -> None:
        self._merge_threshold = max(0.0, min(1.0, threshold))

    def set_conflict_resolution_strategy(self, strategy: str) -> None:
        valid = {"latest", "keep_both", "merge", "flag"}
        if strategy in valid:
            self._conflict_resolution_strategy = strategy

    def get_dream_reports(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._dream_reports[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        return {"merges": self._stats["merges"],
                "conflicts_detected": self._stats["conflicts_detected"],
                "merge_threshold": self._merge_threshold,
                "conflict_resolution_strategy": self._conflict_resolution_strategy}

    def _calculate_similarity(self, a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        sa, sb = set(a), set(b)
        inter = len(sa & sb)
        union = len(sa | sb)
        return inter / union if union > 0 else 0.0

    def _merge_memory_pair(self, ma: Dict[str, Any], mb: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(ma)
        merged["content"] = f"{ma.get('content', '')} {mb.get('content', '')}"
        merged["temperature"] = max(ma.get("temperature", 50), mb.get("temperature", 50))
        merged["merge_count"] = ma.get("merge_count", 0) + 1
        return merged


# ────── MetaCognitionEvaluator ──────

class MetaCognitionEvaluator:
    def __init__(self):
        self._evaluation_history: List[Dict[str, Any]] = []
        self._counter = 0

    def evaluate(self, ctx: FlowContext, tracer: FlowTracer) -> Dict[str, Any]:
        self._counter += 1
        eval_id = f"eval_{self._counter:06d}"
        phase_scores = self._calculate_phase_scores(tracer)
        quality = self._calculate_overall_quality(phase_scores)
        anomalies = self._detect_anomalies(tracer)
        recommendations = self._generate_recommendations(phase_scores, anomalies)
        report = {"evaluation_id": eval_id, "phase_scores": phase_scores,
                  "quality_score": quality, "anomalies": anomalies,
                  "recommendations": recommendations,
                  "timestamp": datetime.datetime.now().isoformat()}
        self._evaluation_history.append(report)
        return report

    def get_evaluation_report(self) -> Dict[str, Any]:
        if not self._evaluation_history:
            return {"evaluations": 0, "avg_quality_score": 0.0}
        qualities = [r["quality_score"] for r in self._evaluation_history]
        return {"evaluations": len(self._evaluation_history),
                "avg_quality_score": sum(qualities) / len(qualities),
                "min_quality_score": min(qualities), "max_quality_score": max(qualities)}

    def _calculate_phase_scores(self, tracer: FlowTracer) -> Dict[str, float]:
        stats = tracer.get_stats()
        scores: Dict[str, float] = {}
        for name, ps in stats.get("phases", {}).items():
            scores[name] = ps["successes"] / ps["count"] if ps["count"] > 0 else 0.0
        return scores

    def _calculate_overall_quality(self, phase_scores: Dict[str, float]) -> float:
        if not phase_scores:
            return 0.0
        return sum(phase_scores.values()) / len(phase_scores)

    def _detect_anomalies(self, tracer: FlowTracer) -> List[Dict[str, Any]]:
        anomalies: List[Dict[str, Any]] = []
        stats = tracer.get_stats()
        for name, ps in stats.get("phases", {}).items():
            if ps["count"] > 0 and (ps["failures"] / ps["count"]) > 0.4:
                anomalies.append({"type": "low_success_rate", "phase": name,
                                   "failure_rate": ps["failures"] / ps["count"]})
        return anomalies

    def _generate_recommendations(self, phase_scores: Dict[str, float],
                                   anomalies: List[Dict[str, Any]]) -> List[str]:
        recs: List[str] = []
        for a in anomalies:
            if a["type"] == "low_success_rate":
                recs.append(f"阶段 {a['phase']} 成功率过低，建议检查相关组件")
        return recs


# ────── FlowOrchestrator ──────

class FlowOrchestrator:
    """完整流程编排器"""

    def __init__(self):
        self.message_flow = MessageFlowManager()
        self.context_bridge = ContextMemoryBridge()
        self.memory_coordinator = MemoryCoordinator()
        self.tool_feedback = ToolFeedbackLoop()
        self.experience_evolution = ExperienceEvolutionEngine()
        self.sleep_consolidation = SleepConsolidationCoordinator()
        self.metacognition = MetaCognitionEvaluator()
        self.tracer = FlowTracer()
        self._cycle_count = 0

    def process_conversation(self, user_input: str = "", session_id: str = "",
                              agent_id: str = "", user_id: str = "",
                              system_prompt: str = "", token_budget: int = 4000) -> FlowContext:
        self._cycle_count += 1
        ctx = FlowContext(session_id=session_id or f"sess_{self._cycle_count:06d}",
                          agent_id=agent_id, user_id=user_id, user_input=user_input,
                          system_prompt=system_prompt, token_budget=token_budget,
                          _cycle_count=self._cycle_count)
        ctx.metadata["cycle_count"] = self._cycle_count

        phases = [FlowPhase.CONVERSATION, FlowPhase.CONTEXT_BUILD, FlowPhase.MEMORY_CACHE,
                  FlowPhase.MEMORY_RETRIEVAL, FlowPhase.MEMORY_WRITE, FlowPhase.TOOL_INVOCATION,
                  FlowPhase.RESULT_FEEDBACK, FlowPhase.EXPERIENCE_ACCUMULATE, FlowPhase.EVOLUTION,
                  FlowPhase.SLEEP_CONSOLIDATION, FlowPhase.CONFLICT_RESOLUTION, FlowPhase.METACOGNITION]
        for phase in phases:
            ctx = self._run_phase(phase, ctx)
        ctx.metadata["completed_at"] = datetime.datetime.now().isoformat()
        return ctx

    def _run_phase(self, phase: FlowPhase, ctx: FlowContext) -> FlowContext:
        evt_id = self.tracer.start_phase(phase)
        ctx.current_phase = phase
        try:
            handler = {
                FlowPhase.CONVERSATION: self._phase_conversation,
                FlowPhase.CONTEXT_BUILD: self._phase_context_build,
                FlowPhase.MEMORY_CACHE: self._phase_memory_cache,
                FlowPhase.MEMORY_RETRIEVAL: self._phase_memory_retrieval,
                FlowPhase.MEMORY_WRITE: self._phase_memory_write,
                FlowPhase.TOOL_INVOCATION: self._phase_tool_invocation,
                FlowPhase.RESULT_FEEDBACK: self._phase_result_feedback,
                FlowPhase.EXPERIENCE_ACCUMULATE: self._phase_experience,
                FlowPhase.EVOLUTION: self._phase_evolution,
                FlowPhase.SLEEP_CONSOLIDATION: self._phase_sleep_consolidation,
                FlowPhase.CONFLICT_RESOLUTION: self._phase_conflict_resolution,
                FlowPhase.METACOGNITION: self._phase_metacognition,
            }[phase]
            ctx = handler(ctx)
            self.tracer.end_phase(evt_id, phase, True)
        except Exception as e:
            logger.warning(f"Phase {phase.value} failed: {e}")
            self.tracer.end_phase(evt_id, phase, False, error=str(e))
        return ctx

    def _phase_conversation(self, ctx: FlowContext) -> FlowContext:
        """记录用户输入到消息流"""
        if ctx.user_input:
            msg = self.message_flow.receive_message(ctx.session_id, "user", ctx.user_input,
                                                     metadata={"agent_id": ctx.agent_id})
            ctx.conversation_history.append(msg)
        return ctx

    def _phase_context_build(self, ctx: FlowContext) -> FlowContext:
        """构建上下文"""
        ctx = self.context_bridge.build_context(ctx, system_prompt=ctx.system_prompt)
        return ctx

    def _phase_memory_cache(self, ctx: FlowContext) -> FlowContext:
        """检查记忆缓存"""
        # 从 MemoryCoordinator 检索缓存记忆
        results = self.memory_coordinator.retrieve(ctx.user_input, limit=5)
        ctx.cached_memories = results
        return ctx

    def _phase_memory_retrieval(self, ctx: FlowContext) -> FlowContext:
        """检索相关记忆"""
        results = self.memory_coordinator.retrieve(ctx.user_input, limit=10)
        ctx.retrieved_memories = results
        return ctx

    def _phase_memory_write(self, ctx: FlowContext) -> FlowContext:
        """写入新记忆"""
        if ctx.user_input:
            self.memory_coordinator.write(ctx.user_input, category="conversation",
                                           temperature=80.0)
        return ctx

    def _phase_tool_invocation(self, ctx: FlowContext) -> FlowContext:
        """工具调用阶段（占位）"""
        return ctx

    def _phase_result_feedback(self, ctx: FlowContext) -> FlowContext:
        """结果反馈阶段（占位）"""
        return ctx

    def _phase_experience(self, ctx: FlowContext) -> FlowContext:
        """经验积累"""
        if ctx.user_input:
            exp_id = self.experience_evolution.accumulate_experience(
                context={"user_input": ctx.user_input},
                result={"output": "processed"},
                success=True,
                skill_name="conversation",
            )
            ctx.experiences.append({"id": exp_id})
        return ctx

    def _phase_evolution(self, ctx: FlowContext) -> FlowContext:
        """进化阶段"""
        result = self.experience_evolution.evolve("conversation", {})
        ctx.evolution_changes.append(result)
        return ctx

    def _phase_sleep_consolidation(self, ctx: FlowContext) -> FlowContext:
        """睡眠记忆合并"""
        memories = [{"id": m["id"], "content": m.get("content", ""), "temperature": m.get("temperature", 50)}
                    for m in self.memory_coordinator._memories]
        if memories:
            result = self.sleep_consolidation.consolidate_memories(memories)
            ctx.sleep_results = result
        return ctx

    def _phase_conflict_resolution(self, ctx: FlowContext) -> FlowContext:
        """冲突检测与解决"""
        if ctx.user_input:
            existing = [{"id": m["id"], "content": m.get("content", ""), "temperature": m.get("temperature", 50)}
                        for m in self.memory_coordinator._memories]
            result = self.sleep_consolidation.detect_and_resolve_conflicts(ctx.user_input, existing)
            ctx.conflicts = result.get("conflicts", [])
        return ctx

    def _phase_metacognition(self, ctx: FlowContext) -> FlowContext:
        """元认知评估"""
        report = self.metacognition.evaluate(ctx, self.tracer)
        ctx.metacognition_report = report
        return ctx

    def get_comprehensive_report(self) -> Dict[str, Any]:
        """获取综合报告"""
        return {
            "cycle_count": self._cycle_count,
            "tracer": self.tracer.get_stats(),
            "memory": self.memory_coordinator.get_stats(),
            "cache": self.context_bridge.get_cache_stats(),
            "tool_feedback": self.tool_feedback.get_feedback_stats(),
            "experience_evolution": self.experience_evolution.get_evolution_stats(),
            "sleep_consolidation": self.sleep_consolidation.get_stats(),
            "metacognition": self.metacognition.get_evaluation_report(),
        }

    def flush_all(self) -> None:
        """刷新所有缓冲"""
        self.memory_coordinator.flush_all()


# ────── Module-level singletons ──────

_global_flow_orchestrator: Optional[FlowOrchestrator] = None


def get_flow_orchestrator() -> FlowOrchestrator:
    """获取全局 FlowOrchestrator 单例"""
    global _global_flow_orchestrator
    if _global_flow_orchestrator is None:
        _global_flow_orchestrator = FlowOrchestrator()
    return _global_flow_orchestrator


def process_conversation_flow(user_input: str = "", session_id: str = "",
                               agent_id: str = "", user_id: str = "",
                               system_prompt: str = "", token_budget: int = 4000) -> FlowContext:
    """便捷函数：使用全局编排器处理一次对话"""
    orchestrator = get_flow_orchestrator()
    return orchestrator.process_conversation(user_input=user_input, session_id=session_id,
                                              agent_id=agent_id, user_id=user_id,
                                              system_prompt=system_prompt, token_budget=token_budget)
