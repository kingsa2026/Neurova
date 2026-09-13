"""Wave 1 — ReflectiveMutator 反射式变异测试。

对照现有 prompt_optimizer.generate_variants 的"加角色段/加结构段"——那是
盲目变异;本模块必须把上一轮**失败反馈**带进 prompt,做定向修改。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.mutator import JudgeFailure, ReflectiveMutator


def _fail(task="审查代码", output="没发现问题", feedback="漏掉了 SQL 注入"):
    return JudgeFailure(task_input=task, output=output, feedback=feedback, score=0.2)


class TestReflectiveMutator:
    @pytest.mark.asyncio
    async def test_failures_are_injected_into_prompt(self):
        captured = {}

        async def fake_call(messages, model):
            captured["messages"] = messages
            return {"success": True, "response": "改进后的技能正文"}

        mut = ReflectiveMutator(EvolutionConfig(), llm_call=fake_call)
        out = await mut.mutate(
            artifact_text="原始技能正文",
            artifact_type="skill",
            failures=[_fail()],
        )
        assert out == "改进后的技能正文"
        blob = str(captured["messages"])
        assert "漏掉了 SQL 注入" in blob, "失败反馈必须进入变异 prompt"
        assert "原始技能正文" in blob, "基线正文必须进入变异 prompt"

    @pytest.mark.asyncio
    async def test_no_failures_falls_back_to_improve_prompt(self):
        async def fake_call(messages, model):
            return {"success": True, "response": "v2"}

        mut = ReflectiveMutator(EvolutionConfig(), llm_call=fake_call)
        out = await mut.mutate(artifact_text="基线", artifact_type="skill", failures=[])
        assert out == "v2"

    @pytest.mark.asyncio
    async def test_empty_llm_response_keeps_baseline(self):
        """LLM 返回空/失败时必须退回基线,绝不产出空技能。"""
        async def fake_call(messages, model):
            return {"success": True, "response": "   "}

        mut = ReflectiveMutator(EvolutionConfig(), llm_call=fake_call)
        out = await mut.mutate(artifact_text="基线正文", artifact_type="skill", failures=[_fail()])
        assert out == "基线正文"

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_baseline(self):
        async def fake_call(messages, model):
            return {"success": False, "error": "boom"}

        mut = ReflectiveMutator(EvolutionConfig(), llm_call=fake_call)
        out = await mut.mutate(artifact_text="基线正文", artifact_type="skill", failures=[_fail()])
        assert out == "基线正文"

    @pytest.mark.asyncio
    async def test_prompt_states_preserve_intent_and_budget(self):
        captured = {}

        async def fake_call(messages, model):
            captured["messages"] = messages
            return {"success": True, "response": "x"}

        cfg = EvolutionConfig(max_skill_size=15_000)
        mut = ReflectiveMutator(cfg, llm_call=fake_call)
        await mut.mutate(artifact_text="基线", artifact_type="skill", failures=[_fail()])
        blob = str(captured["messages"])
        # 约束必须显式写进 prompt(保持原意图 + 尺寸预算)
        assert "15000" in blob or "15,000" in blob
        assert "意图" in blob or "intent" in blob.lower()
