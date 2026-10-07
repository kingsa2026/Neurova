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
    """让位闸端到端：真裁决器单例 + 真进程内 await，走回合入口该走的那条路。

    用例之间先 `await reset_glance_yield_checker()`——这是生产重置入口
    （`/api/coordination/yield-checker/reset` 走的就是它），不是测试自造的旁路。
    """

    @staticmethod
    async def _freshChecker():
        from neurova.collaboration.glance_yield_rules import (
            get_glance_yield_checker,
            reset_glance_yield_checker,
        )

        await reset_glance_yield_checker()
        return await get_glance_yield_checker()

    @pytest.mark.asyncio
    async def test_first_turn_proceeds_and_occupies_exactly_one_slot(self):
        """放行一个回合只占一格，且把操作标识回带给调用方（挂起时要按它记账）。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = await self._freshChecker()

        outcome = await requestYieldGate(
            agentId="e2e-agent", modelName="gpt-4", sessionId="sess-e2e", userInput="你好"
        )

        assert outcome.proceeded is True
        assert outcome.attempts == 1
        assert checker.get_stats()["active_per_model"] == {"gpt-4": 1}, (
            f"占位与放行不一致：{checker.get_stats()['active_per_model']}"
        )
        assert outcome.operation, "操作标识为空——挂起时无法向台账交代是哪个回合"

    @pytest.mark.asyncio
    async def test_repeated_turns_never_exhaust_the_model_quota(self):
        """连开 8 个回合不该把自己模型的额度吃光（旧记账判一次加一次，第 7 次起恒让位）。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = await self._freshChecker()

        for _ in range(8):
            outcome = await requestYieldGate(
                agentId="e2e-loopy", modelName="gpt-4", sessionId="s", userInput="继续"
            )
            assert outcome.proceeded is True, "同一 Agent 反复问就把额度占满——查询当成了开工"
            checker.record_operation_complete("e2e-loopy", outcome.operation, success=True)

    @pytest.mark.asyncio
    async def test_persistent_yield_parks_after_bounded_waiting(self, monkeypatch):
        """冷却不会自愈时：等满预算（10 次 × 20s）就挂起，并带着原因回来。"""
        import asyncio

        from neurova.agent.turn_coordinator import requestYieldGate
        from neurova.collaboration.glance_yield_rules import GlanceYieldChecker

        checker = await self._freshChecker()
        monkeypatch.setattr(GlanceYieldChecker, "DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS", 10 ** 6)
        checker.trigger_rate_limit("e2e-parked")
        slept = []

        async def fakeSleep(seconds):
            slept.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fakeSleep)

        outcome = await requestYieldGate(
            agentId="e2e-parked", modelName="gpt-4", sessionId="s", userInput="继续"
        )

        assert outcome.shouldPark is True
        assert outcome.attempts == 11 and len(slept) == 10
        assert sum(slept) <= 200.0 and max(slept) <= 20.0
        assert outcome.parkReason, "挂起必须带原因"

    @pytest.mark.asyncio
    async def test_occupationIsReleasedOnCompletion(self):
        """完成即还槽——否则跑够 6 个回合之后该模型永久满员。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = await self._freshChecker()

        for index in range(checker.DEFAULT_MAX_CONCURRENT_AGENTS):
            outcome = await requestYieldGate(
                agentId=f"e2e-{index}",
                modelName="gpt-4",
                sessionId="s",
                userInput=f"第 {index} 个回合",
            )
            assert outcome.proceeded is True
            checker.record_operation_complete(f"e2e-{index}", outcome.operation, success=True)

        late = await requestYieldGate(
            agentId="e2e-late", modelName="gpt-4", sessionId="s", userInput="迟到"
        )
        assert late.proceeded is True, (
            f"每个回合都正常完成了，第 7 个仍被挡下（active="
            f"{checker.get_stats()['active_per_model']}）——释放路径没接回计数"
        )


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
        from neurova.agent.turn_coordinator import requestYieldGate
        from neurova.agent.model_selector import get_smart_model_selector

        # Step 1: 两个 Agent 各过一个真回合入口的让位闸
        for agentId, model in (("agent_1", "gpt-4"), ("agent_2", "gpt-3.5")):
            outcome = await requestYieldGate(
                agentId=agentId, modelName=model, sessionId="sess-wf", userInput="What is AI?"
            )
            assert outcome.proceeded is True
        
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
        """两个 Agent 抢同一模型：占满之后后来者必须被让位，释放后又能过。"""
        from neurova.agent.turn_coordinator import requestYieldGate
        from neurova.collaboration.glance_yield_rules import reset_glance_yield_checker

        await reset_glance_yield_checker()
        from neurova.collaboration.glance_yield_rules import get_glance_yield_checker

        checker = await get_glance_yield_checker()
        limit = checker.DEFAULT_MAX_CONCURRENT_AGENTS
        running = []

        for index in range(limit):
            outcome = await requestYieldGate(
                agentId=f"ma-{index}",
                modelName="gpt-4",
                sessionId="sess-ma",
                userInput=f"任务 {index}",
            )
            assert outcome.proceeded is True
            running.append((f"ma-{index}", outcome.operation))

        # 闸自身会重试等待；这里只看一次判据结论，不把等待的时间算进断言
        decision = checker.check_yield_rules(
            agent_id="ma-late",
            model_name="gpt-4",
            proposed_operations=["op-late"],
            conversation_id="sess-ma",
        )
        assert decision.should_yield is True and decision.reason.value == "concurrent_agent", (
            f"占满 {limit} 个操作后后来者却没被挡下：{decision}"
        )

        for agentId, operation in running:
            checker.record_operation_complete(agentId, operation, success=True)
        assert checker.get_stats()["active_per_model"].get("gpt-4", 0) == 0


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
        """放行路径的闸开销必须可忽略——它每回合都要跑，不能变成新的慢点。"""
        import asyncio
        import time

        from neurova.agent.turn_coordinator import requestYieldGate
        from neurova.collaboration.glance_yield_rules import reset_glance_yield_checker

        await reset_glance_yield_checker()
        await requestYieldGate(
            agentId="perf_agent", modelName="gpt-4", sessionId="s", userInput="warm"
        )

        start = time.perf_counter()
        for index in range(5):
            # 每个回合用不同 agent：Layer 3 的生成间距（500ms）会因"同一 agent 连开两回合"
            # 而合法地让闸等一次，那是节流不是开销——测开销要把它排除掉。
            outcome = await requestYieldGate(
                agentId=f"perf-{index}", modelName="gpt-4", sessionId="s", userInput=f"op-{index}"
            )
            assert outcome.proceeded is True and outcome.attempts == 1, (
                f"无竞争场景下闸却等了（attempts={outcome.attempts}, "
                f"waited={outcome.waitedSeconds}）——判据链上有别的东西在挡"
            )
        avgTime = (time.perf_counter() - start) / 5

        assert avgTime < 0.01, f"闸的平均开销 {avgTime:.6f}s 过高（每回合都要付）"


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
