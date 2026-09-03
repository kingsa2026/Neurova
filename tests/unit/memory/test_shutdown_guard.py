"""
Tracer bullet tests for ShutdownGuard — memory write safety net.

Tests verify behavior through public interface only.
"""
import os
import json
import time
import tempfile
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, PropertyMock


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def temp_dir():
    """Temporary workspace directory isolating test file artifacts."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def guard(temp_dir):
    """Create a ShutdownGuard instance with isolated workspace."""
    from neurova.recovery.shutdown_guard import ShutdownGuard
    return ShutdownGuard(workspace_dir=str(temp_dir))


# ── Test 1: Clean Startup/Shutdown Sentinel Cycle ───────────

class TestSentinelLifecycle:
    """Tracer bullet: sentinel written on startup, removed on clean shutdown,
    absent after successful restart."""

    def test_write_sentinel_creates_file(self, guard, temp_dir):
        """RED→GREEN: write_sentinel creates a sentinel file with PID+timestamp."""
        guard.write_sentinel()
        
        sentinel = temp_dir / ".neurova_shutdown_sentinel"
        assert sentinel.exists(), "Sentinel file should be created"
        
        data = json.loads(sentinel.read_text(encoding="utf-8"))
        assert "pid" in data
        assert "started_at" in data
        assert data["pid"] > 0

    def test_mark_clean_shutdown_removes_sentinel(self, guard, temp_dir):
        """RED→GREEN: mark_clean_shutdown removes the sentinel file."""
        guard.write_sentinel()
        guard.mark_clean_shutdown()
        
        sentinel = temp_dir / ".neurova_shutdown_sentinel"
        assert not sentinel.exists(), "Sentinel should be removed on clean shutdown"

    def test_clean_startup_detects_no_abnormal(self, guard, temp_dir):
        """RED→GREEN: On fresh startup without sentinel, no abnormal shutdown detected."""
        result = guard.check_abnormal_shutdown()
        
        assert result["abnormal"] is False
        assert result["crash_time"] is None

    def test_abnormal_shutdown_detected(self, guard, temp_dir):
        """RED→GREEN: If sentinel exists at startup, abnormal shutdown is detected."""
        # Simulate: previous run wrote sentinel but didn't clean up
        sentinel = temp_dir / ".neurova_shutdown_sentinel"
        crash_time = datetime.now(timezone.utc) - timedelta(hours=1)
        sentinel.write_text(json.dumps({
            "pid": 99999,
            "started_at": crash_time.isoformat(),
        }), encoding="utf-8")
        
        result = guard.check_abnormal_shutdown()
        
        assert result["abnormal"] is True
        assert result["crash_time"] is not None
        assert abs((result["crash_time"] - crash_time).total_seconds()) < 5


# ── Test 2: Buffer Flush on Shutdown ────────────────────────

class TestBufferFlush:
    """Tracer bullet: all agent conversation buffers are force-flushed on shutdown."""

    def test_flush_all_buffers_calls_force_flush_on_each(self, guard):
        """RED→GREEN: flush_all_agent_buffers iterates all agents and force-flushes."""
        agent1 = MagicMock()
        agent1.config.agent_id = "agent_1"
        buf1 = MagicMock()
        
        agent2 = MagicMock()
        agent2.config.agent_id = "agent_2"
        buf2 = MagicMock()
        
        # Simulate agents with conversation buffers
        with patch.object(agent1, 'memory_manager', create=True) as mm1, \
             patch.object(agent2, 'memory_manager', create=True) as mm2:
            
            mm1.flush_buffer = MagicMock(return_value=3)
            mm2.flush_buffer = MagicMock(return_value=5)
            
            agents = {"agent_1": agent1, "agent_2": agent2}
            result = guard.flush_all_agent_buffers(agents)
            
            mm1.flush_buffer.assert_called_once()
            mm2.flush_buffer.assert_called_once()
            assert result["agent_1"]["flushed"] == 3
            assert result["agent_2"]["flushed"] == 5
            assert result["total_flushed"] == 8

    def test_flush_all_buffers_handles_missing_memory_manager(self, guard):
        """RED→GREEN: Agents without memory_manager are skipped gracefully."""
        agent = MagicMock()
        agent.config.agent_id = "no_mem"
        agent.memory_manager = None
        
        agents = {"no_mem": agent}
        result = guard.flush_all_agent_buffers(agents)
        
        assert result["no_mem"]["flushed"] == 0
        assert result["total_flushed"] == 0

    def test_flush_all_buffers_handles_exception(self, guard):
        """RED→GREEN: Exception in one agent doesn't block others."""
        agent1 = MagicMock()
        agent1.config.agent_id = "good_agent"
        agent2 = MagicMock()
        agent2.config.agent_id = "bad_agent"
        
        with patch.object(agent1, 'memory_manager', create=True) as mm1, \
             patch.object(agent2, 'memory_manager', create=True) as mm2:
            
            mm1.flush_buffer = MagicMock(return_value=10)
            mm2.flush_buffer = MagicMock(side_effect=RuntimeError("DB locked"))
            
            agents = {"good_agent": agent1, "bad_agent": agent2}
            result = guard.flush_all_agent_buffers(agents)
            
            assert result["good_agent"]["flushed"] == 10
            assert "error" in result["bad_agent"]
            assert result["total_flushed"] == 10


# ── Test 3: Session Recovery on Abnormal Startup ────────────

class TestSessionRecovery:
    """Tracer bullet: on abnormal shutdown, session files are scanned
    and missing memories are synced to storage."""

    def test_recover_no_sessions_when_no_session_dir(self, guard, temp_dir):
        """RED→GREEN: When no session directory exists, recovery returns empty."""
        crash_time = datetime.now(timezone.utc) - timedelta(hours=2)
        result = guard.recover_from_sessions(agents={}, crash_time=crash_time)
        
        assert result["recovered"] == 0
        assert result["errors"] == 0

    def test_recover_scans_session_files(self, guard, temp_dir):
        """RED→GREEN: Session files are scanned and messages after crash time are found."""
        # Create session directory with a session file
        session_dir = temp_dir / "agents" / "test_agent" / "session"
        session_dir.mkdir(parents=True, exist_ok=True)
        
        crash_time = datetime.now(timezone.utc) - timedelta(hours=1)
        
        # Session message timestamps: some before crash, some after
        session_data = {
            "agent_id": "test_agent",
            "session_id": "abc123",
            "session_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "messages": [
                {
                    "role": "user",
                    "content": "Message before crash",
                    "timestamp": (crash_time - timedelta(minutes=30)).isoformat(),
                },
                {
                    "role": "assistant",
                    "content": "Reply before crash",
                    "timestamp": (crash_time - timedelta(minutes=29)).isoformat(),
                },
                {
                    "role": "user",
                    "content": "Message after crash - unsaved",
                    "timestamp": (crash_time + timedelta(minutes=5)).isoformat(),
                },
                {
                    "role": "assistant",
                    "content": "Reply after crash - unsaved",
                    "timestamp": (crash_time + timedelta(minutes=6)).isoformat(),
                },
            ],
            "total_messages": 4,
            "created_at": (crash_time - timedelta(hours=2)).isoformat(),
            "updated_at": (crash_time + timedelta(minutes=6)).isoformat(),
        }
        
        session_file = session_dir / f"session_abc123_{session_data['session_date']}.json"
        session_file.write_text(json.dumps(session_data, ensure_ascii=False), encoding="utf-8")
        
        # Mock agent with memory_manager
        agent = MagicMock()
        agent.config.agent_id = "test_agent"
        
        with patch.object(agent, 'memory_manager', create=True) as mm:
            mm.remember = MagicMock(return_value="mem_recovered")
            
            agents = {"test_agent": agent}
            result = guard.recover_from_sessions(agents=agents, crash_time=crash_time)
            
            # Should find 2 messages after crash time
            assert result["recovered"] >= 2
            assert mm.remember.call_count >= 2

    def test_recover_deduplicates_existing_memories(self, guard, temp_dir):
        """RED→GREEN: Messages already in storage are not re-inserted (dedup)."""
        session_dir = temp_dir / "agents" / "test_agent_2" / "session"
        session_dir.mkdir(parents=True, exist_ok=True)
        
        crash_time = datetime.now(timezone.utc) - timedelta(hours=1)
        
        session_data = {
            "agent_id": "test_agent_2",
            "session_id": "xyz789",
            "session_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "messages": [
                {
                    "role": "user",
                    "content": "Already saved message",
                    "timestamp": (crash_time + timedelta(minutes=2)).isoformat(),
                },
                {
                    "role": "user",
                    "content": "New unsaved message",
                    "timestamp": (crash_time + timedelta(minutes=3)).isoformat(),
                },
            ],
            "total_messages": 2,
        }
        
        session_file = session_dir / f"session_xyz789_{session_data['session_date']}.json"
        session_file.write_text(json.dumps(session_data, ensure_ascii=False), encoding="utf-8")
        
        agent = MagicMock()
        agent.config.agent_id = "test_agent_2"
        
        with patch.object(agent, 'memory_manager', create=True) as mm:
            # Simulate: first message already exists in storage
            def remember_side_effect(content, **kwargs):
                if "Already saved" in content:
                    return None  # Duplicate → skip
                return "mem_new"
            
            mm.remember = MagicMock(side_effect=remember_side_effect)
            mm.search = MagicMock(return_value=[])
            
            agents = {"test_agent_2": agent}
            result = guard.recover_from_sessions(agents=agents, crash_time=crash_time)
            
            # Should attempt all messages but only count successful ones
            assert mm.remember.call_count == 2

    def test_recover_agent_isolation(self, guard, temp_dir):
        """RED→GREEN: Recovery respects agent isolation — only syncs to the correct agent."""
        session_dir = temp_dir / "agents" / "agent_A" / "session"
        session_dir.mkdir(parents=True, exist_ok=True)
        
        crash_time = datetime.now(timezone.utc) - timedelta(hours=1)
        
        session_data = {
            "agent_id": "agent_A",
            "session_id": "aaa111",
            "session_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "messages": [{
                "role": "user",
                "content": "Agent A's message",
                "timestamp": (crash_time + timedelta(minutes=2)).isoformat(),
            }],
            "total_messages": 1,
        }
        
        session_file = session_dir / f"session_aaa111_{session_data['session_date']}.json"
        session_file.write_text(json.dumps(session_data, ensure_ascii=False), encoding="utf-8")
        
        agent_A = MagicMock()
        agent_A.config.agent_id = "agent_A"
        agent_B = MagicMock()
        agent_B.config.agent_id = "agent_B"
        
        with patch.object(agent_A, 'memory_manager', create=True) as mm_A, \
             patch.object(agent_B, 'memory_manager', create=True) as mm_B:
            
            mm_A.remember = MagicMock(return_value="ok_A")
            mm_B.remember = MagicMock(return_value="ok_B")
            mm_A.flush_buffer = MagicMock(return_value=0)
            mm_B.flush_buffer = MagicMock(return_value=0)
            
            agents = {"agent_A": agent_A, "agent_B": agent_B}
            result = guard.recover_from_sessions(agents=agents, crash_time=crash_time)
            
            # Only agent_A should receive recovered memories
            assert mm_A.remember.call_count >= 1
            # agent_B should NOT receive agent_A's messages
            assert mm_B.remember.call_count == 0


# ── Test 4: Full Shutdown Flow ──────────────────────────────

class TestFullShutdownFlow:
    """Tracer bullet: the complete graceful shutdown flow works end-to-end."""

    def test_graceful_shutdown_flow(self, guard, temp_dir):
        """RED→GREEN: graceful_shutdown flushes buffers, then marks clean shutdown."""
        guard.write_sentinel()
        
        agent = MagicMock()
        agent.config.agent_id = "main"
        
        with patch.object(agent, 'memory_manager', create=True) as mm:
            mm.flush_buffer = MagicMock(return_value=42)
            
            agents = {"main": agent}
            result = guard.graceful_shutdown(agents)
            
            # Buffer was flushed
            mm.flush_buffer.assert_called_once()
            assert result["buffers_flushed"]["total_flushed"] == 42
            
            # Sentinel was removed
            sentinel = temp_dir / ".neurova_shutdown_sentinel"
            assert not sentinel.exists()
            assert result["clean_shutdown"] is True


# ── Test 5: Startup Recovery Flow ───────────────────────────

class TestStartupRecoveryFlow:
    """Tracer bullet: the complete startup flow handles both normal and crash scenarios."""

    def test_normal_startup(self, guard, temp_dir):
        """RED→GREEN: Normal startup writes sentinel, detects no crash, no recovery needed."""
        agent = MagicMock()
        agent.config.agent_id = "main"
        
        with patch.object(agent, 'memory_manager', create=True):
            agents = {"main": agent}
            result = guard.prepare_startup(agents)
        
        assert result["abnormal"] is False
        assert result["recovered_memories"] == 0
        assert result["sentinel_written"] is True

    def test_crash_recovery_startup(self, guard, temp_dir):
        """RED→GREEN: Crash startup writes new sentinel, detects crash, recovers."""
        # Simulate previous crash
        crash_time = datetime.now(timezone.utc) - timedelta(hours=1)
        sentinel = temp_dir / ".neurova_shutdown_sentinel"
        sentinel.write_text(json.dumps({
            "pid": 12345,
            "started_at": crash_time.isoformat(),
        }), encoding="utf-8")
        
        # Create session with messages after crash
        session_dir = temp_dir / "agents" / "main" / "session"
        session_dir.mkdir(parents=True, exist_ok=True)
        session_data = {
            "agent_id": "main",
            "session_id": "test123",
            "session_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "messages": [{
                "role": "user",
                "content": "Lost message",
                "timestamp": (crash_time + timedelta(minutes=5)).isoformat(),
            }],
            "total_messages": 1,
        }
        session_file = session_dir / f"session_test123_{session_data['session_date']}.json"
        session_file.write_text(json.dumps(session_data, ensure_ascii=False), encoding="utf-8")
        
        agent = MagicMock()
        agent.config.agent_id = "main"
        
        with patch.object(agent, 'memory_manager', create=True) as mm:
            mm.remember = MagicMock(return_value="recovered_ok")
            mm.flush_buffer = MagicMock(return_value=0)
            mm.search = MagicMock(return_value=[])
            
            agents = {"main": agent}
            result = guard.prepare_startup(agents)
        
        assert result["abnormal"] is True
        assert result["recovered_memories"] > 0
        assert result["sentinel_written"] is True
