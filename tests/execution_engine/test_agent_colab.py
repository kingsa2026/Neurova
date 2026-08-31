"""Tests for execution_engine/agent_colab.py - core scenarios."""
import threading

import pytest


class TestAgentCollaborationService:
    def test_init_with_storage_path(self, tmp_path):
        from neurova.execution_engine.agent_colab import AgentCollaborationService
        svc = AgentCollaborationService(str(tmp_path / "ac"))
        assert svc is not None

    def test_create_and_get_plan(self, tmp_path):
        from neurova.execution_engine.agent_colab import AgentCollaborationService
        svc = AgentCollaborationService(str(tmp_path / "ac"))
        pid = svc.create_plan(name="plan-a", strategy="sequential", description="d")
        assert isinstance(pid, str) and pid.startswith("pl_")
        plan = svc.get_plan(pid)
        assert plan is not None
        assert plan["name"] == "plan-a"
        assert plan["strategy"] == "sequential"
        assert plan["status"] == "planned"
        assert plan["assignments"] == []

    def test_list_plans_by_status(self, tmp_path):
        from neurova.execution_engine.agent_colab import AgentCollaborationService
        svc = AgentCollaborationService(str(tmp_path / "ac"))
        svc.create_plan(name="p1", strategy="sequential")
        svc.create_plan(name="p2", strategy="parallel")
        all_plans = svc.list_plans()
        assert len(all_plans) == 2
        planned = svc.list_plans(status="planned")
        assert len(planned) == 2
        assert svc.list_plans(status="completed") == []

    def test_add_and_get_assignment(self, tmp_path):
        from neurova.execution_engine.agent_colab import AgentCollaborationService
        svc = AgentCollaborationService(str(tmp_path / "ac"))
        pid = svc.create_plan(name="p", strategy="sequential")
        aid = svc.add_assignment(
            plan_id=pid,
            agent_id="agent-1",
            agent_role="worker",
            task_description="do thing",
            task_parameters={"x": 1},
            priority=5,
            dependencies=[],
        )
        assert isinstance(aid, str) and aid.startswith("as_")
        a = svc.get_assignment(pid, aid)
        assert a is not None
        assert a["agent_id"] == "agent-1"
        assert a["status"] == "pending"
        assert a["priority"] == 5
        listed = svc.list_assignments(pid)
        assert len(listed) == 1

    def test_update_assignment_status(self, tmp_path):
        from neurova.execution_engine.agent_colab import AgentCollaborationService
        svc = AgentCollaborationService(str(tmp_path / "ac"))
        pid = svc.create_plan(name="p", strategy="parallel")
        aid = svc.add_assignment(plan_id=pid, agent_id="a1", task_description="t")
        ok = svc.update_assignment(pid, aid, status="running", agent_id="a2")
        assert ok is True
        a = svc.get_assignment(pid, aid)
        assert a["status"] == "running"
        assert a["agent_id"] == "a2"
        bad = svc.update_assignment(pid, aid, status="bogus")
        assert bad is False

    def test_cancel_plan_cascades_assignments(self, tmp_path):
        from neurova.execution_engine.agent_colab import AgentCollaborationService
        svc = AgentCollaborationService(str(tmp_path / "ac"))
        pid = svc.create_plan(name="p", strategy="sequential")
        svc.add_assignment(plan_id=pid, agent_id="a1", task_description="t1")
        svc.add_assignment(plan_id=pid, agent_id="a2", task_description="t2")
        assert svc.cancel_plan(pid) is True
        plan = svc.get_plan(pid)
        assert plan["status"] == "cancelled"
        for a in plan["assignments"]:
            assert a["status"] == "cancelled"
        assert svc.cancel_plan(pid) is False

    def test_persistence_across_instances(self, tmp_path):
        from neurova.execution_engine.agent_colab import AgentCollaborationService
        d = str(tmp_path / "ac")
        svc1 = AgentCollaborationService(d)
        pid = svc1.create_plan(name="persist", strategy="pipeline")
        svc1.add_assignment(plan_id=pid, agent_id="a", task_description="t")
        svc2 = AgentCollaborationService(d)
        plan = svc2.get_plan(pid)
        assert plan is not None
        assert plan["name"] == "persist"
        assert len(plan["assignments"]) == 1

    def test_get_statistics(self, tmp_path):
        from neurova.execution_engine.agent_colab import AgentCollaborationService
        svc = AgentCollaborationService(str(tmp_path / "ac"))
        svc.create_plan(name="p1", strategy="sequential")
        pid2 = svc.create_plan(name="p2", strategy="parallel")
        aid = svc.add_assignment(plan_id=pid2, agent_id="a", task_description="t")
        svc.update_assignment(pid2, aid, status="completed", execution_time_ms=120.0)
        stats = svc.get_statistics()
        assert stats["total_plans"] == 2
        assert stats["total_assignments"] == 1
        assert stats["completed_assignments"] == 1
        assert stats["average_execution_time_ms"] == 120.0


class TestGetAgentCollaborationService:
    def test_returns_singleton(self):
        from neurova.execution_engine.agent_colab import get_agent_collaboration_service
        a = get_agent_collaboration_service()
        b = get_agent_collaboration_service()
        assert a is b
