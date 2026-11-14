# -*- coding: utf-8 -*-
"""V3 可进化面 schema —— 红灯测试。

对照档：docs/08-research/videoevolve_vs_neurova_harness_evolution_comparison_2026-11-14.md §3-V3。
论文（arXiv 2610.01766）「填空式结构表示」：阶段接口固定、每份提案只编辑一个
被允许的「面」、候选先过接口检查。本仓的可进化面此前是**隐式**的——尺寸预算
映射在 mutator/runner/constraints 三处各抄一份，且 runner 那份已漂移（丢了
param_description 分支，把参数描述当成 15KB 正文量）。

本文件钉：
1. surfaces schema：四个文本面各有名称/类型/标注/预算键/可执行套件适用性/
   接口约束（写回位置与消费方）；
2. 单源收口：mutator._size_budget、constraints._size_limit_for、runner 的
   judge max_size 全部与 sizeBudgetFor 一致（含 param_description 修正）；
3. EXEC_SUITE_ARTIFACT_TYPES 由 schema 派生（不再各写一份清单）；
4. 提案按面记录（proposal.surface 读数）。
"""

import pytest

from neurova.evolution.eval import exec_suite as exec_suite_mod
from neurova.evolution.eval import surfaces
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.constraints import ConstraintValidator
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.mutator import ReflectiveMutator
from neurova.evolution.eval.runner import SkillEvolutionRunner
from neurova.evolution.eval.service import SkillEvolutionService

pytestmark = pytest.mark.timeout(120)

BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2


class TestSurfaceSchema:
    """schema 本体：面清单、预算键、可执行套件适用性、接口约束。"""

    def test_four_text_surfaces_registered(self):
        assert set(surfaces.SURFACES) == {"skill", "template",
                                          "tool_description", "param_description"}
        for surface in surfaces.SURFACES.values():
            assert surface.kind == "text"
            assert surface.label
            assert surface.writeback and surface.consumer

    def test_budget_keys_exist_on_config(self):
        cfg = EvolutionConfig()
        for surface in surfaces.SURFACES.values():
            assert hasattr(cfg, surface.size_budget_key), surface.name

    def test_exec_suite_flags(self):
        assert surfaces.SURFACES["skill"].exec_suite_applies is True
        assert surfaces.SURFACES["template"].exec_suite_applies is True
        assert surfaces.SURFACES["tool_description"].exec_suite_applies is True
        assert surfaces.SURFACES["param_description"].exec_suite_applies is False

    def test_unknown_surface_raises(self):
        with pytest.raises(KeyError):
            surfaces.surfaceFor("workflow_code")

    def test_has_surface(self):
        assert surfaces.hasSurface("skill") is True
        assert surfaces.hasSurface("workflow_code") is False

    def test_size_budget_resolves_from_config(self):
        cfg = EvolutionConfig(max_skill_size=1234, max_tool_desc_size=45,
                              max_param_desc_size=6)
        assert surfaces.sizeBudgetFor("skill", cfg) == 1234
        assert surfaces.sizeBudgetFor("template", cfg) == 1234
        assert surfaces.sizeBudgetFor("tool_description", cfg) == 45
        assert surfaces.sizeBudgetFor("param_description", cfg) == 6

    def test_unknown_surface_budget_falls_back_to_skill(self):
        """未知面回退技能预算（与旧 else 分支逐字一致，不因改 schema 漂移）。"""
        cfg = EvolutionConfig(max_skill_size=1234)
        assert surfaces.sizeBudgetFor("workflow_code", cfg) == 1234

    def test_exec_suite_types_derived_from_schema(self):
        assert set(exec_suite_mod.EXEC_SUITE_ARTIFACT_TYPES) == {
            "skill", "template", "tool_description"}


class TestSingleSourceRewire:
    """三处抄写收口到一把尺：mutator / constraints / runner 判分上限。"""

    def test_mutator_budget_matches_schema(self):
        cfg = EvolutionConfig(max_skill_size=1234, max_tool_desc_size=45,
                              max_param_desc_size=6)
        mutator = ReflectiveMutator(cfg)
        for name in surfaces.SURFACES:
            assert mutator._size_budget(name) == surfaces.sizeBudgetFor(name, cfg)

    def test_constraints_limit_matches_schema(self):
        cfg = EvolutionConfig(max_skill_size=1234, max_tool_desc_size=45,
                              max_param_desc_size=6)
        validator = ConstraintValidator(cfg)
        for name in surfaces.SURFACES:
            assert validator._size_limit_for(name) == surfaces.sizeBudgetFor(name, cfg)

    @pytest.mark.asyncio
    async def test_runner_judge_size_cap_matches_schema(self):
        """runner 判分面传给 judge 的 max_size 与 schema 同源——param_description
        不再被当成 15KB 正文量（既有三抄漂移的修正）。"""
        captured = {}

        class _CaptureJudge:
            async def score(self, *, task_input, expected_behavior, output,
                            skill_text, artifact_size=0, max_size=0, **kw):
                captured["max_size"] = max_size
                return FitnessScore(correctness=0.5, procedure_following=0.5,
                                    conciseness=0.5, feedback="")

        class _Agent:
            async def run(self, *, skill_text, task_input):
                return "out"

        cfg = EvolutionConfig(max_skill_size=1234, max_tool_desc_size=45,
                              max_param_desc_size=6)
        runner = SkillEvolutionRunner(cfg, judge=_CaptureJudge(), agent=_Agent())
        example = EvalExample(task_input="t", expected_behavior="x")
        await runner._score_example("正文", example, "param_description")
        assert captured["max_size"] == cfg.max_param_desc_size
        assert captured["max_size"] == surfaces.sizeBudgetFor("param_description", cfg)


class TestProposalCarriesSurface:
    """提案按面记录：面名称/标注/类型/预算随提案出街。"""

    @pytest.mark.asyncio
    async def test_proposal_surface_readout(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("surface-agent", base_dir=tmp_path / "evo")
        cfg = EvolutionConfig(iterations=1, min_improvement=0.0,
                              noise_repeats=1, exec_suite_enabled=False,
                              anchor_floor_enabled=False, heldout_ratio=0.0)

        class _Judge:
            async def score(self, *, task_input, expected_behavior, output,
                            skill_text, **kw):
                value = 0.9 if "IMPROVED" in skill_text else 0.5
                return FitnessScore(correctness=value, procedure_following=value,
                                    conciseness=value, feedback="")

        class _Agent:
            async def run(self, *, skill_text, task_input):
                return f"out::{skill_text}"

        async def _mutate(*, artifact_text, artifact_type, failures, **kw):
            return artifact_text + "\nIMPROVED"

        _result, proposal = await svc.evolve(
            skill_id="s-surface", skill_text=BASELINE,
            dataset=EvalDataset(
                train=[EvalExample(task_input="a", expected_behavior="输出要点")],
                val=[], holdout=[]),
            agent=_Agent(), judge=_Judge(), mutate=_mutate, config=cfg)

        assert proposal is not None, _result.reject_reason
        assert proposal.surface["name"] == "template"
        assert proposal.surface["label"] == surfaces.SURFACES["template"].label
        assert proposal.surface["kind"] == "text"
        assert proposal.surface["max_size"] == cfg.max_skill_size
        assert "surface" in proposal.to_dict()
