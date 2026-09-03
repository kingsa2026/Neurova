"""Tests for neurova/cognitive/orchestrator.py — core scenarios only."""
import pytest


def _make_orchestrator(tmp_path, name="orch"):
    from neurova.cognitive.orchestrator import CognitionOrchestrator
    return CognitionOrchestrator(storage_dir=str(tmp_path / name))


class TestCognitionOrchestratorInit:
    def test_init_with_storage_path(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        assert orch is not None

    def test_init_no_agents(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        agents = orch.list_agents()
        assert isinstance(agents, list)
        assert len(agents) == 0

    def test_init_idle_cognitive_state(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        state = orch.get_cognitive_state()
        assert state is not None


class TestAgentRegistration:
    def test_register_agent(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        aid = orch.register_agent(name="planner", role="planner", capabilities=["plan", "reason"])
        assert isinstance(aid, str) and aid
        agents = orch.list_agents()
        assert len(agents) == 1
        assert agents[0]["name"] == "planner"
        assert agents[0]["role"] == "planner"
        assert "plan" in agents[0]["capabilities"]

    def test_deregister_agent(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        aid = orch.register_agent(name="worker", role="executor")
        assert orch.deregister_agent(aid) is True
        assert orch.deregister_agent(aid) is False
        assert len(orch.list_agents()) == 0

    def test_get_agent(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        aid = orch.register_agent(name="a1", role="r1")
        agent = orch.get_agent(aid)
        assert agent is not None
        assert agent["id"] == aid


class TestTaskSubmission:
    def test_submit_task_to_agent(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        aid = orch.register_agent(name="executor", role="executor")
        tid = orch.submit_task(agent_id=aid, name="step-1", payload={"x": 1})
        assert isinstance(tid, str) and tid
        task = orch.get_task(tid)
        assert task is not None
        assert task["agent_id"] == aid
        assert task["name"] == "step-1"

    def test_submit_task_unknown_agent_raises(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        with pytest.raises((KeyError, ValueError)):
            orch.submit_task(agent_id="missing", name="step", payload={})


class TestOrchestratePipeline:
    def test_orchestrate_sequence(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        a1 = orch.register_agent(name="step1", role="r")
        a2 = orch.register_agent(name="step2", role="r")
        result = orch.orchestrate(
            pipeline=[
                {"agent_id": a1, "name": "first", "payload": {"n": 1}},
                {"agent_id": a2, "name": "second", "payload": {"n": 2}},
            ]
        )
        assert isinstance(result, dict)
        assert result.get("status") in ("completed", "success", "done")
        tasks = result.get("tasks") or []
        assert len(tasks) == 2

    def test_orchestrate_propagates_error(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        a1 = orch.register_agent(name="boom", role="r")
        a2 = orch.register_agent(name="ok", role="r")
        result = orch.orchestrate(
            pipeline=[
                {"agent_id": a1, "name": "fail", "payload": {"raise": True}},
                {"agent_id": a2, "name": "never", "payload": {}},
            ]
        )
        assert isinstance(result, dict)
        assert result.get("status") in ("failed", "error")
        assert result.get("error")


class TestStatusTracking:
    def test_task_status_progression(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        aid = orch.register_agent(name="w", role="r")
        tid = orch.submit_task(agent_id=aid, name="t", payload={})
        task = orch.get_task(tid)
        assert task["status"] in ("pending", "running", "completed", "failed")

    def test_update_task_status(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        aid = orch.register_agent(name="w", role="r")
        tid = orch.submit_task(agent_id=aid, name="t", payload={})
        ok = orch.update_task_status(tid, "running")
        assert ok is True
        assert orch.get_task(tid)["status"] == "running"

    def test_list_tasks_by_agent(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        a1 = orch.register_agent(name="a", role="r")
        a2 = orch.register_agent(name="b", role="r")
        orch.submit_task(agent_id=a1, name="t1", payload={})
        orch.submit_task(agent_id=a1, name="t2", payload={})
        orch.submit_task(agent_id=a2, name="t3", payload={})
        a1_tasks = orch.list_tasks(agent_id=a1)
        assert len(a1_tasks) == 2


class TestErrorPropagation:
    def test_task_failure_marked(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        aid = orch.register_agent(name="err", role="r")
        tid = orch.submit_task(agent_id=aid, name="bad", payload={"raise": True})
        task = orch.get_task(tid)
        assert task["status"] == "failed"
        assert task.get("error")


class TestPersistence:
    def test_state_persists_across_instances(self, tmp_path):
        store = tmp_path / "persist"
        a = _make_orchestrator(tmp_path, name=str(store))
        aid = a.register_agent(name="persistme", role="r")
        tid = a.submit_task(agent_id=aid, name="t", payload={"k": "v"})

        b = _make_orchestrator(tmp_path, name=str(store))
        agents = b.list_agents()
        assert any(ag["id"] == aid for ag in agents)
        task = b.get_task(tid)
        assert task is not None
        assert task["name"] == "t"


class TestAttentionManager:
    def test_set_and_get_attention(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        am = orch.get_attention_manager()
        am.set_attention("focus-1", level="high", weight=0.9)
        record = am.get_attention("focus-1")
        assert record is not None
        assert record["level"] == "high"
        assert record["weight"] == 0.9

    def test_should_switch_attention_returns_bool(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        am = orch.get_attention_manager()
        am.set_attention("a", level="low", weight=0.1)
        am.set_attention("b", level="high", weight=0.9)
        decision = am.should_switch_attention("a", "b")
        assert isinstance(decision, bool)


class TestMemoryManager:
    def test_add_and_retrieve_memory(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        mm = orch.get_memory_manager()
        mid = mm.add_memory(content="hello", memory_type="short_term", tags=["greeting"])
        assert isinstance(mid, str) and mid
        mem = mm.retrieve_memory(mid)
        assert mem is not None
        assert mem["content"] == "hello"

    def test_get_memories_by_type(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        mm = orch.get_memory_manager()
        mm.add_memory(content="a", memory_type="long_term")
        mm.add_memory(content="b", memory_type="long_term")
        mm.add_memory(content="c", memory_type="short_term")
        long = mm.get_memories_by_type("long_term")
        assert isinstance(long, list)
        assert len(long) == 2

    def test_clear_memories(self, tmp_path):
        orch = _make_orchestrator(tmp_path)
        mm = orch.get_memory_manager()
        mm.add_memory(content="x", memory_type="working")
        removed = mm.clear_memories(memory_type="working")
        assert isinstance(removed, int)
        assert removed >= 1


class TestSingleton:
    def test_get_cognition_orchestrator_returns_singleton(self, tmp_path, monkeypatch):
        from neurova.cognitive import orchestrator as orch_mod
        monkeypatch.setattr(orch_mod, "_DEFAULT_DIR", str(tmp_path / "singleton"))
        monkeypatch.setattr(orch_mod, "_singleton", None)
        a = orch_mod.get_cognition_orchestrator()
        b = orch_mod.get_cognition_orchestrator()
        assert a is b
