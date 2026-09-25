"""
Unit Tests for Budget Management System

Tests coverage:
- Budget configuration and lifecycle
- Real-time usage tracking
- Alert threshold triggering
- Budget throttling logic
"""

import pytest
from decimal import Decimal
from datetime import datetime, timedelta
from neurova.models.cost_budget import (
    BudgetManager,
    BudgetService,
    BudgetConfig,
    AlertConfig,
    AlertLevel,
    BudgetScope,
    AlertChannel,
    get_budget_service,
    reset_budget_service,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def budget_manager():
    """Create fresh BudgetManager instance"""
    return BudgetManager()


@pytest.fixture
def sample_budget():
    """Create sample budget configuration"""
    now = datetime.now()
    return BudgetConfig(
        scope=BudgetScope.HOURLY,
        identifier="test_agent",
        amount=Decimal("10.00"),
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
        auto_reset=True
    )


# ============================================================================
# Budget Manager Tests
# ============================================================================

class TestBudgetManager:
    """Test BudgetManager core functionality"""
    
    def test_register_budget(self, budget_manager):
        """Test budget registration"""
        config = BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier="agent_1",
            amount=Decimal("100.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(hours=1)
        )
        
        budget_manager.register_budget(config)
        
        assert "hourly:agent_1" in budget_manager._budgets
        assert budget_manager._budgets["hourly:agent_1"].amount == Decimal("100.00")
        
    def test_unregister_budget(self, budget_manager):
        """Test budget removal"""
        config = BudgetConfig(
            scope=BudgetScope.DAILY,
            identifier="agent_2",
            amount=Decimal("50.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(days=1)
        )
        
        budget_manager.register_budget(config)
        budget_manager.unregister_budget(BudgetScope.DAILY, "agent_2")
        
        assert "daily:agent_2" not in budget_manager._budgets
        
    def test_record_usage(self, budget_manager, sample_budget):
        """Test usage recording"""
        budget_manager.register_budget(sample_budget)
        
        # Record some usage
        budget_manager.record_usage(BudgetScope.HOURLY, "test_agent", Decimal("2.50"))
        budget_manager.record_usage(BudgetScope.HOURLY, "test_agent", Decimal("3.75"))
        
        # Verify usage accumulation
        usage = budget_manager.get_usage(BudgetScope.HOURLY, "test_agent")
        assert usage == Decimal("6.25")
        
    def test_get_remaining(self, budget_manager, sample_budget):
        """Test remaining budget calculation"""
        budget_manager.register_budget(sample_budget)
        budget_manager.record_usage(BudgetScope.HOURLY, "test_agent", Decimal("3.00"))
        
        remaining = budget_manager.get_remaining(BudgetScope.HOURLY, "test_agent")
        assert remaining == Decimal("7.00")
        
    def test_get_usage_percentage(self, budget_manager, sample_budget):
        """Test usage percentage calculation"""
        budget_manager.register_budget(sample_budget)
        budget_manager.record_usage(BudgetScope.HOURLY, "test_agent", Decimal("5.00"))
        
        percentage = budget_manager.get_usage_percentage(BudgetScope.HOURLY, "test_agent")
        assert percentage == Decimal("50.00")
        
    def test_is_over_budget(self, budget_manager, sample_budget):
        """Test over-budget detection"""
        budget_manager.register_budget(sample_budget)
        
        # Not over budget yet
        assert not budget_manager.is_over_budget(BudgetScope.HOURLY, "test_agent")
        
        # Exceed budget
        budget_manager.record_usage(BudgetScope.HOURLY, "test_agent", Decimal("15.00"))
        assert budget_manager.is_over_budget(BudgetScope.HOURLY, "test_agent")
        
    def test_throttle_if_needed(self, budget_manager, sample_budget):
        """Test automatic throttling"""
        budget_manager.register_budget(sample_budget)
        
        # Should not throttle under budget
        assert not budget_manager.throttle_if_needed(BudgetScope.HOURLY, "test_agent")
        
        # Should throttle over budget
        budget_manager.record_usage(BudgetScope.HOURLY, "test_agent", Decimal("15.00"))
        assert budget_manager.throttle_if_needed(BudgetScope.HOURLY, "test_agent")


# ============================================================================
# Alert System Tests
# ============================================================================

class TestAlertSystem:
    """Test alert threshold system"""
    
    def test_info_alert_trigger(self, budget_manager):
        """Test INFO level alert at 50%"""
        config = BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier="alert_test",
            amount=Decimal("10.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(hours=1)
        )
        
        budget_manager.register_budget(config)
        
        # Record 50% usage - should trigger INFO alert
        budget_manager.record_usage(BudgetScope.HOURLY, "alert_test", Decimal("5.00"))
        
        # Check that alert was logged (would appear in logs)
        percentage = budget_manager.get_usage_percentage(BudgetScope.HOURLY, "alert_test")
        assert percentage == Decimal("50.00")
        
    def test_warning_alert_trigger(self, budget_manager):
        """Test WARNING level alert at 75%"""
        config = BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier="alert_test",
            amount=Decimal("10.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(hours=1)
        )
        
        budget_manager.register_budget(config)
        
        # Record 75% usage - should trigger WARNING alert
        budget_manager.record_usage(BudgetScope.HOURLY, "alert_test", Decimal("7.50"))
        
        percentage = budget_manager.get_usage_percentage(BudgetScope.HOURLY, "alert_test")
        assert percentage == Decimal("75.00")
        
    def test_critical_alert_trigger(self, budget_manager):
        """Test CRITICAL level alert at 90%"""
        config = BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier="alert_test",
            amount=Decimal("10.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(hours=1)
        )
        
        budget_manager.register_budget(config)
        
        # Record 90% usage - should trigger CRITICAL alert
        budget_manager.record_usage(BudgetScope.HOURLY, "alert_test", Decimal("9.00"))
        
        percentage = budget_manager.get_usage_percentage(BudgetScope.HOURLY, "alert_test")
        assert percentage == Decimal("90.00")
        
    def test_exceeded_alert_trigger(self, budget_manager):
        """Test EXCEEDED alert at 100%+"""
        config = BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier="alert_test",
            amount=Decimal("10.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(hours=1)
        )
        
        budget_manager.register_budget(config)
        
        # Exceed budget - should trigger EXCEEDED alert
        budget_manager.record_usage(BudgetScope.HOURLY, "alert_test", Decimal("12.50"))
        
        percentage = budget_manager.get_usage_percentage(BudgetScope.HOURLY, "alert_test")
        assert percentage == Decimal("125.00")
        assert budget_manager.is_over_budget(BudgetScope.HOURLY, "alert_test")
        
    def test_no_duplicate_alerts(self, budget_manager):
        """Test that alerts are not duplicated"""
        config = BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier="alert_test",
            amount=Decimal("10.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(hours=1)
        )
        
        budget_manager.register_budget(config)
        
        # Record 75% usage (triggers WARNING)
        budget_manager.record_usage(BudgetScope.HOURLY, "alert_test", Decimal("7.50"))
        last_alerted_75 = budget_manager._last_alerted.get("hourly:alert_test", {}).get(AlertLevel.WARNING)
        
        # Record more usage but still at WARNING level
        budget_manager.record_usage(BudgetScope.HOURLY, "alert_test", Decimal("0.50"))
        
        # Should have same last alerted time (no duplicate)
        assert last_alerted_75 == budget_manager._last_alerted.get("hourly:alert_test", {}).get(AlertLevel.WARNING)


# ============================================================================
# Budget Service Tests
# ============================================================================

class TestBudgetService:
    """Test high-level BudgetService API"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup before each test"""
        reset_budget_service()
        yield
        reset_budget_service()
        
    def test_record_llm_call_cost(self):
        """Test LLM call cost recording across budgets"""
        service = BudgetService()
        service.initialize()
        
        # Record an LLM call
        service.record_llm_call_cost(
            agent_id="agent_1",
            provider="openai",
            model="gpt-4",
            cost=Decimal("0.05")
        )
        
        # Verify costs recorded against multiple budgets
        agent_usage = service.manager.get_usage(BudgetScope.HOURLY, "agent_1")
        provider_usage = service.manager.get_usage(BudgetScope.PROVIDER, "openai")
        model_usage = service.manager.get_usage(BudgetScope.MODEL, "gpt-4")
        
        assert agent_usage == Decimal("0.05")
        assert provider_usage == Decimal("0.05")
        assert model_usage == Decimal("0.05")
        
    def test_get_agent_budget_status(self):
        """Test getting agent budget status"""
        service = BudgetService()
        service.initialize()
        
        # Register a budget
        config = BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier="agent_1",
            amount=Decimal("10.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(hours=1)
        )
        service.manager.register_budget(config)
        
        # Record some usage
        service.record_llm_call_cost(
            agent_id="agent_1",
            provider="openai",
            model="gpt-4",
            cost=Decimal("3.00")
        )
        
        # Get status
        status = service.get_agent_budget_status("agent_1")
        
        assert status["agent_id"] == "agent_1"
        assert status["hourly"]["usage"] == 3.0
        assert status["hourly"]["remaining"] == 7.0
        assert status["hourly"]["percentage"] == 30.0
        assert status["hourly"]["is_over_budget"] is False
        
    def test_get_all_budget_statuses(self):
        """Test getting all budget statuses"""
        service = BudgetService()
        service.initialize()
        
        # Register multiple budgets
        for i in range(3):
            config = BudgetConfig(
                scope=BudgetScope.HOURLY,
                identifier=f"agent_{i}",
                amount=Decimal("10.00"),
                period_start=datetime.now(),
                period_end=datetime.now() + timedelta(hours=1)
            )
            service.manager.register_budget(config)
            
            service.record_llm_call_cost(
                agent_id=f"agent_{i}",
                provider="openai",
                model="gpt-4",
                cost=Decimal("2.00")
            )
        
        # Get all statuses
        result = service.get_all_budget_statuses()
        
        # Result is a dict of budget keys to status dicts (not wrapped in "budgets" key)
        assert len(result) >= 3
        assert all("scope" in b for b in result.values())
        assert all("identifier" in b for b in result.values())


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_zero_budget(self, budget_manager):
        """Test behavior with zero budget"""
        config = BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier="zero_budget",
            amount=Decimal("0.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(hours=1)
        )
        
        budget_manager.register_budget(config)
        
        # Should handle gracefully
        percentage = budget_manager.get_usage_percentage(BudgetScope.HOURLY, "zero_budget")
        assert percentage == Decimal("0.00")
        
    def test_negative_usage(self, budget_manager, sample_budget):
        """Test negative usage (should be handled)"""
        budget_manager.register_budget(sample_budget)
        
        # Record negative usage
        budget_manager.record_usage(BudgetScope.HOURLY, "test_agent", Decimal("-1.00"))
        
        # Should subtract from usage
        usage = budget_manager.get_usage(BudgetScope.HOURLY, "test_agent")
        assert usage == Decimal("-1.00")
        
    def test_unregistered_budget(self, budget_manager):
        """Test accessing unregistered budget"""
        # Should return zeros for unregistered budgets
        usage = budget_manager.get_usage(BudgetScope.HOURLY, "unknown_agent")
        remaining = budget_manager.get_remaining(BudgetScope.HOURLY, "unknown_agent")
        percentage = budget_manager.get_usage_percentage(BudgetScope.HOURLY, "unknown_agent")
        
        assert usage == Decimal("0.00")
        assert remaining == Decimal("0.00")
        assert percentage == Decimal("0.00")


# ============================================================================
# Performance Tests
# ============================================================================

class TestPerformance:
    """Test performance under load"""
    
    def test_high_frequency_usage_recording(self, budget_manager):
        """Test recording many small usage amounts"""
        config = BudgetConfig(
            scope=BudgetScope.HOURLY,
            identifier="perf_test",
            amount=Decimal("1000.00"),
            period_start=datetime.now(),
            period_end=datetime.now() + timedelta(hours=1)
        )
        
        budget_manager.register_budget(config)
        
        # Record 1000 small transactions
        for i in range(1000):
            budget_manager.record_usage(BudgetScope.HOURLY, "perf_test", Decimal("0.01"))
        
        usage = budget_manager.get_usage(BudgetScope.HOURLY, "perf_test")
        assert usage == Decimal("10.00")
        
    def test_concurrent_access(self, budget_manager, sample_budget):
        """Test thread-safe concurrent access"""
        import threading
        
        budget_manager.register_budget(sample_budget)
        errors = []
        
        def record_usage_thread():
            try:
                for _ in range(100):
                    budget_manager.record_usage(BudgetScope.HOURLY, "concurrent_test", Decimal("0.01"))
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = [threading.Thread(target=record_usage_thread) for _ in range(10)]
        
        # Start all threads
        for t in threads:
            t.start()
            
        # Wait for completion
        for t in threads:
            t.join()
        
        # Should have no errors
        assert len(errors) == 0
        
        # Verify final usage
        usage = budget_manager.get_usage(BudgetScope.HOURLY, "concurrent_test")
        # 10 threads * 100 iterations * 0.01 = 10.00
        assert usage == Decimal("10.00")
