"""Only actual tool execution, not repeated learning callbacks, creates evidence."""
from contextlib import nullcontext
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.mark.asyncio
async def test_learning_callback_cannot_poison_or_duplicate_execution(tmp_path, monkeypatch):
    from neurova.skills import creation_governance as governance
    from neurova.skills.skill_service import SkillService
    from neurova.tool_executor import ToolExecutor

    service = SkillService(agent_id="boundary", skills_dir=str(tmp_path))
    monkeypatch.setattr(governance, "_execution", ContextVar("boundary", default=None))
    monkeypatch.setattr("neurova.cognitive_layers.meta_cognition_layer.self_model.get_self_model_engine", Mock())
    monkeypatch.setattr("neurova.core.metrics.get_metrics", Mock())
    monkeypatch.setattr("neurova.agent.tool_pipeline.notify_tool_result", Mock())
    executor = ToolExecutor(SimpleNamespace(config=SimpleNamespace(agent_id="boundary")))
    monkeypatch.setattr(executor, "_agent_identity", lambda: ("test", "boundary"))
    monkeypatch.setattr(executor, "_governance_precheck", AsyncMock(return_value=None))
    monkeypatch.setattr(executor, "_metacog_gate_check", lambda name: None)
    monkeypatch.setattr(executor, "_sandbox_scope", lambda *args: nullcontext())
    monkeypatch.setattr("neurova.security.tool_param_guard.get_param_guard", lambda: None)
    monkeypatch.setattr("neurova.security.tool_arg_validator.validation_enabled", lambda: False)
    monkeypatch.setattr("neurova.security.monotonic_guard.get_monotonic_guards",
                        lambda: SimpleNamespace(check_all=lambda *args: None))

    async def core(name, params):
        executor.on_tool_executed(name, params, "report", True, "skill_system")
        return "report contents", True, "skill_system"

    async def run(name, operation, **kwargs):
        return await operation

    monkeypatch.setattr(executor, "_execute_tool_core", core)
    monkeypatch.setattr(executor.tool_coordinator, "run_with_timeout", run)
    governance.begin_task()
    assert await executor._execute_single_tool_inner("read_report", {}) == "report contents"
    evidence = governance.flush_task(service, "report", True)
    assert evidence["success"] is True
    assert evidence["steps"] == [{"tool": "read_report", "params": {}}]
    assert len(service.creation_evidence.success_tasks(evidence["steps"], "report")) == 1
