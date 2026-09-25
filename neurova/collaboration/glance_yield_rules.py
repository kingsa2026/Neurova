"""
Neurova GLANCE_YIELD_RULES - Multi-Agent Coordination Protocol
七层防御体系核心协议，定义 agent 协作的基本原则

"""

import asyncio
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
import time

from neurova.core.logger import get_logger

logger = get_logger(__name__)

class YieldReason(str, Enum):
    """Yield decision reasons"""
    CONCURRENT_AGENT = "concurrent_agent"
    DETERMINISTIC_SPACING = "deterministic_spacing"
    ADAPTIVE_PACER = "adaptive_pacer"
    COLLISION_DETECTED = "collision_detected"
    VERBATIM_DUP = "verbatim-dup"
    TRIAGE_GATE = "triage_gate"
    COST_THRESHOLD = "cost_threshold"
    MODEL_PIN_VIOLATION = "model_pin_violation"

@dataclass
class YieldDecision:
    """Yield decision result"""
    should_yield: bool
    reason: Optional[YieldReason] = None
    wait_time_seconds: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_yield": self.should_yield,
            "reason": self.reason.value if self.reason else None,
            "wait_time_seconds": self.wait_time_seconds,
            "details": self.details,
        }

@dataclass
class AgentModelPin:
    """Agent model pin configuration"""
    agent_id: str
    model_name: str
    pinned_at: datetime = field(default_factory=datetime.utcnow)
    reason: Optional[str] = None

class GlanceYieldChecker:
    """
    GLANCE_YIELD_RULES implementation

    Seven-layer defense system for multi-agent coordination:

    Layer 1: Per-agent model pin (固定模型版本)
    Layer 2: Big-brain concurrency cap (限制并发大模型调用)
    Layer 3: Deterministic spawn spacing (最小间隔避免 thundering herd)
      3a: Triage concurrency cap (小模型分类器并发限制)
      3b: AdaptivePacer (速率限制自适应调整)
      3c: Wake debounce & coalesce (去抖窗口)
    Layer 4: Rate-limit cooldown (单次限流冷却)
    Layer 5: Freshness preflight (提交前检查新消息)
      5b: Atomic verbatim-dup detection (重复内容检测)
      5c: Stall pipeline (静默 conversation 唤醒)
    Layer 6: Small-brain triage gate (小模型过滤无意义对话)
    Layer 7: Standing prompt + yield rules (协作原则)

    Key Principles:
    - Simple over complex
    - Observable over opaque
    - Conservative defaults
    - Easy opt-out when needed
    """

    # Configuration defaults
    DEFAULT_MAX_CONCURRENT_AGENTS = 6
    DEFAULT_MIN_SPAWN_INTERVAL_MS = 500  # 0.5 seconds
    DEFAULT_TRIAGE_CONCURRENT_LIMIT = 8
    DEFAULT_WAKE_DEBOUNCE_MS = 2500  # 2.5 seconds
    DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60

    def __init__(self):
        # Layer 1: Model pins
        self._agent_pins: Dict[str, AgentModelPin] = {}

        # Layer 2: Concurrency tracking
        self._active_agents: Dict[str, int] = {}  # model_name -> count

        # Layer 3: Spacing and pacing
        self._last_spawn_time: Dict[str, float] = {}  # agent_id -> timestamp
        self._pacing_stats: Dict[str, Dict[str, Any]] = {}  # model -> stats

        # Layer 4: Rate limit state
        self._rate_limited_agents: Dict[str, float] = {}  # agent_id -> cooldown_end

        # Layer 5: Seen cursors (integrated with SeenBoundary)
        self._seen_sequences: Dict[str, int] = {}  # (agent, convo) -> seq

        # Layer 6: Triage cache
        self._triage_cache: Dict[str, bool] = {}  # conversation_hash -> actionable

        # Statistics
        self._stats = {
            'total_checks': 0,
            'yields': 0,
            'proceeds': 0,
        }

        logger.info("GlanceYieldChecker initialized")

    def register_agent(
        self,
        agent_id: str,
        model_name: str,
        reason: Optional[str] = None,
    ) -> None:
        """
        Layer 1: Register agent with model pin

        Ensures consistent model behavior per agent
        """
        pin = AgentModelPin(
            agent_id=agent_id,
            model_name=model_name,
            reason=reason,
        )

        self._agent_pins[agent_id] = pin

        logger.info(f"Registered agent {agent_id} with model {model_name}")

    def unregister_agent(self, agent_id: str) -> None:
        """Unregister agent"""
        if agent_id in self._agent_pins:
            model_name = self._agent_pins[agent_id].model_name

            if model_name in self._active_agents:
                self._active_agents[model_name] = max(0, self._active_agents[model_name] - 1)

            del self._agent_pins[agent_id]

    def check_yield_rules(
        self,
        agent_id: str,
        model_name: str,
        proposed_operations: List[str],
        conversation_id: Optional[str] = None,
    ) -> YieldDecision:
        """
        Main entry point: Check all yield rules

        Returns decision on whether agent should proceed or yield
        """
        # Update stats
        self._stats['total_checks'] += 1
        # Layer 1: Model pin validation
        decision = self._check_model_pin(agent_id, model_name)
        if decision.should_yield:
            return decision

        # Layer 2: Concurrency check
        decision = self._check_concurrency_limit(agent_id, model_name)
        if decision.should_yield:
            return decision

        # Layer 3: Spawn spacing
        decision = self._check_spawn_spacing(agent_id)
        if decision.should_yield:
            return decision

        # Layer 3b: Adaptive pacing
        decision = self._check_adaptive_pacer(agent_id, model_name)
        if decision.should_yield:
            return decision

        # Layer 4: Rate limit
        decision = self._check_rate_limit(agent_id)
        if decision.should_yield:
            return decision

        # Layer 5: Freshness preflight
        if conversation_id:
            decision = self._check_freshness_preflight(agent_id, conversation_id)
            if decision.should_yield:
                return decision

        # Layer 6: Triage gate
        if conversation_id:
            decision = self._check_triage_gate(conversation_id)
            if decision.should_yield:
                return decision

        # All checks passed - proceed
        self._stats['proceeds'] += 1
        return YieldDecision(should_yield=False)

    def _check_model_pin(self, agent_id: str, model_name: str) -> YieldDecision:
        """Layer 1: Validate model pin"""
        if agent_id not in self._agent_pins:
            # First time - set pin
            self.register_agent(agent_id, model_name)
            return YieldDecision(should_yield=False)

        pinned_model = self._agent_pins[agent_id].model_name
        if model_name != pinned_model:
            logger.warning(
                f"Model pin violation: agent={agent_id}, "
                f"pinned={pinned_model}, requested={model_name}"
            )

            return YieldDecision(
                should_yield=True,
                reason=YieldReason.MODEL_PIN_VIOLATION,
                details={
                    "pinned_model": pinned_model,
                    "requested_model": model_name,
                },
            )

        return YieldDecision(should_yield=False)

    def _check_concurrency_limit(
        self,
        agent_id: str,
        model_name: str,
    ) -> YieldDecision:
        """Layer 2: Check big-brain concurrency cap"""
        # Get current count for this model
        current_count = self._active_agents.get(model_name, 0)

        # If under limit, temporarily increment to simulate this agent becoming active
        if current_count < self.DEFAULT_MAX_CONCURRENT_AGENTS:
            # First agent proceeds (no yield)
            self._active_agents[model_name] = current_count + 1
            return YieldDecision(should_yield=False)

        # Limit exceeded - second and subsequent agents must yield
        logger.warning(
            f"Concurrency limit exceeded: "
            f"model={model_name}, current={current_count}, max={self.DEFAULT_MAX_CONCURRENT_AGENTS}"
        )

        return YieldDecision(
            should_yield=True,
            reason=YieldReason.CONCURRENT_AGENT,
            wait_time_seconds=1.0,
            details={
                "model": model_name,
                "current_count": current_count,
                "max_allowed": self.DEFAULT_MAX_CONCURRENT_AGENTS,
            },
        )

    def _check_spawn_spacing(self, agent_id: str) -> YieldDecision:
        """Layer 3: Check deterministic spawn spacing"""
        last_time = self._last_spawn_time.get(agent_id, 0)
        elapsed_ms = (time.time() - last_time) * 1000

        if elapsed_ms < self.DEFAULT_MIN_SPAWN_INTERVAL_MS:
            wait_ms = self.DEFAULT_MIN_SPAWN_INTERVAL_MS - elapsed_ms
            wait_seconds = wait_ms / 1000

            logger.debug(
                f"Spawn spacing violated: "
                f"agent={agent_id}, elapsed={elapsed_ms:.0f}ms, "
                f"required={self.DEFAULT_MIN_SPAWN_INTERVAL_MS}ms"
            )

            return YieldDecision(
                should_yield=True,
                reason=YieldReason.DETERMINISTIC_SPACING,
                wait_time_seconds=wait_seconds,
                details={
                    "elapsed_ms": elapsed_ms,
                    "required_ms": self.DEFAULT_MIN_SPAWN_INTERVAL_MS,
                },
            )

        return YieldDecision(should_yield=False)

    def _check_adaptive_pacer(self, agent_id: str, model_name: str) -> YieldDecision:
        """Layer 3b: Adaptive pacing based on error rate"""
        stats = self._pacing_stats.get(model_name, {"success_rate": 1.0})
        success_rate = stats.get("success_rate", 1.0)

        # Exponential backoff if error rate high
        if success_rate < 0.5:
            base_wait = 2.0
            backoff_factor = (1.0 - success_rate) * 2
            wait_seconds = base_wait * backoff_factor

            logger.warning(
                f"Adaptive pacer triggered: "
                f"model={model_name}, success_rate={success_rate:.1%}"
            )

            return YieldDecision(
                should_yield=True,
                reason=YieldReason.ADAPTIVE_PACER,
                wait_time_seconds=wait_seconds,
                details={"success_rate": success_rate},
            )

        return YieldDecision(should_yield=False)

    def _check_rate_limit(self, agent_id: str) -> YieldDecision:
        """Layer 4: Check rate limit cooldown"""
        cooldown_end = self._rate_limited_agents.get(agent_id, 0)

        if time.time() < cooldown_end:
            remaining = cooldown_end - time.time()

            logger.info(
                f"Rate limit active: "
                f"agent={agent_id}, remaining={remaining:.0f}s"
            )

            return YieldDecision(
                should_yield=True,
                reason=YieldReason.COLLISION_DETECTED,
                wait_time_seconds=remaining,
            )

        # Clear cooldown
        if agent_id in self._rate_limited_agents:
            del self._rate_limited_agents[agent_id]

        return YieldDecision(should_yield=False)

    def _check_freshness_preflight(
        self,
        agent_id: str,
        conversation_id: str,
    ) -> YieldDecision:
        """Layer 5: Freshness preflight check"""
        # This integrates with SeenBoundary
        # For now, simplified version

        key = f"{agent_id}:{conversation_id}"
        current_seq = int(time.time() * 1000)
        last_seq = self._seen_sequences.get(key, 0)

        if current_seq == last_seq:
            # No new activity
            return YieldDecision(should_yield=False)

        # Update sequence
        self._seen_sequences[key] = current_seq

        return YieldDecision(should_yield=False)

    def _check_triage_gate(self, conversation_id: str) -> YieldDecision:
        """Layer 6: Small-brain triage gate"""
        # Check if conversation is actionable
        # Uses cheap model to filter noise

        cache_key = f"triage:{conversation_id}"
        if cache_key in self._triage_cache:
            is_actionable = self._triage_cache[cache_key]

            if not is_actionable:
                logger.debug(f"Triage gate blocked: conversation={conversation_id}")

                return YieldDecision(
                    should_yield=True,
                    reason=YieldReason.TRIAGE_GATE,
                    details={"conversation_id": conversation_id},
                )

        # Default: allow (conservative)
        return YieldDecision(should_yield=False)

    def record_operation_start(self, agent_id: str, operation_hash: str) -> None:
        """Record operation start time"""
        self._last_spawn_time[agent_id] = time.time()

    def record_operation_complete(
        self,
        agent_id: str,
        operation_hash: str,
        success: bool,
    ) -> None:
        """Record operation completion and update pacing stats"""
        model_name = self._agent_pins.get(agent_id, AgentModelPin(
            agent_id=agent_id,
            model_name="unknown",
        )).model_name

        stats = self._pacing_stats.setdefault(model_name, {
            "total_ops": 0,
            "successful_ops": 0,
        })

        stats["total_ops"] += 1
        if success:
            stats["successful_ops"] += 1

        # Calculate success rate
        stats["success_rate"] = (
            stats["successful_ops"] / stats["total_ops"]
            if stats["total_ops"] > 0
            else 1.0
        )

        logger.debug(
            f"Operation completed: "
            f"agent={agent_id}, model={model_name}, "
            f"success_rate={stats['success_rate']:.1%}"
        )

    def trigger_rate_limit(self, agent_id: str) -> None:
        """Trigger rate limit cooldown for agent"""
        self._rate_limited_agents[agent_id] = (
            time.time() + self.DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
        )

        logger.warning(f"Rate limit triggered for agent: {agent_id}")

    def cache_triage_result(self, conversation_id: str, actionable: bool) -> None:
        """Cache triage gate result"""
        cache_key = f"triage:{conversation_id}"
        self._triage_cache[cache_key] = actionable

        logger.debug(f"Cached triage result: {cache_key}={actionable}")

    def get_stats(self) -> Dict[str, Any]:
        """Get checker statistics"""
        return {
            "registered_agents": len(self._agent_pins),
            "active_per_model": dict(self._active_agents),
            "pacing_stats": dict(self._pacing_stats),
            "triage_cache_size": len(self._triage_cache),
            **self._stats,
        }

# Global instance management
_glance_checker_instance: Optional[GlanceYieldChecker] = None
_glance_checker_lock = asyncio.Lock()

async def get_glance_yield_checker() -> GlanceYieldChecker:
    """Get global GlanceYieldChecker instance"""
    global _glance_checker_instance

    if _glance_checker_instance is None:
        async with _glance_checker_lock:
            if _glance_checker_instance is None:
                _glance_checker_instance = GlanceYieldChecker()

    return _glance_checker_instance

async def reset_glance_yield_checker() -> None:
    """Reset GlanceYieldChecker instance (for testing)"""
    global _glance_checker_instance
    _glance_checker_instance = None
