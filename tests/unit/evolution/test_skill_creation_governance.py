"""Automatic creation must use persisted, independent execution evidence."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.asyncio
async def test_create_skill_cannot_self_attest(tmp_path, monkeypatch):
    from neurova.tool_executor import ToolExecutor
    from neurova.skills.skill_service import SkillService
    service = SkillService(agent_id="isolated", skills_dir=str(tmp_path))
    monkeypatch.setattr("neurova.skills.skill_service.SkillService", lambda **kw: service)
    registry = Mock()
    agent = SimpleNamespace(config=SimpleNamespace(agent_id="isolated"), _skill_registry=registry)
    result = await ToolExecutor(agent)._execute_create_skill({
        "name": "invented", "description": "read report",
        "steps": [{"name": "file_read", "params": {"path": "report.txt"}}],
        "source": "manual", "success_count": 100, "source_key": "claimed",
    })
    assert result.get("success") is not True
    registry.register_skill.assert_not_called()
    assert service.list_skills() == []


def test_anonymous_observations_do_not_create_templates():
    from neurova.evolution.skill_encapsulation import AutoSkillBuilder
    builder = AutoSkillBuilder(min_pattern_occurrences=1, min_independent_successes=1)
    for _ in range(5):
        builder.observe(["read", "save"], context="report", success=True)
    assert builder.get_all_templates() == []


def service_at(tmp_path, agent="a"):
    from neurova.skills.skill_service import SkillService
    return SkillService(agent_id=agent, skills_dir=str(tmp_path))


STEPS = [{"tool": "file_read", "params": {"path": "report.txt"}},
         {"tool": "file_write", "params": {"path": "out.txt"}}]


def seed(service, steps=STEPS, purpose="report", count=3):
    for index in range(count):
        service.creation_evidence.record(f"task-{index}", steps, purpose, True)


def test_three_tasks_restart_and_sticky_failure(tmp_path):
    service = service_at(tmp_path)
    seed(service, count=2)
    service.creation_evidence.record("task-0", STEPS, "report", True)
    assert not service.creation_evidence.eligible(STEPS)
    service.creation_evidence.record("failed", STEPS, "report", False)
    service.creation_evidence.record("failed", STEPS, "report", True)
    assert not service.creation_evidence.eligible(STEPS)
    service.creation_evidence.record("third", STEPS, "report", True)
    restarted = service_at(tmp_path)
    assert restarted.creation_evidence.eligible(STEPS)
    assert not service_at(tmp_path, "b").creation_evidence.eligible(STEPS)


def test_creation_dedupes_across_instances_and_manual_install(tmp_path):
    import json
    service = service_at(tmp_path / "library")
    seed(service)
    first = service.create_automatic_skill("one", "first", "report", {"tool_sequence": STEPS})
    assert first["success"]
    second = service_at(tmp_path / "library").create_automatic_skill(
        "two", "renamed", "other name", {"tool_sequence": STEPS})
    assert second == {"success": True, "duplicate": True, "skill_id": "one"}
    stage = tmp_path / "incoming"
    stage.mkdir()
    (stage / "manifest.json").write_text(json.dumps({
        "id": "manual", "name": "manual", "config": {"tool_sequence": STEPS}}))
    assert service.install_skill(str(stage))["skill_id"] == "one"
    assert not (service.skills_dir / "manual").exists()
    assert len(service.list_skills()) == 1


def test_fingerprint_keeps_order_repetitions_parameters_and_bare_purpose():
    from neurova.skills.creation_governance import fingerprint
    assert fingerprint(STEPS) != fingerprint(STEPS[::-1])
    assert fingerprint(STEPS) != fingerprint(STEPS + STEPS[:1])
    assert fingerprint(STEPS) != fingerprint([{"tool": "file_read", "params": {"path": "other.txt"}}, STEPS[1]])
    assert fingerprint(["read", "write"], "report") != fingerprint(["read", "write"], "invoice")
    assert fingerprint(["read", "write"], " Report ") == fingerprint([
        {"name": "read", "params": {}}, {"tool": "write", "params": {}}], "report")


def test_builder_uses_persisted_evidence_not_observer_claims(tmp_path):
    from neurova.evolution.skill_encapsulation import AutoSkillBuilder
    service = service_at(tmp_path)
    builder = AutoSkillBuilder(min_pattern_occurrences=1, evidence_store=service.creation_evidence)
    for i in range(6):
        builder.observe(STEPS, context="report", metadata={"source_key": f"fake-{i}"})
    assert builder.get_all_templates() == []
    seed(service)
    builder.observe(STEPS, context="report", metadata={"source_key": "task-2"})
    assert len(builder.get_all_templates()) == 1
    pattern = next(iter(builder._patterns.values()))
    assert pattern.total_uses == 3
    builder.observe(STEPS, context="report", metadata={"source_key": "task-2"})
    assert pattern.total_uses == 3
    restored = AutoSkillBuilder.from_dict(builder.to_dict())
    assert next(iter(restored._patterns.values())).source_evidence == pattern.source_evidence


def test_runtime_registry_deduplicates_same_steps(tmp_path):
    from neurova.skill_system import SkillRegistry
    registry = SkillRegistry()
    for name in ("one", "two"):
        assert registry.register_skill(SimpleNamespace(id=name, name=name,
            description="report", config={"tool_sequence": STEPS}))
    assert registry.get_skill_names() == ["one"]


def test_concurrent_creation_is_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    service = service_at(tmp_path)
    seed(service)
    def create(i):
        return service_at(tmp_path).create_automatic_skill(
            f"skill-{i}", f"name-{i}", "report", {"tool_sequence": STEPS})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(create, range(8)))
    assert all(r["success"] for r in results)
    assert len({r["skill_id"] for r in results}) == 1
    assert len(service_at(tmp_path).list_skills()) == 1


@pytest.mark.asyncio
async def test_historical_pattern_mining_never_feeds_success():
    from neurova.post_chat_pipeline import PostChatPipeline
    from unittest.mock import MagicMock
    agent = MagicMock()
    agent._collect_tool_messages.return_value = [{"tool_name": "read"}, {"tool_name": "save"}]
    miner = agent.evolution.pattern_miner
    miner.mine.return_value = [{"tools": ["read", "save"]}]
    miner.to_skill_template_list.return_value = [{"tools": ["read", "save"]}]
    pipeline = PostChatPipeline(agent)
    pipeline._get_dependency = lambda key: getattr(agent, key)
    await pipeline._step_pattern_mining()
    agent.skill_packer.observe.assert_not_called()
    agent.skill_packer.register_to_skill_registry.assert_not_called()
    miner.mine.assert_called_once()


def test_agent_router_initialization_restores_pending(monkeypatch):
    from neurova.agent_core import Agent
    from neurova.skills.skill_service import SkillService
    from neurova.evolution.skill_encapsulation import AutoSkillBuilder
    monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "1")
    service = SkillService(agent_id="restart-agent")
    seed(service)
    builder = AutoSkillBuilder(evidence_store=service.creation_evidence)
    builder.observe(STEPS, context="report", metadata={"source_key": "task-2"})
    builder.register_to_skill_registry(Mock(), service)
    expected, = builder.list_pending_templates()
    agent = SimpleNamespace(
        config=SimpleNamespace(agent_id="restart-agent", name="restart-agent",
                               enable_active_skill_acquisition=False, enable_skill_packer=True),
        _skill_registry=Mock(), memory_manager=None, tool_memory=None)
    monkeypatch.setattr("neurova.router.create_default_router", Mock())
    Agent.init_router(agent)
    assert agent.skill_packer.list_pending_templates() == [expected]


def test_rejected_template_stays_rejected_after_restart(tmp_path, monkeypatch):
    from neurova.evolution.skill_encapsulation import AutoSkillBuilder
    monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "1")
    service = service_at(tmp_path)
    seed(service)
    builder = AutoSkillBuilder(evidence_store=service.creation_evidence)
    builder.observe(STEPS, context="report", metadata={"source_key": "task-2"})
    builder.register_to_skill_registry(Mock(), service)
    template, = builder.get_all_templates()
    assert builder.reject_template(template.template_id)
    restarted = AutoSkillBuilder(evidence_store=service_at(tmp_path).creation_evidence)
    assert restarted.list_pending_templates() == []


def test_pending_template_survives_restart_and_approval(tmp_path, monkeypatch):
    from neurova.evolution.skill_encapsulation import AutoSkillBuilder
    from neurova.skill_system import SkillRegistry
    monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "1")
    service = service_at(tmp_path)
    seed(service)
    builder = AutoSkillBuilder(evidence_store=service.creation_evidence)
    builder.observe(STEPS, context="report", metadata={"source_key": "task-2"})
    builder.register_to_skill_registry(SkillRegistry(), service)
    template, = builder.get_all_templates()
    assert service.get_skill_info(template.template_id)["enabled"] is False

    restarted_service = service_at(tmp_path)
    restarted = AutoSkillBuilder(evidence_store=restarted_service.creation_evidence)
    pending, = restarted.list_pending_templates()
    assert pending["template_id"] == template.template_id
    assert pending["tool_sequence"] == STEPS
    assert restarted.approve_template(template.template_id)
    assert service_at(tmp_path).get_skill_info(template.template_id)["enabled"] is True
    assert AutoSkillBuilder(evidence_store=service_at(tmp_path).creation_evidence).list_pending_templates() == []


def test_real_collector_finish_approve_registration(tmp_path, monkeypatch):
    from neurova.skills.creation_governance import begin_task, record_tool_execution, finish_task
    from neurova.evolution.skill_encapsulation import AutoSkillBuilder
    from neurova.skill_system import SkillRegistry
    from neurova.skill_system_module_standalone import SkillStatus
    service = service_at(tmp_path)
    monkeypatch.setattr("neurova.skills.skill_service.SkillService", lambda **kw: service)
    monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "1")
    builder = AutoSkillBuilder()
    agent = SimpleNamespace(config=SimpleNamespace(agent_id="a"), skill_packer=builder,
                            _skill_registry=SkillRegistry())
    for i in range(3):
        begin_task()
        for step in STEPS:
            record_tool_execution(step["tool"], step["params"], True, {"ok": True})
        finish_task(agent, "report", True)
        if i < 2:
            assert builder.get_all_templates() == []
    template, = builder.get_all_templates()
    assert service.get_skill_info(template.template_id)["enabled"] is False
    assert builder.approve_template(template.template_id)
    builder.register_to_skill_registry(agent._skill_registry, service)
    assert service.get_skill_info(template.template_id)["enabled"] is True
    assert agent._skill_registry.get_skill(template.name).status == SkillStatus.ACTIVE
    builder.register_to_skill_registry(agent._skill_registry, service)
    assert agent._skill_registry.get_skill(template.name).status == SkillStatus.ACTIVE


@pytest.mark.asyncio
async def test_stream_without_terminal_stop_is_not_task_success():
    from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
    from unittest.mock import AsyncMock
    async def events():
        yield {"type": "content", "data": "partial response"}
        yield {"type": "done", "finish_reason": "length"}
    agent = SimpleNamespace(loop=SimpleNamespace(predict_step=AsyncMock(return_value=events())))
    pipeline = object.__new__(ChatPipeline)
    pipeline._agent = agent
    ctx = ChatContext(user_input="report")
    await pipeline._call_loop_stream(ctx, [])
    assert ctx.execution_completed is False


def test_collector_finish_is_terminal_and_counts_failures(tmp_path):
    from neurova.skills.creation_governance import begin_task, record_tool_execution, flush_task
    service = service_at(tmp_path)
    begin_task()
    for step in STEPS:
        record_tool_execution(step["tool"], step["params"], True, {"ok": True})
    first = flush_task(service, "report", False)
    assert first["success"] is False
    assert flush_task(service, "report", True) is None
    record_tool_execution("late_tool", {}, True, {"ok": True})
    assert flush_task(service, "report", True) is None
    assert list(service.creation_evidence.task_results(STEPS).values()) == [0]


def test_empty_task_finish_closes_child_context(tmp_path):
    from contextvars import copy_context
    from neurova.skills import creation_governance as cg
    service = service_at(tmp_path)
    cg.begin_task()
    child = copy_context()
    cg.finish_task(SimpleNamespace(config=SimpleNamespace(agent_id="a")), "report", False)
    child.run(cg.record_tool_execution, "late", {"value": 1}, True, {"ok": True})
    assert child.run(cg.flush_task, service, "report", True) is None


def test_finalized_collector_rejects_late_child_context(tmp_path):
    from contextvars import copy_context
    from neurova.skills import creation_governance as cg
    service = service_at(tmp_path)
    cg.begin_task()
    child = copy_context()
    for step in STEPS:
        cg.record_tool_execution(step["tool"], step["params"], True, {"ok": True})
    record = cg.flush_task(service, "report", True)
    child.run(cg.record_tool_execution, "late", {"value": 1}, True, {"ok": True})
    assert child.run(cg.flush_task, service, "report", True) is None
    assert service.creation_evidence.task_results(STEPS) == {record["source_key"]: 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["_step_llm_call", "_step_post_processing"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_pipeline_interruption_records_failure(tmp_path, monkeypatch, stage, cancelled):
    import asyncio
    from unittest.mock import AsyncMock
    from neurova.agent.chat_pipeline import ChatPipeline, ChatContext
    from neurova.skills import creation_governance as cg

    service = service_at(tmp_path)
    monkeypatch.setattr("neurova.skills.skill_service.SkillService", lambda **kw: service)
    pipeline = object.__new__(ChatPipeline)
    pipeline._agent = SimpleNamespace(config=SimpleNamespace(agent_id="a"), skill_packer=None)
    def initialize(ctx):
        cg.begin_task()
        for step in STEPS:
            cg.record_tool_execution(step["tool"], step["params"], True, {"ok": True})
    monkeypatch.setattr(pipeline, "_init_agent_state", initialize)
    for name in ("_step_activity_tracking", "_step_pre_llm_checks", "_step_inject_attachments",
                 "_step_retrieve_and_build_context", "_step_llm_call", "_step_post_processing",
                 "_sync_final_reply"):
        monkeypatch.setattr(pipeline, name, AsyncMock())
    monkeypatch.setattr(pipeline, "_flush_vision_attachments", Mock())
    monkeypatch.setattr(pipeline, "_step_evocate_injection", Mock())
    error = asyncio.CancelledError if cancelled else RuntimeError
    monkeypatch.setattr(pipeline, stage, AsyncMock(side_effect=error("interrupted")))
    ctx = ChatContext(user_input="report", reply="finished text", execution_completed=True)
    try:
        with pytest.raises(error):
            await pipeline.execute(ctx)
        assert list(service.creation_evidence.task_results(STEPS).values()) == [0]
        assert cg.flush_task(service, "report", True) is None
    finally:
        cg.flush_task(service, "report", False)


def test_parameter_identity_and_unknown_sequence_matching(tmp_path):
    from neurova.evolution.skill_encapsulation import AutoSkillBuilder, ToolPattern, SkillTemplate
    builder = AutoSkillBuilder()
    first = ToolPattern(pattern_id="one", tool_sequence=STEPS)
    second = ToolPattern(pattern_id="two", tool_sequence=[STEPS[1], STEPS[0]])
    assert builder._generate_skill_name(first) != builder._generate_skill_name(second)
    changed = ToolPattern(pattern_id="three", tool_sequence=[
        {"tool": "file_read", "params": {"path": "different.txt"}}, STEPS[1]])
    assert builder._generate_skill_name(first) != builder._generate_skill_name(changed)
    template = SkillTemplate(tool_sequence=STEPS)
    assert builder._pattern_skill_similarity(first, template) == 1
    assert builder._pattern_skill_similarity(changed, template) == 0
    assert builder._calculate_match_score(SkillTemplate(tool_sequence=["a", "b"]), [], ["x", "y"]) == 0


def test_review_state_survives_restart_and_duplicate_publish(tmp_path, monkeypatch):
    from neurova.skills.creation_governance import publish_automatic
    from neurova.skill_system import SkillRegistry
    monkeypatch.setenv("NEUROVA_SKILL_REVIEW_GATE", "1")
    service = service_at(tmp_path)
    seed(service)
    manifest = SimpleNamespace(id="review", name="review", description="report",
                               config={"tool_sequence": STEPS})
    registry = SkillRegistry()
    assert publish_automatic(service, registry, manifest)["success"]
    restarted = service_at(tmp_path)
    assert restarted.get_skill_info("review")["enabled"] is False
    assert restarted.enable_skill("review")["success"]
    assert publish_automatic(service_at(tmp_path), registry, manifest)["duplicate"]
    assert service_at(tmp_path).get_skill_info("review")["enabled"] is True
    from neurova.skill_system_module_standalone import SkillStatus
    assert registry.get_skill("review").status == SkillStatus.ACTIVE


def test_persistence_failure_never_registers_runtime(tmp_path, monkeypatch):
    from neurova.skills.creation_governance import publish_automatic
    service = service_at(tmp_path)
    seed(service)
    monkeypatch.setattr(service, "_save_manifest", lambda: False)
    registry = Mock()
    result = publish_automatic(service, registry, SimpleNamespace(
        id="failed", name="failed", description="report", config={"tool_sequence": STEPS}))
    assert result["success"] is False
    registry.register_skill.assert_not_called()
    assert service.list_skills() == []
