"""Creation returns the stored skill identity when a proposal is renamed."""
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_renamed_create_skill_returns_canonical_identity(tmp_path, monkeypatch):
    from neurova.skills.skill_service import SkillService
    from neurova.skill_system import SkillRegistry
    from neurova.tool_executor import ToolExecutor

    service = SkillService(agent_id="canonical", skills_dir=str(tmp_path))
    monkeypatch.setattr("neurova.skills.skill_service.SkillService", lambda **kw: service)
    monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "0")
    steps = [{"name": "file_read", "params": {"path": "report.txt"}}]
    for index in range(3):
        service.creation_evidence.record(f"completed-{index}", steps, "report", True)
    registry = SkillRegistry()
    executor = ToolExecutor(SimpleNamespace(
        config=SimpleNamespace(agent_id="canonical"), _skill_registry=registry))
    first = await executor._execute_create_skill({
        "name": "read_report", "description": "report", "steps": steps})
    second = await executor._execute_create_skill({
        "name": "renamed_report", "description": "report", "steps": steps})
    assert first["success"] is True
    assert second["success"] is True
    assert second["duplicate"] is True
    assert second["skill_id"] == first["skill_id"]
    assert second["skill_name"] == first["skill_name"]
    assert len(service.list_skills()) == 1
    assert registry.get_skill_names() == [first["skill_name"]]


@pytest.mark.asyncio
async def test_completed_task_lifecycle_enforces_three_successes(tmp_path, monkeypatch):
    from contextvars import ContextVar
    from neurova.skills import creation_governance as governance
    from neurova.skills.skill_service import SkillService
    from neurova.skill_system import SkillRegistry
    from neurova.tool_executor import ToolExecutor

    service = SkillService(agent_id="lifecycle", skills_dir=str(tmp_path))
    monkeypatch.setattr("neurova.skills.skill_service.SkillService", lambda **kw: service)
    monkeypatch.setattr(governance, "_execution", ContextVar("test_creation_task", default=None))
    registry = SkillRegistry()
    agent = SimpleNamespace(config=SimpleNamespace(agent_id="lifecycle"), _skill_registry=registry)
    executor = ToolExecutor(agent)
    proposal = {"name": "read_report", "description": "report",
                "steps": [{"name": "file_read", "params": {"path": "report.txt"}}]}

    async def create():
        return await executor._execute_create_skill(proposal)

    assert (await create())["code"] == "insufficient_evidence"
    for completed, tool_success in ((False, True), (True, False)):
        governance.begin_task()
        governance.record_tool_execution("file_read", {"path": "report.txt"}, tool_success,
                                         {"success": tool_success})
        governance.finish_task(agent, "report", completed)
    assert (await create())["code"] == "insufficient_evidence"
    for count in range(1, 4):
        governance.begin_task()
        governance.record_tool_execution("file_read", {"path": "report.txt"}, True, {"text": "report"})
        governance.finish_task(agent, "report", True)
        governance.finish_task(agent, "report", True)
        assert len(service.creation_evidence.success_tasks(proposal["steps"], "report")) == count
        result = await create()
        if count < 3:
            assert result["code"] == "insufficient_evidence"
            assert service.list_skills() == []
        else:
            assert result["success"] is True
            assert len(service.list_skills()) == 1
