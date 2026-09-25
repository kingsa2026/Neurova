"""
Test: Freshness Preflight & GLANCE_YIELD_RULES Unit Tests
Phase 2 Coordination Layer - Testing
"""

import pytest
import time
from neurova.collaboration.seen_cursor import (
    SeenCursor, 
    SeenCursorManager, 
    reset_seen_cursor_manager,
)
from neurova.collaboration.glance_yield_rules import (
    GlanceYieldChecker, 
    YieldDecision, 
    YieldReason,
    reset_glance_yield_checker,
)


@pytest.fixture
def cursor_manager():
    """Create fresh SeenCursorManager for each test"""
    manager = SeenCursorManager()
    yield manager
    reset_seen_cursor_manager()


@pytest.fixture
def yield_checker():
    """Create fresh GlanceYieldChecker for each test"""
    checker = GlanceYieldChecker()
    checker.initialize(
        max_concurrent_agents_per_model=3,
        min_spawn_interval_seconds=1.0,
        adaptive_pacer_enabled=True,
    )
    yield checker
    reset_glance_yield_checker()


class TestSeenCursorCreation:
    """Test Seen Cursor creation"""
    
    def test_create_cursor(self, cursor_manager):
        """Test creating new cursor"""
        cursor = cursor_manager.create_cursor(
            agent_id="agent_123",
            session_id="sess_456",
            turn_id="turn_789",
            op_hashes=["hash_abc", "hash_def"],
        )
        
        assert cursor.agent_id == "agent_123"
        assert cursor.session_id == "sess_456"
        assert cursor.turn_id == "turn_789"
        assert len(cursor.op_hashes) == 2
        assert cursor.cursor_id.startswith("seen_")
    
    def test_add_operation_hash(self, cursor_manager):
        """Test adding operation to cursor"""
        cursor = cursor_manager.create_cursor(agent_id="agent_1")
        
        initial_count = len(cursor.op_hashes)
        cursor.add_operation_hash("new_hash")
        
        assert len(cursor.op_hashes) == initial_count + 1
    
    def test_compute_hash(self, cursor_manager):
        """Test cursor hash computation"""
        cursor = cursor_manager.create_cursor(
            agent_id="test_agent",
            op_hashes=["op1", "op2"],
        )
        
        computed = cursor.compute_hash()
        
        assert len(computed) == 64  # SHA256 hex length
        assert isinstance(computed, str)


class TestFreshnessPreflight:
    """Test Freshness Preflight logic"""
    
    def test_fresh_operations(self, cursor_manager):
        """Test fresh operations are allowed"""
        # No existing cursor
        is_fresh, reason = cursor_manager.check_freshness(
            agent_id="new_agent",
            expected_op_hashes=["hash_new"],
        )
        
        assert is_fresh is True
        assert reason is None
    
    def test_duplicate_detection(self, cursor_manager):
        """Test duplicate detection"""
        # Create cursor with operation
        cursor_manager.create_cursor(
            agent_id="agent_1",
            op_hashes=["existing_hash"],
        )
        
        # Check same operation
        is_fresh, reason = cursor_manager.check_freshness(
            agent_id="agent_1",
            expected_op_hashes=["existing_hash"],
        )
        
        assert is_fresh is False
        assert "already seen" in reason.lower()
    
    def test_partial_overlap(self, cursor_manager):
        """Test partial overlap detection"""
        # Create cursor with multiple operations
        cursor_manager.create_cursor(
            agent_id="agent_2",
            op_hashes=["hash_a", "hash_b", "hash_c"],
        )
        
        # Check subset of operations
        is_fresh, reason = cursor_manager.check_freshness(
            agent_id="agent_2",
            expected_op_hashes=["hash_a", "hash_d"],  # hash_a exists
        )
        
        assert is_fresh is False
        assert "hash_a" in reason or "already" in reason.lower()
    
    def test_recording_operations(self, cursor_manager):
        """Test recording operations"""
        cursor = cursor_manager.record_operations(
            agent_id="agent_new",
            session_id="sess_x",
            turn_id="turn_y",
            operation_hashes=["op1", "op2"],
        )
        
        assert len(cursor.op_hashes) == 2
        assert cursor.metadata.get("last_session") == "sess_x"


class TestGLANCE_YIELD_Rules:
    """Test GLANCE_YIELD_RULES implementation"""
    
    def test_register_agent(self, yield_checker):
        """Test agent registration"""
        yield_checker.register_agent("agent_a", "model_gpt4")
        
        load = yield_checker.get_current_load("model_gpt4")
        
        assert load["active_agents"] == 1
        assert "agent_a" in load["agents"]
    
    def test_concurrency_limit(self, yield_checker):
        """Test concurrency cap enforcement"""
        # Register 3 agents (max allowed)
        for i in range(3):
            yield_checker.register_agent(f"agent_{i}", "model_small")
        
        # Try to check another agent
        decision = yield_checker.check_yield_rules(
            agent_id="agent_new",
            model_name="model_small",
            proposed_operations=["op1"],
        )
        
        assert decision.should_yield is True
        assert decision.reason == YieldReason.MODEL_CONCURRENCY_LIMIT
    
    def test_spawn_spacing(self, yield_checker):
        """Test spawn interval enforcement"""
        yield_checker.register_agent("agent_spacing", "model_test")
        
        # Record recent spawn
        yield_checker._last_spawn_time["agent_spacing"] = time.time()
        
        # Check immediately - should yield
        decision = yield_checker.check_yield_rules(
            agent_id="agent_spacing",
            model_name="model_test",
            proposed_operations=["op1"],
        )
        
        assert decision.should_yield is True
        assert decision.reason == YieldReason.DETERMINISTIC_SPACING
    
    def test_verbatim_dup_detection(self, yield_checker):
        """Test verbatim duplicate detection"""
        yield_checker.register_agent("agent_dup", "model_dup")
        
        # Mark operations as pending
        yield_checker._pending_operations["agent_dup"] = {"op_a", "op_b"}
        
        # Check identical operations
        decision = yield_checker.check_yield_rules(
            agent_id="agent_dup",
            model_name="model_dup",
            proposed_operations=["op_a", "op_b"],
        )
        
        assert decision.should_yield is True
        assert decision.reason == YieldReason.VERBATIM_DUPLICATE
    
    def test_all_rules_pass(self, yield_checker):
        """Test when all rules pass"""
        yield_checker.register_agent("agent_ok", "model_ok")
        
        decision = yield_checker.check_yield_rules(
            agent_id="agent_ok",
            model_name="model_ok",
            proposed_operations=["fresh_op"],
        )
        
        assert decision.should_yield is False
        assert decision.reason is None


class TestAdaptivePacing:
    """Test adaptive pacing functionality"""
    
    def test_high_error_rate_backoff(self, yield_checker):
        """Test backoff on high error rate"""
        # Simulate high error rate
        yield_checker._pacing_stats["model_stress"] = {
            "total_ops": 100,
            "successful_ops": 60,
            "failed_ops": 40,
            "success_rate": 0.6,
            "error_rate": 0.4,
        }
        
        yield_checker.register_agent("agent_stress", "model_stress")
        
        decision = yield_checker.check_yield_rules(
            agent_id="agent_stress",
            model_name="model_stress",
            proposed_operations=["op1"],
        )
        
        assert decision.should_yield is True
        assert decision.reason == YieldReason.RESOURCE_CONTENTION
        assert decision.wait_time_seconds >= 5.0
    
    def test_normal_operation_no_backoff(self, yield_checker):
        """Test no backoff on normal operation"""
        # Normal stats
        yield_checker._pacing_stats["model_normal"] = {
            "total_ops": 100,
            "successful_ops": 95,
            "failed_ops": 5,
            "success_rate": 0.95,
            "error_rate": 0.05,
        }
        
        yield_checker.register_agent("agent_normal", "model_normal")
        
        decision = yield_checker.check_yield_rules(
            agent_id="agent_normal",
            model_name="model_normal",
            proposed_operations=["op1"],
        )
        
        assert decision.should_yield is False


class TestOperationLifecycle:
    """Test complete operation lifecycle"""
    
    def test_start_complete_cycle(self, yield_checker):
        """Test start and complete operation cycle"""
        yield_checker.register_agent("agent_cycle", "model_cycle")
        
        op_hash = "cycle_op_hash"
        
        # Start
        yield_checker.record_operation_start("agent_cycle", op_hash)
        
        assert op_hash in yield_checker._pending_operations["agent_cycle"]
        
        # Complete successfully
        yield_checker.record_operation_complete("agent_cycle", op_hash, success=True)
        
        assert op_hash not in yield_checker._pending_operations["agent_cycle"]
    
    def test_failure_tracking(self, yield_checker):
        """Test failure tracking updates pacing stats"""
        yield_checker.register_agent("agent_fail", "model_fail")
        
        # Simulate some failures
        yield_checker._pacing_stats["model_fail"] = {
            "total_ops": 10,
            "successful_ops": 5,
            "failed_ops": 5,
        }
        
        # Record another failure
        yield_checker.record_operation_complete("agent_fail", "fail_op", success=False)
        
        stats = yield_checker._pacing_stats["model_fail"]
        assert stats["total_ops"] == 11
        assert stats["failed_ops"] == 6


class TestCleanup:
    """Test cleanup operations"""
    
    def test_cleanup_old_cursors(self, cursor_manager):
        """Test cleanup of old cursors"""
        # Create multiple cursors for single agent
        for i in range(150):
            cursor_manager.create_cursor(
                agent_id="agent_cleanup",
                op_hashes=[f"hash_{i}"],
            )
        
        # Cleanup keeping only 100
        cleaned = cursor_manager.cleanup_old_cursors(keep_count=100)
        
        assert cleaned >= 40  # At least 50 should be cleaned (150-100)


class TestIntegration:
    """Integration tests combining both systems"""
    
    def test_full_coordination_flow(self, cursor_manager, yield_checker):
        """Test complete coordination flow"""
        import uuid
        agent_id = f"flow_agent_{uuid.uuid4().hex[:8]}"
        model_name = "flow_model"
        
        # Register agent
        yield_checker.register_agent(agent_id, model_name)
        
        # Check freshness - should be fresh initially (no history)
        is_fresh, _ = cursor_manager.check_freshness(
            agent_id=agent_id,
            expected_op_hashes=["fresh_op_1"],
        )
        assert is_fresh is True
        
        # Record operation
        cursor = cursor_manager.record_operations(
            agent_id=agent_id,
            session_id="sess_flow",
            turn_id="turn_flow",
            operation_hashes=["fresh_op_1"],
        )
        
        # Now check again - should NOT be fresh (already recorded)
        is_fresh_again, collision_reason = cursor_manager.check_freshness(
            agent_id=agent_id,
            expected_op_hashes=["fresh_op_1"],  # Same operation
        )
        
        # Should detect duplicate
        assert is_fresh_again is False
        assert collision_reason is not None
        assert "already seen" in collision_reason.lower()
    
    def test_collision_prevention(self, cursor_manager, yield_checker):
        """Test collision prevention end-to-end"""
        agent_id = "collision_agent"
        
        # First execution
        cursor_manager.create_cursor(
            agent_id=agent_id,
            op_hashes=["op_collision"],
        )
        
        # Second attempt should detect collision
        is_fresh, reason = cursor_manager.check_freshness(
            agent_id=agent_id,
            expected_op_hashes=["op_collision"],
        )
        
        assert is_fresh is False
        assert reason is not None
