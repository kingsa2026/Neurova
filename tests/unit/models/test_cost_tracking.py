"""
Test: LLM Cost Tracker Unit Tests
Phase 1 Foundation - Testing
"""

import pytest
from datetime import datetime, timedelta
from neurova.models.cost_tracking import (
    CostTracker, 
    LLMCall, 
    LLMProvider, 
    LLMDirection,
    reset_cost_tracker,
    track_llm_call,
)


@pytest.fixture
def cost_tracker():
    """Create fresh CostTracker for each test"""
    tracker = CostTracker()
    yield tracker
    reset_cost_tracker()


class TestLLMCallCreation:
    """Test LLMCall creation"""
    
    def test_create_llm_call(self):
        """Test creating LLMCall object"""
        call = LLMCall(
            agent_id="agent_123",
            provider=LLMProvider.OPENAI,
            model="gpt-4",
            direction=LLMDirection.INPUT,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0045,
        )
        
        assert call.agent_id == "agent_123"
        assert call.provider == LLMProvider.OPENAI
        assert call.model == "gpt-4"
        assert call.direction == LLMDirection.INPUT
        assert call.input_tokens == 100
        assert call.output_tokens == 50
        assert call.cost_usd == 0.0045
    
    def test_to_dict_and_from_dict(self):
        """Test serialization/deserialization"""
        original = LLMCall(
            agent_id="agent_456",
            provider=LLMProvider.ANTHROPIC,
            model="claude-3.5-sonnet",
            input_tokens=200,
            output_tokens=100,
            cost_usd=0.0045,
        )
        
        # Serialize
        data = original.to_dict()
        
        # Deserialize
        restored = LLMCall.from_dict(data)
        
        assert restored.call_id == original.call_id
        assert restored.agent_id == original.agent_id
        assert restored.model == original.model
        assert restored.input_tokens == original.input_tokens
        assert restored.output_tokens == original.output_tokens
        assert restored.cost_usd == original.cost_usd


class TestCostCalculation:
    """Test cost calculation logic"""
    
    def test_openai_gpt4_cost(self):
        """Test OpenAI GPT-4 cost calculation"""
        tracker = CostTracker()
        
        cost = tracker.calculate_cost(
            provider=LLMProvider.OPENAI,
            model="gpt-4",
            input_tokens=1000,
            output_tokens=500,
        )
        
        # gpt-4: $0.03/1K input, $0.06/1K output
        expected = (1000 * 0.03 / 1000) + (500 * 0.06 / 1000)
        assert cost == expected
    
    def test_claude_3_sonnet_cost(self):
        """Test Claude 3 Sonnet cost calculation"""
        tracker = CostTracker()
        
        cost = tracker.calculate_cost(
            provider=LLMProvider.ANTHROPIC,
            model="claude-3-sonnet",
            input_tokens=1000,
            output_tokens=500,
        )
        
        # claude-3-sonnet: $0.003/1K input, $0.015/1K output
        expected = (1000 * 0.003 / 1000) + (500 * 0.015 / 1000)
        assert cost == pytest.approx(expected, rel=1e-9)
    
    def test_unknown_model_cost(self):
        """Test unknown model returns zero cost"""
        tracker = CostTracker()
        
        cost = tracker.calculate_cost(
            provider=LLMProvider.OPENAI,
            model="unknown-model",
            input_tokens=1000,
            output_tokens=500,
        )
        
        assert cost == 0.0


class TestCostSummary:
    """Test cost summary queries"""
    
    @pytest.mark.asyncio
    async def test_get_agent_cost_summary(self, cost_tracker, mock_db_pool):
        """Test getting agent cost summary"""
        # Setup mock data
        await mock_db_pool.execute("""
            INSERT INTO llm_calls (agent_id, provider, model, input_tokens, output_tokens, cost_usd, called_at)
            VALUES 
                ('agent_123', 'openai', 'gpt-4', 1000, 500, 0.045, :now),
                ('agent_123', 'anthropic', 'claude-3', 2000, 1000, 0.021, :now)
        """, {"now": datetime.now()})
        
        start_time = datetime.now() - timedelta(hours=1)
        end_time = datetime.now()
        
        summary = await cost_tracker.get_agent_cost_summary("agent_123", start_time, end_time)
        
        assert summary["agent_id"] == "agent_123"
        assert summary["total_cost"] == pytest.approx(0.066, rel=0.001)
        assert len(summary["summary"]) == 2
    
    @pytest.mark.asyncio
    async def test_empty_cost_summary(self, cost_tracker, mock_db_pool):
        """Test empty cost summary"""
        start_time = datetime.now() - timedelta(hours=1)
        end_time = datetime.now()
        
        summary = await cost_tracker.get_agent_cost_summary("nonexistent_agent", start_time, end_time)
        
        assert summary == {}


class TestCostTrackingDecorator:
    """Test track_llm_call decorator"""
    
    def test_decorator_basic(self):
        """Test basic decorator usage"""
        from functools import wraps
        
        @track_llm_call(provider=LLMProvider.OPENAI, model="gpt-4", agent_id="test_agent")
        async def mock_llm_call(messages):
            return {
                "content": "Hello!",
                "usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 25,
                }
            }
        
        # Verify function is wrapped
        assert hasattr(mock_llm_call, '__wrapped__')
    
    def test_decorator_with_cache_tokens(self):
        """Test decorator with cache tokens"""
        @track_llm_call(
            provider=LLMProvider.OPENAI, 
            model="gpt-4o", 
            agent_id="cache_test",
            direction=LLMDirection.INPUT
        )
        async def mock_llm_call_with_cache(messages):
            return {
                "content": "Cached response",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "cache_read_tokens": 50,
                    "cache_write_tokens": 10,
                }
            }
        
        # Verify function is wrapped
        assert hasattr(mock_llm_call_with_cache, '__wrapped__')


class TestSingletonPattern:
    """Test CostTracker singleton pattern"""
    
    def test_singleton_instance(self):
        """Test that only one instance exists"""
        tracker1 = CostTracker()
        tracker2 = CostTracker()
        
        assert tracker1 is tracker2
    
    def test_reset_cost_tracker(self):
        """Test resetting CostTracker - verifies reset function exists and runs"""
        # Just verify the reset function doesn't crash
        tracker = CostTracker()
        reset_cost_tracker()  # Should not raise exception


# Helper function for decorator test
def _calculate_cost_from_usage(provider, model, usage):
    """Calculate cost from usage dict"""
    price_map = {
        LLMProvider.OPENAI: {
            "gpt-4": {"input": 0.03},
        },
    }.get(provider, {}).get(model, {"input": 0})
    
    return price_map.get("input", 0) * usage.get('prompt_tokens', 0) / 1000
