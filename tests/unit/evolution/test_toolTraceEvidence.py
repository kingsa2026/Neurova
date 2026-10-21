"""完整工具 trace：技能边界采集 → 失败证据落盘 → 变异器提示消费。"""

from types import SimpleNamespace

import pytest

from neurova.core.tool_trace import recordToolTrace
from neurova.skill_system.core import Skill, SkillEvent, SkillRegistry, SkillResult


class _TracingSkill(Skill):
    def __init__(self):
        super().__init__(name="trace-skill", description="trace")

    async def execute(self, params, context=None):
        recordToolTrace("inner_tool", {"q": "北京"}, success=True, duration_ms=2.0, layer="test")
        return SkillResult(success=False, error="inner failed", data={"x": 1})


@pytest.mark.asyncio
async def test_skill_boundary_carries_tool_trace_to_post_execute():
    registry = SkillRegistry()
    registry.register(_TracingSkill())
    seen = {}

    def handler(skill, result, **kwargs):
        seen["trace"] = kwargs.get("trace")

    registry.register_event_callback(SkillEvent.POST_EXECUTE, handler)
    await registry.execute_skill("trace-skill", {"city": "北京"})

    assert seen["trace"]
    assert seen["trace"][0]["tool"] == "inner_tool"
    assert seen["trace"][0]["success"] is True


def test_failure_evidence_persists_trace_and_mutator_renders_it(tmp_path, monkeypatch):
    from neurova.evolution.eval.config import EvolutionConfig
    from neurova.evolution.eval.mutator import ReflectiveMutator
    from neurova.evolution.skill_evidence import (
        failureJudgeFailures,
        loadExecutionEvidence,
        recordExecutionEvidence,
    )

    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    failure = SimpleNamespace(success=False, data={"x": 1}, error="boom", metadata={})
    written = recordExecutionEvidence(
        "agent", "sk", user_input="task", params={"p": 1}, result=failure,
        trace=[
            {"tool": "inner_tool", "layer": "test", "params": "{}",
             "success": True, "error": "", "duration_ms": 2.0}
        ],
    )
    assert written["tool_trace_count"] == 1
    data = loadExecutionEvidence(written["evidence_ref"])
    assert data["tool_trace"][0]["tool"] == "inner_tool"

    record = SimpleNamespace(
        success=False, input_summary="task", output_summary="out",
        error_message="boom", metadata={"evidence_ref": written["evidence_ref"]},
    )
    failures = failureJudgeFailures([record])
    assert failures[0].tool_trace[0]["tool"] == "inner_tool"

    captured = {}

    async def fake_llm(messages, model):
        captured["prompt"] = messages[-1]["content"]
        return {"success": True, "response": "改进"}

    import asyncio

    asyncio.run(
        ReflectiveMutator(EvolutionConfig(), llm_call=fake_llm).mutate(
            artifact_text="base", artifact_type="skill", failures=failures
        )
    )
    assert "工具轨迹" in captured["prompt"]
    assert "inner_tool" in captured["prompt"]
