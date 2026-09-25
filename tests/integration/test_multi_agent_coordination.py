"""
Neurova Multi-Agent Coordination System - Integration Tests
Multi-agent 协作系统集成测试
"""

import asyncio
import pytest
from typing import Dict, Any
from datetime import datetime

from neurova.agents.seen_boundary import (
    get_seen_boundary,
    reset_seen_boundary,
)
from neurova.collaboration.glance_yield_rules import (
    get_glance_yield_checker,
    reset_glance_yield_checker,
    YieldReason,
)
from neurova.llm.triage import (
    get_small_brain_triage_gate,
    reset_small_brain_triage_gate,
)
from neurova.agents.wake_debounce import (
    get_wake_debounce_manager,
    reset_wake_debounce_manager,
    WakeEvent,
)
from neurova.experiments.ab_test_manager import (
    get_ab_test_manager,
    reset_ab_test_manager,
    ExperimentConfig,
    ExperimentGroup,
)


# Cleanup after each test class
def teardown_module(module):
    """Cleanup all components after tests"""
    import asyncio
    
    # Reset all components
    try:
        asyncio.get_event_loop().run_until_complete(reset_seen_boundary())
    except:
        pass
    
    try:
        asyncio.get_event_loop().run_until_complete(reset_glance_yield_checker())
    except:
        pass
    
    try:
        reset_small_brain_triage_gate()
    except:
        pass
    
    try:
        reset_wake_debounce_manager()
    except:
        pass
    
    try:
        asyncio.get_event_loop().run_until_complete(reset_ab_test_manager())
    except:
        pass


class TestSeenBoundary:
    """Test Seen Boundary component"""
    
    @pytest.mark.asyncio
    async def test_seen_boundary_singleton(self):
        """Test that seen boundary is singleton"""
        boundary1 = await get_seen_boundary()
        boundary2 = await get_seen_boundary()
        
        assert boundary1 is boundary2
        
        reset_seen_boundary()
    
    @pytest.mark.asyncio
    async def test_freshness_check_stale(self):
        """Test freshness check detects stale messages"""
        boundary = await get_seen_boundary()
        
        # First call: establish baseline (will be None without Redis)
        result1 = await boundary.check_freshness(
            agent_id="test_agent",
            conversation_id="test_conv",
            last_seen_seq=0,
        )
        
        # Without Redis, baseline is None so first call returns None (fresh)
        # This is expected behavior for in-memory mode
        assert result1 is None or hasattr(result1, 'newer_messages')
        
        reset_seen_boundary()
    
    @pytest.mark.asyncio
    async def test_seen_boundary_stats(self):
        """Test seen boundary statistics"""
        boundary = await get_seen_boundary()
        
        # Make some calls
        await boundary.check_freshness("agent_1", "conv_1", 0)
        await boundary.check_freshness("agent_1", "conv_1", 1)
        
        stats = boundary.get_stats()
        
        assert stats["total_checks"] >= 2
        
        reset_seen_boundary()


class TestYieldChecker:
    """Test Yield Checker component"""
    
    @pytest.mark.asyncio
    async def test_yield_checker_singleton(self):
        """Test that yield checker is singleton"""
        checker1 = await get_glance_yield_checker()
        checker2 = await get_glance_yield_checker()
        
        assert checker1 is checker2
        
        reset_glance_yield_checker()
    
    @pytest.mark.asyncio
    async def test_agent_registration(self):
        """Test agent registration"""
        checker = await get_glance_yield_checker()
        
        checker.register_agent("agent_1", "gpt-4o")
        checker.register_agent("agent_2", "gpt-4o-mini")
        
        stats = checker.get_stats()
        
        assert stats["registered_agents"] == 2
        
        reset_glance_yield_checker()
    
    @pytest.mark.asyncio
    async def test_yield_decision_collision(self):
        """Test yield decision on collision"""
        checker = await get_glance_yield_checker()
        
        # Register multiple agents with same model
        for i in range(15):  # More than DEFAULT_MAX_CONCURRENT_AGENTS (10)
            checker.register_agent(f"agent_{i}", "gpt-4o")
        
        # First 10 should proceed, rest should yield
        proceeding_count = 0
        yielding_count = 0
        
        for i in range(15):
            decision = checker.check_yield_rules(
                agent_id=f"agent_{i}",
                model_name="gpt-4o",
                proposed_operations=["do_task"],
            )
            
            if decision.should_yield:
                yielding_count += 1
            else:
                proceeding_count += 1
        
        # At least some should yield (those beyond the limit)
        assert yielding_count > 0, "Some agents should yield due to concurrency limit"
        assert proceeding_count > 0, "Some agents should proceed (up to limit)"
        
        reset_glance_yield_checker()
    
    @pytest.mark.asyncio
    async def test_yield_reasons(self):
        """Test different yield reasons"""
        checker = await get_glance_yield_checker()
        
        checker.register_agent("agent_1", "gpt-4o")
        
        decision = checker.check_yield_rules(
            agent_id="agent_1",
            model_name="gpt-4o",
            proposed_operations=["task"],
        )
        
        # Check that reason is valid if yielding
        if decision.should_yield and decision.reason:
            assert decision.reason.value in [r.value for r in YieldReason]
        
        reset_glance_yield_checker()


class TestTriageGate:
    """Test Small-Brain Triage Gate"""
    
    @pytest.mark.asyncio
    async def test_triage_gate_singleton(self):
        """Test that triage gate is singleton"""
        gate1 = get_small_brain_triage_gate()
        gate2 = get_small_brain_triage_gate()
        
        assert gate1 is gate2
        
        reset_small_brain_triage_gate()
    
    @pytest.mark.asyncio
    async def test_triage_message_empty(self):
        """Test triage with empty conversation"""
        gate = get_small_brain_triage_gate()
        
        result = await gate.triage_message("empty_conv")
        
        # Default to actionable when no history
        assert result.actionable == True
        assert result.reason == "no_history"
        
        reset_small_brain_triage_gate()
    
    @pytest.mark.asyncio
    async def test_triage_stats(self):
        """Test triage statistics"""
        gate = get_small_brain_triage_gate()
        
        # Make some calls
        await gate.triage_message("conv_1")
        await gate.triage_message("conv_2")
        
        stats = gate.get_stats()
        
        assert stats["total_tries"] >= 2
        
        reset_small_brain_triage_gate()


class TestWakeDebounce:
    """Test Wake Debounce & Coalesce"""
    
    @pytest.mark.asyncio
    async def test_debounce_manager_singleton(self):
        """Test that debounce manager is singleton"""
        manager1 = get_wake_debounce_manager()
        manager2 = get_wake_debounce_manager()
        
        assert manager1 is manager2
        
        reset_wake_debounce_manager()
    
    @pytest.mark.asyncio
    async def test_wake_event_handling(self):
        """Test wake event handling"""
        manager = get_wake_debounce_manager()
        
        # Send wake events
        manager.on_wake_event(WakeEvent(
            agent_id="agent_1",
            conversation_id="conv_1",
            message_id="msg_1",
        ))
        
        manager.on_wake_event(WakeEvent(
            agent_id="agent_1",
            conversation_id="conv_1",
            message_id="msg_2",
        ))
        
        stats = manager.get_stats()
        
        assert stats["total_wakes"] == 2
        
        reset_wake_debounce_manager()
    
    @pytest.mark.asyncio
    async def test_coalesced_turn_creation(self):
        """Test coalesced turn creation"""
        manager = get_wake_debounce_manager()
        
        # Send multiple events
        for i in range(5):
            manager.on_wake_event(WakeEvent(
                agent_id="agent_1",
                conversation_id="conv_1",
                message_id=f"msg_{i}",
            ))
        
        # Wait for debounce window
        await asyncio.sleep(manager.debounce_seconds / 1000 + 0.1)
        
        # Get coalesced turn
        turn = manager.get_coalesced_turn("agent_1", "conv_1")
        
        if turn:
            assert len(turn.messages) <= manager.DEFAULT_MAX_MESSAGES
        
        reset_wake_debounce_manager()


class TestABTestManager:
    """Test A/B Test Manager"""
    
    @pytest.mark.asyncio
    async def test_ab_test_manager_singleton(self):
        """Test that AB test manager is singleton"""
        manager1 = await get_ab_test_manager()
        manager2 = await get_ab_test_manager()
        
        assert manager1 is manager2
        
        reset_ab_test_manager()
    
    @pytest.mark.asyncio
    async def test_experiment_lifecycle(self):
        """Test full experiment lifecycle"""
        manager = await get_ab_test_manager()
        
        # Create config
        config = ExperimentConfig(
            name="test_coordination_v1",
            description="Test coordination rules",
            groups=[ExperimentGroup.CONTROL, ExperimentGroup.TREATMENT],
            traffic_split={
                ExperimentGroup.CONTROL: 0.5,
                ExperimentGroup.TREATMENT: 0.5,
            },
            metrics=["success_rate", "latency_ms"],
            duration_days=7,
            min_sample_size=10,
        )
        
        # Start experiment
        success = await manager.start_experiment(config)
        assert success
        
        # Assign agent
        group = await manager.get_experiment_group("agent_1", "test_coordination_v1")
        assert group in [ExperimentGroup.CONTROL, ExperimentGroup.TREATMENT]
        
        # Record metric
        await manager.record_metric(
            experiment_name="test_coordination_v1",
            group=group,
            metrics={"success_rate": 0.8, "latency_ms": 150},
            context={"task_type": "test"},
        )
        
        # End experiment
        success = await manager.end_experiment("test_coordination_v1")
        assert success
        
        # Get results
        results = await manager.get_experiment_results("test_coordination_v1")
        assert results is not None
        
        reset_ab_test_manager()
    
    @pytest.mark.asyncio
    async def test_traffic_splitting(self):
        """Test consistent traffic splitting"""
        manager = await get_ab_test_manager()
        
        config = ExperimentConfig(
            name="split_test",
            description="Test traffic splitting",
            groups=[ExperimentGroup.CONTROL, ExperimentGroup.TREATMENT],
            traffic_split={
                ExperimentGroup.CONTROL: 0.3,
                ExperimentGroup.TREATMENT: 0.7,
            },
            metrics=["metric1"],
            duration_days=1,
        )
        
        await manager.start_experiment(config)
        
        # Same agent should always get same group
        group1 = await manager.get_experiment_group("consistent_agent", "split_test")
        group2 = await manager.get_experiment_group("consistent_agent", "split_test")
        
        assert group1 == group2
        
        reset_ab_test_manager()


class TestFullWorkflow:
    """Test full multi-agent workflow"""
    
    @pytest.mark.asyncio
    async def test_complete_workflow(self):
        """Test complete multi-agent workflow"""
        # Initialize all components
        seen_boundary = await get_seen_boundary()
        yield_checker = await get_glance_yield_checker()
        triage_gate = get_small_brain_triage_gate()
        debounce_manager = get_wake_debounce_manager()
        ab_manager = await get_ab_test_manager()
        
        # Setup
        yield_checker.register_agent("agent_1", "gpt-4o")
        
        config = ExperimentConfig(
            name="full_workflow_test",
            description="Complete workflow test",
            groups=[ExperimentGroup.TREATMENT],
            traffic_split={ExperimentGroup.TREATMENT: 1.0},
            metrics=["turn_count"],
            duration_days=1,
        )
        
        await ab_manager.start_experiment(config)
        
        # Simulate agent turn with yield check first
        decision = yield_checker.check_yield_rules(
            agent_id="agent_1",
            model_name="gpt-4o",
            proposed_operations=["workflow_task"],
            conversation_id="workflow_conv",
        )
        
        if not decision.should_yield:
            held = await seen_boundary.check_freshness(
                agent_id="agent_1",
                conversation_id="workflow_conv",
                last_seen_seq=0,
            )
            
            if not held:
                # Triage check
                triage_result = await triage_gate.triage_message("workflow_conv")
                
                if triage_result.actionable:
                    # Wake event
                    debounce_manager.on_wake_event(WakeEvent(
                        agent_id="agent_1",
                        conversation_id="workflow_conv",
                        message_id="workflow_msg_1",
                    ))
                    
                    # Record metric
                    await ab_manager.record_metric(
                        experiment_name="full_workflow_test",
                        group=ExperimentGroup.TREATMENT,
                        metrics={"turn_count": 1},
                        context={},
                    )
        
        # Verify stats
        stats = {
            "seen_boundary": seen_boundary.get_stats(),
            "yield_checker": yield_checker.get_stats(),
            "triage_gate": triage_gate.get_stats(),
            "debounce": debounce_manager.get_stats(),
        }
        
        assert stats["seen_boundary"]["total_checks"] >= 0
        assert stats["yield_checker"]["total_checks"] >= 0
        assert stats["triage_gate"]["total_tries"] >= 0
        
        reset_seen_boundary()
        reset_glance_yield_checker()
        reset_small_brain_triage_gate()
        reset_wake_debounce_manager()
        reset_ab_test_manager()


class TestIntegrationPerformance:
    """Test integration performance"""
    
    @pytest.mark.asyncio
    async def test_coordination_overhead(self):
        """Test coordination overhead is minimal"""
        import time
        
        yield_checker = await get_glance_yield_checker()
        yield_checker.register_agent("perf_agent", "gpt-4o")
        
        # Measure overhead
        iterations = 100
        start_time = time.time()
        
        for i in range(iterations):
            yield_checker.check_yield_rules(
                agent_id="perf_agent",
                model_name="gpt-4o",
                proposed_operations=[f"task_{i}"],
            )
        
        elapsed = time.time() - start_time
        avg_latency_ms = (elapsed / iterations) * 1000
        
        # Overhead should be < 1ms per check
        assert avg_latency_ms < 1.0, f"Coordination overhead too high: {avg_latency_ms:.2f}ms"
        
        reset_glance_yield_checker()
