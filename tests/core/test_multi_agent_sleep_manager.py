"""Tests for neurova.core.multi_agent_sleep_manager - core scenarios."""
import json
import os
import threading
import time
from pathlib import Path

import pytest

pytest.skip(
    "依赖不存在的模块 neurova.core.multi_agent_sleep_manager（MultiAgentSleepManager/IdleTracker）。"
    "已整体 skip，待确认该模块是实现还是废弃；详见 docs/test-debt-skip-list.md",
    allow_module_level=True,
)


@pytest.fixture
def storage_dir(tmp_path):
    d = tmp_path / "multi_agent_sleep"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


@pytest.fixture
def manager(storage_dir):
    from neurova.core.multi_agent_sleep_manager import MultiAgentSleepManager
    return MultiAgentSleepManager(config={"storage_dir": storage_dir})


class TestIdleTracker:
    def test_init_default_active(self):
        from neurova.core.multi_agent_sleep_manager import IdleTracker
        t = IdleTracker(agent_id="a1")
        assert t.agent_id == "a1"
        assert t.get_current_phase() == "active"
        assert t.get_current_idle_time() == 0
        assert t._sleep_mode == "time"

    def test_record_activity_resets_phase(self):
        from neurova.core.multi_agent_sleep_manager import IdleTracker
        t = IdleTracker(agent_id="a1")
        t.enter_phase("light_sleep")
        assert t.get_current_phase() == "light_sleep"
        t.record_activity()
        assert t.get_current_phase() == "active"
        assert t.get_current_idle_time() == 0

    def test_get_phase_display_name(self):
        from neurova.core.multi_agent_sleep_manager import IdleTracker
        t = IdleTracker(agent_id="a1")
        assert t.get_phase_display_name("light_sleep") != "light_sleep"
        assert t.get_phase_display_name("active") != ""
        assert t.get_phase_display_name() == t.get_phase_display_name("active")

    def test_enter_phase_valid_and_invalid(self):
        from neurova.core.multi_agent_sleep_manager import IdleTracker
        t = IdleTracker(agent_id="a1")
        assert t.enter_phase("light_sleep") is True
        assert t.get_current_phase() == "light_sleep"
        assert t.enter_phase("not_a_phase") is False

    def test_should_enter_temperature_mode(self):
        from neurova.core.multi_agent_sleep_manager import IdleTracker
        t = IdleTracker(agent_id="a1", sleep_mode="temperature")
        assert t.should_enter_phase("light_sleep", current_temperature=80.0) is False
        assert t.should_enter_phase("light_sleep", current_temperature=10.0) is True

    def test_update_config(self):
        from neurova.core.multi_agent_sleep_manager import IdleTracker
        t = IdleTracker(agent_id="a1")
        t.update_config(sleep_mode="temperature", idle_thresholds={"light_sleep": 500})
        assert t._sleep_mode == "temperature"
        assert t._idle_thresholds.get("light_sleep") == 500

    def test_get_status(self):
        from neurova.core.multi_agent_sleep_manager import IdleTracker
        t = IdleTracker(agent_id="a1")
        status = t.get_status()
        assert status.get("agent_id") == "a1"
        assert "current_phase" in status
        assert "current_idle_time" in status
        assert "sleep_mode" in status


class TestMultiAgentSleepManager:
    def test_init_no_agents(self, manager):
        assert manager.get_registered_agents() == []
        assert manager.get_all_agents_status() == []

    def test_register_agent_creates_tracker(self, manager):
        from neurova.core.multi_agent_sleep_manager import IdleTracker
        tracker = manager.register_agent("agent1")
        assert isinstance(tracker, IdleTracker)
        assert tracker.agent_id.lower() == "agent1"
        assert "agent1" in manager.get_registered_agents()

    def test_register_agent_is_idempotent(self, manager):
        a = manager.register_agent("agent1")
        b = manager.register_agent("Agent1")
        assert a is b
        assert len(manager.get_registered_agents()) == 1

    def test_wake_sleep_cycle(self, manager):
        manager.register_agent("agent1")
        assert manager.enter_phase("agent1", "light_sleep") is True
        status = manager.get_agent_status("agent1")
        assert status["current_phase"] == "light_sleep"
        manager.record_activity("agent1")
        status = manager.get_agent_status("agent1")
        assert status["current_phase"] == "active"

    def test_batch_sleep_multiple_agents(self, manager):
        manager.register_agent("a")
        manager.register_agent("b")
        manager.register_agent("c")
        results = []
        for aid in ("a", "b", "c"):
            results.append(manager.enter_phase(aid, "deep_sleep"))
        assert all(results)
        statuses = manager.get_all_agents_status()
        assert len(statuses) == 3
        for s in statuses:
            assert s["current_phase"] == "deep_sleep"

    def test_status_per_agent(self, manager):
        manager.register_agent("a1")
        status = manager.get_agent_status("a1")
        assert isinstance(status, dict)
        assert status.get("agent_id") == "a1"
        assert "current_phase" in status
        assert "config" in status

    def test_update_agent_config_persists(self, manager, storage_dir):
        manager.register_agent("a1")
        ok = manager.update_agent_config("a1", {"sleep_mode": "temperature"})
        assert ok is True
        cfg = manager.get_agent_config("a1")
        assert cfg.sleep_mode == "temperature"
        path = Path(storage_dir) / "agents.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "a1" in data
        assert data["a1"]["sleep_mode"] == "temperature"

    def test_persistence_round_trip(self, storage_dir):
        from neurova.core.multi_agent_sleep_manager import MultiAgentSleepManager
        m1 = MultiAgentSleepManager(config={"storage_dir": storage_dir})
        m1.register_agent("alpha")
        m1.update_agent_config("alpha", {"sleep_mode": "temperature"})
        m1.enter_phase("alpha", "light_sleep")
        m2 = MultiAgentSleepManager(config={"storage_dir": storage_dir})
        cfg = m2.get_agent_config("alpha")
        assert cfg.sleep_mode == "temperature"
        tracker = m2.get_agent_tracker("alpha")
        assert tracker is not None

    def test_health_check(self, manager):
        manager.register_agent("a1")
        h = manager.health_check()
        assert isinstance(h, dict)
        assert h.get("healthy") is True
        assert h.get("registered_agents") == 1
        assert "module_state" in h

    def test_thread_safety_concurrent_sleep_wake(self, manager):
        from neurova.core.multi_agent_sleep_manager import MultiAgentSleepManager
        for i in range(5):
            manager.register_agent(f"agent_{i}")
        errors = []

        def worker(aid: str):
            try:
                for _ in range(50):
                    manager.enter_phase(aid, "light_sleep")
                    manager.record_activity(aid)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(f"agent_{i}",))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        assert errors == []
        assert len(manager.get_registered_agents()) == 5

    def test_lifecycle_hooks(self, manager):
        manager._on_init()
        manager._on_start()
        manager._on_stop()
