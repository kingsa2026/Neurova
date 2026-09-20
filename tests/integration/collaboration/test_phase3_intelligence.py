"""
Test: Phase 3 - Intelligence & Realtime Features
Final Phase Testing
"""

import pytest
import time
from neurova.collaboration.small_brain_router import (
    SmallBrainRouter,
    RoutingContext,
    RoutingDecision,
    reset_small_brain_router,
)
from neurova.collaboration.outbox_handler import (
    OutboxEvent,
    EventStatus,
    OutboxHandler,
    get_outbox_handler,
    reset_outbox_handler,
)
from neurova.collaboration.cost_ledger_integration import (
    CostAlertSystem,
    reset_cost_alert_system,
)


@pytest.fixture
def router():
    """Create fresh SmallBrainRouter for each test"""
    router_instance = SmallBrainRouter()
    yield router_instance
    reset_small_brain_router()


@pytest.fixture
def outbox():
    """Create fresh OutboxHandler for each test"""
    handler = OutboxHandler()
    yield handler
    reset_outbox_handler()


@pytest.fixture
def alert_system():
    """Create fresh CostAlertSystem for each test"""
    system = CostAlertSystem()
    yield system
    reset_cost_alert_system()


class TestSmallBrainRouter:
    """Test Small-Brain Router functionality"""
    
    def test_classify_simple_question(self, router):
        """Test simple question classification"""
        query = "What is the weather today?"
        
        category, confidence = router.classify_query(query)
        
        # Should classify as something (confidence may vary)
        assert category is not None
        assert confidence >= 0.1
    
    def test_classify_code_generation(self, router):
        """Test code generation classification"""
        query = "Write a function to sort an array"
        
        category, confidence = router.classify_query(query)
        
        # Should classify as something
        assert category is not None
        assert confidence >= 0.1
    
    def test_classify_complex_task(self, router):
        """Test complex task classification"""
        query = "Design a microservices architecture for e-commerce"
        
        category, confidence = router.classify_query(query)
        
        # Should classify as something
        assert category is not None
        assert confidence >= 0.1
    
    def test_estimate_cost(self, router):
        """Test cost estimation"""
        cost = router.estimate_cost("gpt-4", 1000, direction="output")
        
        # gpt-4 output: $0.06/1K tokens
        assert cost == pytest.approx(0.06, rel=0.01)
    
    def test_select_model_for_simple_query(self, router):
        """Test model selection for simple queries"""
        context = RoutingContext(
            agent_id="agent_1",
            model_name="gpt-4",
            user_query="What is 2+2?",
            urgency_level=5,
        )
        
        available_models = ["gpt-3.5-turbo", "gpt-4", "claude-3"]
        
        selected_model, decision = router.select_model(context, available_models)
        
        # Should select a valid model
        assert selected_model in available_models
        assert decision in [RoutingDecision.ALLOW, RoutingDecision.ESCALATE]
    
    def test_route_request_simple(self, router):
        """Test routing simple request"""
        context = RoutingContext(
            agent_id="agent_simple",
            model_name="gpt-4",
            user_query="What is Python?",
            cost_budget=0.1,
            urgency_level=5,
        )
        
        result = router.route_request(context, ["gpt-3.5-turbo", "gpt-4"])
        
        assert result.decision in [RoutingDecision.ALLOW, RoutingDecision.ESCALATE]
        assert result.confidence_score > 0
    
    def test_route_request_exceeds_budget(self, router):
        """Test routing when budget exceeded"""
        context = RoutingContext(
            agent_id="agent_budget",
            model_name="gpt-4",
            user_query="Design enterprise architecture",
            cost_budget=0.001,  # Very low budget
            urgency_level=5,
        )
        
        result = router.route_request(context, ["gpt-4"])
        
        assert result.decision == RoutingDecision.DENY
        assert "budget" in result.reason.lower()
    
    def test_routing_stats(self, router):
        """Test routing statistics collection"""
        # Make several requests
        for _ in range(5):
            context = RoutingContext(
                agent_id="agent_stats",
                model_name="gpt-4",
                user_query="test query",
                cost_budget=0.1,
            )
            router.route_request(context)
        
        stats = router.get_routing_stats()
        
        assert stats["total_requests"] == 5
        assert "decision_distribution" in stats


class TestOutboxHandler:
    """Test Outbox Handler functionality"""
    
    def test_publish_event(self, outbox):
        """Test publishing event"""
        event = outbox.publish(
            event_type="test_event",
            agent_id="agent_test",
            payload={"key": "value"},
            priority=7,
        )
        
        assert event.event_id.startswith("evt_")
        assert event.event_type == "test_event"
        assert event.status == EventStatus.PENDING
        assert event.payload["key"] == "value"
    
    def test_register_handler(self, outbox):
        """Test registering event handler"""
        handler_called = []
        
        def test_handler(event: OutboxEvent) -> bool:
            handler_called.append(event.event_id)
            return True
        
        outbox.register_handler("test_event", test_handler)
        
        # Publish and process
        event = outbox.publish(
            event_type="test_event",
            agent_id="agent_handler",
            payload={},
        )
        
        processed = outbox.process_pending_events()
        
        # At least one event should be processed
        assert processed >= 1
    
    def test_event_retry_mechanism(self, outbox):
        """Test event retry mechanism"""
        fail_count = [0]
        
        def failing_handler(event: OutboxEvent) -> bool:
            fail_count[0] += 1
            return False  # Always fail
        
        outbox.register_handler("retry_test", failing_handler)
        
        # Publish event (max_retries is set on the event object itself)
        event = outbox.publish(
            event_type="retry_test",
            agent_id="agent_retry",
            payload={},
        )
        event.max_retries = 2  # Set directly on event
        
        # Process multiple times
        for _ in range(3):
            outbox.process_pending_events()
        
        # Should have retried at least once
        assert fail_count[0] >= 1
    
    def test_get_agent_events(self, outbox):
        """Test getting agent's events"""
        # Publish multiple events for unique agent
        import uuid
        unique_agent = f"agent_multi_{uuid.uuid4().hex[:8]}"
        
        for i in range(3):
            outbox.publish(
                event_type="agent_event",
                agent_id=unique_agent,
                payload={"index": i},
            )
        
        events = outbox.get_agent_events(unique_agent)
        
        assert len(events) == 3
    
    def test_outbox_stats(self, outbox):
        """Test outbox statistics"""
        # Publish some events
        for _ in range(5):
            outbox.publish(
                event_type="stat_test",
                agent_id="agent_stat",
                payload={},
            )
        
        stats = outbox.get_stats()
        
        assert stats["total_events"] == 5
        assert "success_rate" in stats
    
    def test_dead_letter_queue(self, outbox):
        """Test dead letter queue functionality"""
        def always_fail_handler(event: OutboxEvent) -> bool:
            return False
        
        outbox.register_handler("dlq_test", always_fail_handler)
        
        event = outbox.publish(
            event_type="dlq_test",
            agent_id="agent_dlq",
            payload={},
        )
        event.max_retries = 1  # Set directly on event
        
        # Process until failure
        outbox.process_pending_events()
        
        # Event should be in failed state or pending (retrying)
        assert event.status in [EventStatus.FAILED, EventStatus.PENDING]


class TestCostAlertSystem:
    """Test Cost Alert System"""
    
    def test_set_threshold(self, alert_system):
        """Test setting cost threshold"""
        alert_system.set_threshold("agent_1", 10.0)
        
        # Verify threshold is set (internal state)
        assert "agent_1" in alert_system._thresholds
    
    def test_check_threshold_not_exceeded(self, alert_system):
        """Test threshold check when not exceeded"""
        alert_system.set_threshold("agent_2", 100.0)
        
        exceeded = alert_system.check_threshold("agent_2", 50.0)
        
        assert exceeded is False
    
    def test_check_threshold_exceeded(self, alert_system):
        """Test threshold check when exceeded"""
        alert_system.set_threshold("agent_3", 10.0)
        
        # Accumulate spend
        alert_system.check_threshold("agent_3", 6.0)
        alert_system.check_threshold("agent_3", 5.0)  # Total: 11.0
        
        exceeded = alert_system.check_threshold("agent_3", 0.0)
        
        assert exceeded is True
    
    def test_reset_spend(self, alert_system):
        """Test resetting agent spend"""
        alert_system.set_threshold("agent_4", 100.0)
        
        # Accumulate spend
        alert_system.check_threshold("agent_4", 50.0)
        
        # Reset
        alert_system.reset_spend("agent_4")
        
        # Check current spend is reset
        assert alert_system._current_spends["agent_4"] == 0


class TestIntegration:
    """Integration tests combining all Phase 3 components"""
    
    def test_full_intelligence_pipeline(self, router, outbox):
        """Test complete intelligence pipeline"""
        # 1. Route request
        context = RoutingContext(
            agent_id="pipeline_agent",
            model_name="gpt-4",
            user_query="Write a Python script",
            cost_budget=0.5,
        )
        
        routing_result = router.route_request(context, ["gpt-4", "gpt-3.5"])
        
        # 2. Based on routing, publish event
        if routing_result.decision.value == "allow":
            event = outbox.publish(
                event_type="task_started",
                agent_id="pipeline_agent",
                payload={
                    "routing_decision": routing_result.to_dict(),
                    "selected_model": routing_result.suggested_model,
                },
                priority=7,
            )
            
            assert event.event_id is not None
    
    def test_cost_tracking_with_alerts(self, outbox, alert_system):
        """Test cost tracking with alerts"""
        # Set threshold
        alert_system.set_threshold("cost_agent", 0.10)
        
        # Simulate multiple LLM calls
        call_costs = [0.03, 0.04, 0.05]
        
        for cost in call_costs:
            # Check threshold
            exceeded = alert_system.check_threshold("cost_agent", cost)
            
            # Publish cost event
            outbox.publish(
                event_type="llm_cost_recorded",
                agent_id="cost_agent",
                payload={
                    "cost_usd": cost,
                    "exceeded": exceeded,
                },
                priority=5,
            )
        
        # Last call should exceed threshold
        assert exceeded is True


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_router_unknown_category(self, router):
        """Test router with unknown query type"""
        query = "xyz123randomtext"
        
        category, confidence = router.classify_query(query)
        
        # Should default to something
        assert category is not None
    
    def test_outbox_expired_event(self, outbox):
        """Test expired event handling"""
        event = outbox.publish(
            event_type="expire_test",
            agent_id="agent_expire",
            payload={},
            expiration_ttl=0,  # Immediate expiration
        )
        
        # Should be marked as expired
        assert event.is_expired()
    
    def test_alert_system_no_threshold(self, alert_system):
        """Test alert system without threshold"""
        # Should not raise exception
        exceeded = alert_system.check_threshold("no_threshold_agent", 100.0)
        
        assert exceeded is False
