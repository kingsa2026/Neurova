# -*- coding: utf-8 -*-
"""T4 E1 真臂 token 读数——真臂段 usage 快照差分出街，模拟臂不冒领。"""

import pytest

from neurova.core import usage_accounting as ua_module
from neurova.core.usage_accounting import (
    get_usage_accounting,
    reset_usage_accounting,
    tokensDelta,
)


@pytest.fixture
def clean_usage():
    reset_usage_accounting()
    yield get_usage_accounting()
    reset_usage_accounting()


def test_tokens_delta_core_single_source():
    """core 单源：正差分/零差分/负差分归零（不产假成本）。"""
    assert tokensDelta(100, 250) == 150
    assert tokensDelta(100, 100) == 0
    assert tokensDelta(100, 50) == 0


@pytest.mark.asyncio
async def test_simulated_arm_reports_none(tmp_path, monkeypatch, offlineAgent):
    """模拟臂 ⇒ None（不冒领真 token 计数）。"""
    from neurova.evolution.eval.config import EvolutionConfig
    from neurova.evolution.eval.dataset import EvalDataset, EvalExample
    from neurova.evolution.eval.service import SkillEvolutionService

    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    svc = SkillEvolutionService("tok-agent", base_dir=tmp_path / "evo")
    items = [EvalExample(task_input=f"t{i}", expected_behavior="要点") for i in range(2)]
    ds = EvalDataset(train=list(items), val=[], holdout=list(items))

    async def _judge(*, task_input, expected_behavior, output, skill_text, **kw):
        from neurova.evolution.eval.fitness import FitnessScore

        v = 0.9 if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=v, procedure_following=v,
                            conciseness=v, feedback="")

    async def _mutate(*, artifact_text, artifact_type, failures, **kw):
        return artifact_text + "IMPROVED。"

    result, _ = await svc.evolve(
        skill_id="s1", skill_text="基础正文。" + "补充。" * 8, dataset=ds,
        agent=offlineAgent, judge=_judge, mutate=_mutate,
        config=EvolutionConfig(iterations=1, min_improvement=0.0,
                               anchor_floor_enabled=False, cost_rule_enabled=False,
                               noise_repeats=0, heldout_ratio=0.0),
    )
    assert result.agent_turns_tokens is None, (
        "模拟臂报了 token 数——冒领真 token 计数")


@pytest.mark.asyncio
async def test_real_arm_reports_delta(tmp_path, monkeypatch):
    """真臂段差分咬合：评测期间发生的 usage 记账进读数（含校准探针段）。"""
    from neurova.evolution.eval.config import EvolutionConfig
    from neurova.evolution.eval.dataset import EvalDataset, EvalExample
    from neurova.evolution.eval.service import SkillEvolutionService
    from neurova.evolution.eval.ab_library import TextArmAgentExecutor

    monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
    reset_usage_accounting()

    class _StubOnlineAgent:
        async def chat(self, message, **kw):
            # 真臂回合路径上真记一笔 usage（模拟 multi_model_client 的记账）
            get_usage_accounting().record(model="stub", provider="stub",
                                          prompt_tokens=30, completion_tokens=20,
                                          estimated=False)
            return "MARK-OUTPUT"

    items = [EvalExample(task_input=f"t{i}", expected_behavior="要点") for i in range(2)]
    ds = EvalDataset(train=list(items), val=[], holdout=list(items))
    executor = TextArmAgentExecutor(_StubOnlineAgent(), skill_name="s1")
    svc = SkillEvolutionService("tok-real", base_dir=tmp_path / "evo")

    async def _judge(*, task_input, expected_behavior, output, skill_text, **kw):
        from neurova.evolution.eval.fitness import FitnessScore

        v = 0.9 if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=v, procedure_following=v,
                            conciseness=v, feedback="")

    async def _mutate(*, artifact_text, artifact_type, failures, **kw):
        return artifact_text + "IMPROVED。"

    result, _ = await svc.evolve(
        skill_id="s1", skill_text="基础正文。" + "补充。" * 8, dataset=ds,
        agent=executor, judge=_judge, mutate=_mutate,
        config=EvolutionConfig(iterations=1, min_improvement=0.0,
                               anchor_floor_enabled=False, cost_rule_enabled=False,
                               noise_repeats=0, heldout_ratio=0.0),
    )
    assert result.executorKind == "real_agent"
    assert result.agent_turns_tokens is not None and result.agent_turns_tokens > 0, (
        f"真臂 token 差分没咬合：{result.agent_turns_tokens}")
    assert result.agent_turns_tokens % 50 == 0, (
        f"差分与记账笔数不齐（每笔 50）：{result.agent_turns_tokens}")
