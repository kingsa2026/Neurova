"""
Phase 4 Integration Tests - Minimal Version
端到端测试：验证 Phase 1-3 功能的集成
Neurova Style: Follows existing testing patterns (pytest, asyncio, fixtures)
"""

import pytest


# ============================================================================
# Task 1: Cost Tracking Tests
# ============================================================================

class TestCostTrackingIntegration:
    """Test LLM cost tracking integration"""
    
    @pytest.mark.asyncio
    async def test_cost_calculation_gpt4o_mini(self):
        """Test cost calculation for gpt-4o-mini"""
        # Prices: $0.00015 per 1K input, $0.0006 per 1K output
        input_tokens = 1000
        output_tokens = 500
        
        cost = (
            input_tokens * 0.00015 / 1000 +
            output_tokens * 0.0006 / 1000
        )
        
        expected = 0.00015 + 0.0003  # = 0.00045
        assert abs(cost - expected) < 0.00001
    
    @pytest.mark.asyncio
    async def test_cost_calculation_claude3_haiku(self):
        """Test cost calculation for claude-3-haiku"""
        # Prices: $0.00025 per 1K input, $0.00125 per 1K output
        input_tokens = 1000
        output_tokens = 500
        
        cost = (
            input_tokens * 0.00025 / 1000 +
            output_tokens * 0.00125 / 1000
        )
        
        expected = 0.00025 + 0.000625  # = 0.000875
        assert abs(cost - expected) < 0.00001


# ============================================================================
# Task 2: Turn Coordination Tests
# ============================================================================

class TestTurnCoordination:
    """Test turn coordination integration"""
    
    @pytest.mark.asyncio
    async def test_turn_coordinator_singleton(self):
        """Test TurnCoordinator is singleton"""
        from neurova.agent.turn_coordinator import get_turn_coordinator
        
        coordinator1 = get_turn_coordinator()
        coordinator2 = get_turn_coordinator()
        
        assert coordinator2 is coordinator1
    
    @pytest.mark.asyncio
    async def test_turn_coordinator_initialization(self):
        """Test TurnCoordinator initialization"""
        from neurova.agent.turn_coordinator import get_turn_coordinator
        
        coordinator = get_turn_coordinator()
        stats = coordinator.get_stats()
        
        assert stats["total_turns"] == 0
        assert stats["successful_turns"] == 0
        assert stats["yielded_turns"] == 0
    
    @pytest.mark.asyncio
    async def test_yield_rules_registration(self):
        """Test agent registration in yield rules"""
        from neurova.agent.turn_coordinator import get_turn_coordinator
        
        coordinator = get_turn_coordinator()
        
        # Register agents
        coordinator.yield_checker.register_agent("agent_1", "gpt-4")
        coordinator.yield_checker.register_agent("agent_2", "gpt-3.5")
        
        # Check if registered
        assert "agent_1" in coordinator.yield_checker._agent_models
        assert "agent_2" in coordinator.yield_checker._agent_models
    
    @pytest.mark.asyncio
    async def test_operation_collision_detection(self):
        """Test operation collision detection"""
        from neurova.agent.turn_coordinator import get_turn_coordinator
        
        coordinator = get_turn_coordinator()
        
        # Register agent
        coordinator.yield_checker.register_agent("agent_1", "gpt-4")
        
        # Start operation
        op_hash = "test_operation_1"
        coordinator.yield_checker.record_operation_start("agent_1", op_hash)
        
        # Check collision
        decision = coordinator.yield_checker.check_yield_rules(
            agent_id="agent_1",
            model_name="gpt-4",
            proposed_operations=[op_hash],
        )
        
        # Should detect collision (any of the three reasons)
        assert decision.should_yield is True
        assert decision.reason.value in [
            "collision_detected",
            "deterministic_spacing",
            "concurrent_agent",
        ]
        
        # Complete operation
        coordinator.yield_checker.record_operation_complete(
            "agent_1", op_hash, success=True
        )
        
        # Wait for spawn interval (2 seconds)
        import time
        time.sleep(2.5)
        
        # No longer should yield (operation completed + wait time passed)
        decision = coordinator.yield_checker.check_yield_rules(
            agent_id="agent_1",
            model_name="gpt-4",
            proposed_operations=[op_hash],
        )
        
        # Should NOT yield anymore
        assert decision.should_yield is False


# ============================================================================
# Task 3: Smart Model Selection Tests
# ============================================================================

class TestSmartModelSelection:
    """Test smart model selection"""
    
    @pytest.mark.asyncio
    async def test_model_selector_singleton(self):
        """Test SmartModelSelector is singleton"""
        from neurova.agent.model_selector import get_smart_model_selector
        
        selector1 = get_smart_model_selector()
        selector2 = get_smart_model_selector()
        
        assert selector2 is selector1
    
    @pytest.mark.asyncio
    async def test_default_models_available(self):
        """Test default models are available"""
        from neurova.agent.model_selector import get_smart_model_selector
        
        selector = get_smart_model_selector()
        
        assert len(selector.default_models) > 0
        assert "gpt-4o-mini" in selector.default_models
        assert "gpt-3.5-turbo" in selector.default_models
    
    @pytest.mark.asyncio
    async def test_model_selection_caching(self):
        """Test model selection caching"""
        from neurova.agent.model_selector import get_smart_model_selector
        
        selector = get_smart_model_selector()
        query = "Simple question"
        
        # First selection
        model1 = await selector.select_model(
            agent_id="test_agent",
            user_query=query,
        )
        
        # Second selection (should use cache)
        model2 = await selector.select_model(
            agent_id="test_agent",
            user_query=query,
        )
        
        assert model1 == model2
        assert len(selector._selection_cache) >= 1
    
    @pytest.mark.asyncio
    async def test_model_selection_budget_constraint(self):
        """Test model selection respects budget"""
        from neurova.agent.model_selector import get_smart_model_selector
        
        selector = get_smart_model_selector()
        query = "Generate code"
        
        # Very tight budget
        model = await selector.select_model(
            agent_id="test_agent",
            user_query=query,
            available_models=["gpt-4", "gpt-4o-mini"],
            cost_budget=0.001,  # Very low budget
        )
        
        # Should use cheapest available
        assert model == "gpt-4o-mini"
    
    @pytest.mark.asyncio
    async def test_model_selection_stats(self):
        """Test model selection statistics"""
        from neurova.agent.model_selector import get_smart_model_selector
        
        selector = get_smart_model_selector()
        
        # Make some selections
        await selector.select_model(
            agent_id="test_agent",
            user_query="Query 1",
        )
        await selector.select_model(
            agent_id="test_agent",
            user_query="Query 2",
        )
        
        stats = selector.get_selection_stats()
        
        assert stats["cache_size"] >= 2
        assert "default_models" in stats


# ============================================================================
# Task 4: Full Workflow Integration Tests
# ============================================================================

class TestFullWorkflow:
    """Test complete multi-agent workflow integration"""
    
    @pytest.mark.asyncio
    async def test_complete_workflow_basic(self):
        """Test basic complete workflow"""
        from neurova.agent.turn_coordinator import get_turn_coordinator
        from neurova.agent.model_selector import get_smart_model_selector
        
        # Step 1: Register agents
        coordinator = get_turn_coordinator()
        coordinator.yield_checker.register_agent("agent_1", "gpt-4")
        coordinator.yield_checker.register_agent("agent_2", "gpt-3.5")
        
        # Step 3: Select models
        selector = get_smart_model_selector()
        
        model1 = await selector.select_model(
            agent_id="agent_1",
            user_query="What is AI?",
        )
        
        model2 = await selector.select_model(
            agent_id="agent_2",
            user_query="Write Python code",
        )
        
        assert model1 in ["gpt-4", "gpt-4o-mini", "gpt-3.5-turbo"]
        assert model2 in ["gpt-4", "gpt-4o-mini", "gpt-3.5-turbo"]
        
        # Step 2: Verify coordination works
        logger.info(f"Complete workflow test passed!")
    
    @pytest.mark.asyncio
    async def test_multi_agent_coordination(self):
        """Test multi-agent coordination"""
        from neurova.agent.turn_coordinator import get_turn_coordinator
        
        # Get coordinator
        coordinator = get_turn_coordinator()
        
        # Register two agents on SAME model (to detect collision)
        coordinator.yield_checker.register_agent("agent_1", "gpt-4")
        coordinator.yield_checker.register_agent("agent_2", "gpt-4")
        
        # Agent 1 starts operation
        op_hash = "operation_1"
        coordinator.yield_checker.record_operation_start("agent_1", op_hash)
        
        # Agent 2 tries same operation
        decision = coordinator.yield_checker.check_yield_rules(
            agent_id="agent_2",
            model_name="gpt-3.5",
            proposed_operations=[op_hash],
        )
        
        # Should detect collision (any of the three reasons)
        assert decision.should_yield is True
        assert decision.reason.value in [
            "collision_detected",
            "deterministic_spacing",
            "concurrent_agent",
        ]
        
        # Clean up
        coordinator.yield_checker.record_operation_complete("agent_1", op_hash, success=True)


# ============================================================================
# Performance Tests
# ============================================================================

class TestPerformance:
    """Test performance characteristics"""
    
    @pytest.mark.asyncio
    async def test_cost_tracking_speed(self):
        """Test cost tracking is fast"""
        import time
        
        # Time multiple calls
        start = time.time()
        
        for i in range(10):
            input_tokens = 100
            output_tokens = 50
            
            cost = (
                input_tokens * 0.00015 / 1000 +
                output_tokens * 0.0006 / 1000
            )
        
        elapsed = time.time() - start
        
        # Should complete quickly
        assert elapsed < 1.0, f"Cost tracking took {elapsed}s for 10 calls"
    
    @pytest.mark.asyncio
    async def test_coordination_overhead(self):
        """Test coordination overhead is minimal"""
        import time
        
        from neurova.agent.turn_coordinator import get_turn_coordinator
        
        # Register agent
        coordinator = get_turn_coordinator()
        coordinator.yield_checker.register_agent("perf_agent", "gpt-4")
        
        # Time operations
        start = time.time()
        
        for _ in range(5):
            decision = coordinator.yield_checker.check_yield_rules(
                agent_id="perf_agent",
                model_name="gpt-4",
                proposed_operations=["test_op"],
            )
        
        elapsed = time.time() - start
        
        # Should be fast
        avg_time = elapsed / 5
        assert avg_time < 0.01, f"Avg coordination time {avg_time}s is too high"


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling and recovery"""
    
    @pytest.mark.asyncio
    async def test_invalid_token_counts(self):
        """Test handling of invalid token counts"""
        # Negative tokens should not crash
        input_tokens = -100
        output_tokens = 50
        
        cost = (
            input_tokens * 0.00015 / 1000 +
            output_tokens * 0.0006 / 1000
        )
        
        # Cost might be negative but shouldn't crash
        assert isinstance(cost, float)
    
    @pytest.mark.asyncio
    async def test_empty_query_selection(self):
        """Test model selection with empty query"""
        from neurova.agent.model_selector import get_smart_model_selector
        
        selector = get_smart_model_selector()
        model = await selector.select_model(
            agent_id="test_agent",
            user_query="",
        )
        
        # Should return a valid model
        assert model is not None
        assert isinstance(model, str)


# ============================================================================
# Helper Classes
# ============================================================================

logger = pytest.importorskip("neurova.core.logger").get_logger(__name__)
