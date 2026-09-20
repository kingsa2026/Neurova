"""
Neurova Multi-Agent Coordination Benchmarks
Multi-agent 协作性能基准测试

"""

import asyncio
import time
import statistics
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json

from neurova.core.logger import get_logger
from neurova.agents.seen_boundary import get_seen_boundary
from neurova.collaboration.glance_yield_rules import get_glance_yield_checker
from neurova.llm.triage import get_small_brain_triage_gate
from neurova.agents.wake_debounce import get_wake_debounce_manager, WakeEvent

logger = get_logger(__name__)

@dataclass
class BenchmarkResult:
    """Single benchmark result"""
    name: str
    timestamp: datetime
    metrics: Dict[str, float]
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "timestamp": self.timestamp.isoformat(),
            "metrics": self.metrics,
            "details": self.details,
        }

class MultiAgentBenchmarkSuite:
    """
    Multi-agent coordination benchmark suite

    Test scenarios:
    1. Chain task - Sequential agent dependencies
    2. Counting game - Collaborative counting with collision avoidance
    3. Werewolf - Complex multi-agent roleplay
    4. Kanban - Task board collaboration

    Metrics tracked:
    - Turn completion time
    - Collision rate
    - Yield rate
    - Message coalescing efficiency
    - Cost per task
    """

    def __init__(self):
        self._results: List[BenchmarkResult] = []

        logger.info("MultiAgentBenchmarkSuite initialized")

    async def run_chain_task_benchmark(
        self,
        num_agents: int = 5,
        tasks_per_agent: int = 10,
    ) -> BenchmarkResult:
        """
        Chain task benchmark

        Simulates sequential agent dependencies where each agent
        must wait for previous agent's completion before proceeding.

        Expected behavior:
        - Agent 1 → Agent 2 → Agent 3 → ... (sequential)
        - No collisions expected
        - Low yield rate expected
        """
        logger.info(f"Starting chain task benchmark: {num_agents} agents")

        start_time = time.time()

        # Initialize components
        seen_boundary = await get_seen_boundary()
        yield_checker = await get_glance_yield_checker()
        debounce_manager = get_wake_debounce_manager()

        # Track metrics
        metrics = {
            "total_turns": 0,
            "successful_turns": 0,
            "failed_turns": 0,
            "collisions": 0,
            "yields": 0,
            "total_duration_seconds": 0,
            "avg_turn_latency_ms": 0,
            "turn_latencies": [],
        }

        turn_latencies = []

        # Simulate chain execution
        for agent_num in range(num_agents):
            agent_id = f"chain_agent_{agent_num}"

            for task_num in range(tasks_per_agent):
                task_start = time.time()

                try:
                    # Register agent
                    yield_checker.register_agent(agent_id, "gpt-4o-mini")

                    # Check freshness
                    held = await seen_boundary.check_freshness(
                        agent_id=agent_id,
                        conversation_id=f"chain_conv_{agent_num}",
                        last_seen_seq=task_num,
                    )

                    if held:
                        metrics["collisions"] += 1
                        continue

                    # Check yield rules
                    decision = yield_checker.check_yield_rules(
                        agent_id=agent_id,
                        model_name="gpt-4o-mini",
                        proposed_operations=[f"task_{task_num}"],
                        conversation_id=f"chain_conv_{agent_num}",
                    )

                    if decision.should_yield:
                        metrics["yields"] += 1
                        await asyncio.sleep(decision.wait_time_seconds)

                    # Execute turn
                    await asyncio.sleep(0.01)  # Simulate turn execution

                    metrics["successful_turns"] += 1

                except Exception as e:
                    metrics["failed_turns"] += 1
                    logger.error(f"Turn failed: {e}")

                finally:
                    metrics["total_turns"] += 1
                    latency_ms = (time.time() - task_start) * 1000
                    turn_latencies.append(latency_ms)

        # Calculate final metrics
        metrics["total_duration_seconds"] = time.time() - start_time
        metrics["avg_turn_latency_ms"] = round(
            statistics.mean(turn_latencies), 2
        ) if turn_latencies else 0
        metrics["turn_latencies"] = None  # Too large to store

        result = BenchmarkResult(
            name="chain_task",
            timestamp=datetime.utcnow(),
            metrics=metrics,
            details={
                "num_agents": num_agents,
                "tasks_per_agent": tasks_per_agent,
            },
        )

        self._results.append(result)
        logger.info(f"Chain task benchmark complete: {result.to_dict()}")

        return result

    async def run_counting_game_benchmark(
        self,
        num_agents: int = 10,
        target_number: int = 100,
    ) -> BenchmarkResult:
        """
        Collaborative counting game benchmark

        Multiple agents take turns counting sequentially.
        Tests collision avoidance and spawn spacing.

        Expected behavior:
        - Agents count 1, 2, 3, ... in turn
        - High collision detection rate
        - Spawn spacing enforced
        """
        logger.info(f"Starting counting game benchmark: {num_agents} agents")

        start_time = time.time()

        seen_boundary = await get_seen_boundary()
        yield_checker = await get_glance_yield_checker()

        metrics = {
            "total_attempts": 0,
            "successful_counts": 0,
            "collisions_detected": 0,
            "spacing_violations": 0,
            "total_duration_seconds": 0,
            "efficiency_rate": 0.0,
        }

        current_number = 0

        while current_number < target_number:
            # Each agent tries to claim next number
            for agent_num in range(num_agents):
                agent_id = f"count_agent_{agent_num}"

                metrics["total_attempts"] += 1

                try:
                    yield_checker.register_agent(agent_id, "gpt-4o-mini")

                    # Check yield rules
                    decision = yield_checker.check_yield_rules(
                        agent_id=agent_id,
                        model_name="gpt-4o-mini",
                        proposed_operations=[f"count_{current_number + 1}"],
                    )

                    if decision.should_yield:
                        if decision.reason.value == "deterministic_spacing":
                            metrics["spacing_violations"] += 1
                        elif decision.reason.value == "collision_detected":
                            metrics["collisions_detected"] += 1

                        await asyncio.sleep(decision.wait_time_seconds)
                        continue

                    # Claim number
                    current_number += 1
                    metrics["successful_counts"] += 1

                    logger.debug(f"Agent {agent_id} counted: {current_number}")

                    if current_number >= target_number:
                        break

                except Exception as e:
                    logger.error(f"Counting error: {e}")

        metrics["total_duration_seconds"] = time.time() - start_time
        metrics["efficiency_rate"] = round(
            metrics["successful_counts"] / max(metrics["total_attempts"], 1) * 100, 2
        )

        result = BenchmarkResult(
            name="counting_game",
            timestamp=datetime.utcnow(),
            metrics=metrics,
            details={
                "num_agents": num_agents,
                "target_number": target_number,
            },
        )

        self._results.append(result)
        logger.info(f"Counting game benchmark complete: {result.to_dict()}")

        return result

    async def run_werewolf_benchmark(
        self,
        num_agents: int = 7,
        rounds: int = 3,
    ) -> BenchmarkResult:
        """
        Werewolf roleplay benchmark

        Complex multi-agent scenario with different roles:
        - Villagers: Discuss and vote
        - Werewolves: Coordinate attacks
        - Seer: Investigate players

        Tests complex coordination patterns.
        """
        logger.info(f"Starting werewolf benchmark: {num_agents} agents, {rounds} rounds")

        start_time = time.time()

        seen_boundary = await get_seen_boundary()
        yield_checker = await get_glance_yield_checker()
        triage_gate = get_small_brain_triage_gate()
        debounce_manager = get_wake_debounce_manager()

        metrics = {
            "total_rounds": 0,
            "completed_rounds": 0,
            "triage_skips": 0,
            "debounce_coalesced": 0,
            "avg_round_duration_seconds": 0,
            "coordination_efficiency": 0.0,
        }

        for round_num in range(rounds):
            round_start = time.time()

            # Assign roles
            roles = ["villager"] * (num_agents - 2) + ["werewolf"] * 2 + ["seer"]

            for agent_num, role in enumerate(roles):
                agent_id = f"werewolf_agent_{agent_num}_{role}"

                # Wake event simulation
                wake_event = WakeEvent(
                    agent_id=agent_id,
                    conversation_id=f"werewolf_round_{round_num}",
                    message_id=f"msg_{round_num}_{agent_num}",
                )

                debounce_manager.on_wake_event(wake_event)

                # Triage check
                triage_result = await triage_gate.triage_message(
                    conversation_id=f"werewolf_round_{round_num}"
                )

                if not triage_result.actionable:
                    metrics["triage_skips"] += 1
                    continue

                # Yield check
                decision = yield_checker.check_yield_rules(
                    agent_id=agent_id,
                    model_name="gpt-4o-mini",
                    proposed_operations=[f"round_{round_num}_action"],
                    conversation_id=f"werewolf_round_{round_num}",
                )

                if not decision.should_yield:
                    await asyncio.sleep(0.01)  # Simulate action

            metrics["total_rounds"] += 1
            metrics["completed_rounds"] += 1

            # Wait for debounce window
            await asyncio.sleep(debounce_manager.debounce_seconds / 1000)

            # Check for coalesced turns
            for agent_num in range(num_agents):
                agent_id = f"werewolf_agent_{agent_num}"
                turn = debounce_manager.get_coalesced_turn(
                    agent_id,
                    f"werewolf_round_{round_num}",
                )
                if turn:
                    metrics["debounce_coalesced"] += 1

            round_duration = time.time() - round_start
            logger.debug(f"Werewolf round {round_num} completed in {round_duration:.2f}s")

        metrics["total_duration_seconds"] = time.time() - start_time
        metrics["avg_round_duration_seconds"] = round(
            metrics["total_duration_seconds"] / max(metrics["total_rounds"], 1), 2
        )
        metrics["coordination_efficiency"] = round(
            metrics["completed_rounds"] / max(metrics["total_rounds"], 1) * 100, 2
        )

        result = BenchmarkResult(
            name="werewolf",
            timestamp=datetime.utcnow(),
            metrics=metrics,
            details={
                "num_agents": num_agents,
                "rounds": rounds,
            },
        )

        self._results.append(result)
        logger.info(f"Werewolf benchmark complete: {result.to_dict()}")

        return result

    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive benchmark report"""
        if not self._results:
            return {"error": "No results available"}

        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "total_benchmarks": len(self._results),
            "benchmarks": [r.to_dict() for r in self._results],
            "summary": {
                "fastest_scenario": min(
                    self._results,
                    key=lambda r: r.metrics.get("total_duration_seconds", float('inf'))
                ).name if self._results else None,
                "highest_collision_rate": max(
                    self._results,
                    key=lambda r: r.metrics.get("collisions", 0) / max(r.metrics.get("total_turns", 1), 1)
                ).name if self._results else None,
                "best_efficiency": max(
                    self._results,
                    key=lambda r: r.metrics.get("efficiency_rate", 0)
                ).name if self._results else None,
            },
        }

        return report

    def save_report(self, filepath: str) -> None:
        """Save benchmark report to file"""
        report = self.generate_report()

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Benchmark report saved to {filepath}")

# Global instance management
_benchmark_suite_instance: Optional[MultiAgentBenchmarkSuite] = None
_benchmark_suite_lock = asyncio.Lock()

async def get_benchmark_suite() -> MultiAgentBenchmarkSuite:
    """Get global benchmark suite instance"""
    global _benchmark_suite_instance

    if _benchmark_suite_instance is None:
        async with _benchmark_suite_lock:
            if _benchmark_suite_instance is None:
                _benchmark_suite_instance = MultiAgentBenchmarkSuite()

    return _benchmark_suite_instance

async def reset_benchmark_suite() -> None:
    """Reset benchmark suite instance (for testing)"""
    global _benchmark_suite_instance
    _benchmark_suite_instance = None
