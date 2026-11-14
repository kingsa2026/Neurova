# -*- coding: utf-8 -*-
"""V4 增益-代价归因读数 —— 红灯测试。

对照档：docs/08-research/videoevolve_vs_neurova_harness_evolution_comparison_2026-11-14.md §3-V4。
论文（arXiv 2610.01766）成分交换实验把「增益来自哪一层、花什么代价」摆在桌面
上（指令稳定增益/代码收益不稳且调用翻倍）。本仓文本-only 阶段的诚实形态：
提案带 `gain_attribution` 面板——增益（留出/密封）、体积代价、修复通道贡献
（V1 是否参与最终胜者），并显式标注「当前唯一可进化面=指令面；策略/代码面
接入后按面分解」。

本文件钉：
1. runner：修复通道救回的运行 `repair_rescued=True`；常态接受/拒绝均为 False；
2. 提案：`gain_attribution` 随提案出街，数值与运行读数一致（不另算第二份）。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner
from neurova.evolution.eval.service import SkillEvolutionService

pytestmark = pytest.mark.timeout(120)

BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2
IMPROVED = "IMPROVED"
FIX1 = "FIX1"


def _dataset(names):
    items = [EvalExample(task_input=n, expected_behavior="输出要点") for n in names]
    return EvalDataset(train=list(items), val=[], holdout=list(items))


class _MarkerJudge:
    def __init__(self, baseline_scores, candidate_scores, fix1_scores=None):
        self._tables = [(FIX1, fix1_scores or {}), (IMPROVED, candidate_scores)]
        self._baseline = dict(baseline_scores)

    async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
        table = self._baseline
        for marker, scores in self._tables:
            if marker in skill_text:
                table = scores
                break
        value = table.get(task_input, 0.0)
        return FitnessScore(correctness=value, procedure_following=value,
                            conciseness=value, feedback="")


class _EchoAgent:
    async def run(self, *, skill_text, task_input):
        return f"out::{skill_text}"


def _scripted_mutate(script):
    calls = {"n": 0}

    async def _mutate(*, artifact_text, artifact_type, failures, **kw):
        idx = calls["n"]
        calls["n"] += 1
        if idx < len(script):
            return artifact_text + "\n" + script[idx]
        return artifact_text

    return _mutate


def _config(**kw):
    defaults = dict(iterations=1, min_improvement=0.0, case_regression_allowance=0,
                    noise_repeats=1, exec_suite_enabled=False,
                    anchor_floor_enabled=False, heldout_ratio=0.0)
    defaults.update(kw)
    return EvolutionConfig(**defaults)


class TestRepairRescuedFlag:
    """runner 面：最终胜者是否由修复通道捞回——采纳者该知道增益的来路。"""

    @pytest.mark.asyncio
    async def test_repaired_run_is_marked_rescued(self):
        judge = _MarkerJudge(
            baseline_scores={"a": 0.5, "b": 0.5, "c": 0.5},
            candidate_scores={"a": 1.0, "b": 1.0, "c": 0.1},
            fix1_scores={"a": 1.0, "b": 1.0, "c": 1.0})
        runner = SkillEvolutionRunner(
            _config(repair_rounds=1), judge=judge, agent=_EchoAgent(),
            mutate=_scripted_mutate([IMPROVED, FIX1]))
        result = await runner.run(baseline_text=BASELINE,
                                  dataset=_dataset(["a", "b", "c"]),
                                  artifact_type="skill", iterations=1)
        assert result.rejected is False
        assert result.repair_rescued is True
        assert result.to_dict()["repair_rescued"] is True

    @pytest.mark.asyncio
    async def test_plain_accept_is_not_rescued(self):
        judge = _MarkerJudge(
            baseline_scores={"a": 0.5},
            candidate_scores={"a": 0.9})
        runner = SkillEvolutionRunner(
            _config(), judge=judge, agent=_EchoAgent(),
            mutate=_scripted_mutate([IMPROVED]))
        result = await runner.run(baseline_text=BASELINE, dataset=_dataset(["a"]),
                                  artifact_type="skill", iterations=1)
        assert result.rejected is False
        assert result.repair_rescued is False

    @pytest.mark.asyncio
    async def test_rejected_run_is_not_rescued(self):
        judge = _MarkerJudge(
            baseline_scores={"a": 0.5, "b": 0.5, "c": 0.5},
            candidate_scores={"a": 1.0, "b": 1.0, "c": 0.1})
        runner = SkillEvolutionRunner(
            _config(), judge=judge, agent=_EchoAgent(),
            mutate=_scripted_mutate([IMPROVED]))
        result = await runner.run(baseline_text=BASELINE,
                                  dataset=_dataset(["a", "b", "c"]),
                                  artifact_type="skill", iterations=1)
        assert result.rejected is True
        assert result.repair_rescued is False


class TestProposalGainAttribution:
    """提案面：增益-代价归因面板随提案出街，数值与运行读数同源。"""

    @pytest.mark.asyncio
    async def test_proposal_carries_attribution(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("attr-agent", base_dir=tmp_path / "evo")
        _result, proposal = await svc.evolve(
            skill_id="s-attr", skill_text=BASELINE, dataset=_dataset(["a", "b"]),
            agent=_EchoAgent(),
            judge=_MarkerJudge({"a": 0.5, "b": 0.5}, {"a": 0.9, "b": 0.9}),
            mutate=_scripted_mutate([IMPROVED]), config=_config())

        assert proposal is not None, _result.reject_reason
        attr = proposal.gain_attribution
        assert attr["surfaces_touched"] == ["instruction"]
        assert attr["holdout_gain"] == pytest.approx(round(_result.improvement, 4))
        assert attr["size_delta_ratio"] is not None
        assert attr["repair_rounds"] == 0
        assert attr["repair_rescued"] is False
        assert "策略/代码面" in attr["note"]
        # 详情面同样携带
        assert "gain_attribution" in proposal.to_dict()
