# -*- coding: utf-8 -*-
"""V1 near-miss 有界修复通道 —— 红灯测试。

对照档：docs/08-research/videoevolve_vs_neurova_harness_evolution_comparison_2026-11-14.md §3-V1。
论文（arXiv 2610.01766）机制：被验证侧门拒绝、但开发集增益为正的候选（near miss）
带门别诊断进入**有界**修复轮，而不是整轮弃置。本文件钉：

1. 默认关：repair_rounds=0 时回归门拒绝照旧（逐字旧行为），无修复尝试；
2. 修复生效：case_regression / holdout_regression 拒绝后，修复候选过全链门 → 接受；
3. 有界：修复候选仍不达标 → 额度耗尽即最终拒绝，尝试全程入审计（repair_attempts）；
4. 不可修复门（no_improvement）不触发修复；
5. 修复候选进恒等式账（assertCandidateIdentity 不破）。

测试里阈值/额度一律显式传参，不把实现默认值钉成契约（与本目录既有判据同纪律）。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner

pytestmark = pytest.mark.timeout(120)

BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2
# 变异器按调用序追加的标记；判分器按正文标记换分表（互不为子串，防误匹配）。
IMPROVED = "IMPROVED"
FIX1 = "FIX1"
FIX2 = "FIX2"


def _dataset(names):
    items = [EvalExample(task_input=n, expected_behavior="输出要点") for n in names]
    return EvalDataset(train=list(items), val=[], holdout=list(items))


def _split_dataset(train_names, holdout_names):
    """train 与 holdout 用不同任务面——holdout_regression 场景需要两侧读数分叉。"""
    return EvalDataset(
        train=[EvalExample(task_input=n, expected_behavior="输出要点") for n in train_names],
        val=[],
        holdout=[EvalExample(task_input=n, expected_behavior="输出要点") for n in holdout_names],
    )


class _MarkerJudge:
    """按正文标记换分表的脚本化判分器；未列出的任务记 0 分（已量出）。"""

    def __init__(self, baseline_scores, candidate_scores, fix1_scores=None, fix2_scores=None):
        # 匹配顺序即优先级；各标记互不为子串，顺序不影响结果
        self._tables = [(FIX2, fix2_scores or {}), (FIX1, fix1_scores or {}),
                        (IMPROVED, candidate_scores)]
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


def _mutate_by_call(script):
    """按调用序回放变异产物（追加标记）；超出脚本回原文（不再变异）。"""
    calls = {"n": 0}

    async def _mutate(*, artifact_text, artifact_type, failures, **kw):
        idx = calls["n"]
        calls["n"] += 1
        if idx < len(script):
            return artifact_text + "\n" + script[idx]
        return artifact_text

    _mutate.calls = calls
    return _mutate


def _config(repair_rounds, **kw):
    defaults = dict(iterations=1, min_improvement=0.0, case_regression_allowance=0,
                    repair_rounds=repair_rounds, noise_repeats=1,
                    exec_suite_enabled=False, anchor_floor_enabled=False)
    defaults.update(kw)
    return EvolutionConfig(**defaults)


class TestNearMissRepair:
    """V1 核心语义：回归门拒绝 ≠ 弃置，有界修复后过全链门才接受。"""

    @pytest.mark.asyncio
    async def test_case_regression_repaired_within_budget(self):
        """例级退化被拒 → 修复候选修好该例 → 过全链门接受，尝试入审计。"""
        mutate = _mutate_by_call([IMPROVED, FIX1])
        judge = _MarkerJudge(
            baseline_scores={"a": 0.5, "b": 0.5, "c": 0.5},
            candidate_scores={"a": 1.0, "b": 1.0, "c": 0.1},   # c 被改坏 → case_regression
            fix1_scores={"a": 1.0, "b": 1.0, "c": 1.0},        # 修复候选把 c 修好
        )
        runner = SkillEvolutionRunner(_config(1), judge=judge, agent=_EchoAgent(),
                                      mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
                                  artifact_type="skill", iterations=1)

        assert result.rejected is False, result.reject_reason
        assert FIX1 in result.deployed_text
        assert [a["gate"] for a in result.repair_attempts] == ["case_regression"]
        assert result.repair_attempts[0]["improved"] is True
        # 修复候选进恒等式账：生成 − 预检拒绝 = 评估 = 轮次
        result.assertCandidateIdentity()
        # 审计面外露（run 审计落盘读这里）
        assert result.to_dict()["repair_attempts"] == result.repair_attempts

    @pytest.mark.asyncio
    async def test_repair_disabled_by_default_rejects_as_before(self):
        """repair_rounds=0（缺省）：例级退化照旧整轮拒绝，无修复尝试。"""
        judge = _MarkerJudge(
            baseline_scores={"a": 0.5, "b": 0.5, "c": 0.5},
            candidate_scores={"a": 1.0, "b": 1.0, "c": 0.1},
            fix1_scores={"a": 1.0, "b": 1.0, "c": 1.0},
        )
        runner = SkillEvolutionRunner(_config(0), judge=judge, agent=_EchoAgent(),
                                      mutate=_mutate_by_call([IMPROVED, FIX1]))
        result = await runner.run(baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
                                  artifact_type="skill", iterations=1)

        assert result.rejected is True
        assert result.reject_reason == "case_regression"
        assert result.repair_attempts == []
        assert result.deployed_text == BASELINE

    @pytest.mark.asyncio
    async def test_holdout_regression_repaired(self):
        """留出集均值回退被拒 → 修复候选把留出侧拉回来 → 接受。"""
        mutate = _mutate_by_call([IMPROVED, FIX1])
        judge = _MarkerJudge(
            baseline_scores={"t1": 0.5, "t2": 0.5, "h1": 0.5, "h2": 0.5},
            candidate_scores={"t1": 0.9, "t2": 0.9, "h1": 0.1, "h2": 0.2},
            fix1_scores={"t1": 1.0, "t2": 1.0, "h1": 0.9, "h2": 0.9},
        )
        runner = SkillEvolutionRunner(_config(1), judge=judge, agent=_EchoAgent(),
                                      mutate=mutate)
        result = await runner.run(baseline_text=BASELINE,
                                  dataset=_split_dataset(["t1", "t2"], ["h1", "h2"]),
                                  artifact_type="skill", iterations=1)

        assert result.rejected is False, result.reject_reason
        assert FIX1 in result.deployed_text
        assert [a["gate"] for a in result.repair_attempts] == ["holdout_regression"]
        result.assertCandidateIdentity()

    @pytest.mark.asyncio
    async def test_repair_not_improved_rejects_without_burning_more(self):
        """修复候选在 tune 上无增益 → 不再空转，按原门拒绝（一次尝试即止）。"""
        mutate = _mutate_by_call([IMPROVED, FIX1])
        judge = _MarkerJudge(
            baseline_scores={"a": 0.5, "b": 0.5, "c": 0.5},
            candidate_scores={"a": 1.0, "b": 1.0, "c": 0.1},
            fix1_scores={"a": 1.0, "b": 1.0, "c": 0.1},   # 修复后 c 仍被撞坏
        )
        runner = SkillEvolutionRunner(_config(3), judge=judge, agent=_EchoAgent(),
                                      mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
                                  artifact_type="skill", iterations=1)

        assert result.rejected is True
        assert result.reject_reason == "case_regression"
        assert len(result.repair_attempts) == 1
        assert result.repair_attempts[0]["improved"] is False
        assert result.deployed_text == BASELINE

    @pytest.mark.asyncio
    async def test_repair_loop_bounded_by_budget(self):
        """修复候选逐轮更好但仍未过门 → 逐轮修复直到额度耗尽，最终拒绝。"""
        mutate = _mutate_by_call([IMPROVED, FIX1, FIX2])
        judge = _MarkerJudge(
            baseline_scores={"a": 0.5, "b": 0.5, "c": 0.5},
            candidate_scores={"a": 1.0, "b": 1.0, "c": 0.1},
            fix1_scores={"a": 1.0, "b": 1.0, "c": 0.2},
            fix2_scores={"a": 1.0, "b": 1.0, "c": 0.3},   # 逐轮回升但始终 < 0.5
        )
        runner = SkillEvolutionRunner(_config(2), judge=judge, agent=_EchoAgent(),
                                      mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
                                  artifact_type="skill", iterations=1)

        assert result.rejected is True
        assert result.reject_reason == "case_regression"
        assert len(result.repair_attempts) == 2, "额度=2：修复两轮后停止"
        assert [a["improved"] for a in result.repair_attempts] == [True, True]
        assert result.deployed_text == BASELINE
        result.assertCandidateIdentity()

    @pytest.mark.asyncio
    async def test_no_improvement_is_not_repaired(self):
        """无增益（no_improvement）不属可修复门：即便有额度也不发起修复。"""
        mutate = _mutate_by_call([IMPROVED, FIX1])
        judge = _MarkerJudge(
            baseline_scores={"a": 0.5},
            candidate_scores={"a": 0.5},   # 无增益
            fix1_scores={"a": 0.9},
        )
        runner = SkillEvolutionRunner(_config(2), judge=judge, agent=_EchoAgent(),
                                      mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, dataset=_dataset(["a"]),
                                  artifact_type="skill", iterations=1)

        assert result.rejected is True
        assert result.reject_reason == "no_improvement"
        assert result.repair_attempts == []

    @pytest.mark.asyncio
    async def test_repair_respects_constraints_gate(self):
        """修复候选照样过约束闸：超尺寸/违规候选不得借修复通道绕闸。"""
        mutate = _mutate_by_call([IMPROVED, FIX1])

        class _RejectingConstraints:
            def validate(self, candidate, artifact_type, baseline_text=""):
                from neurova.evolution.eval.constraints import ConstraintResult

                # 只拦修复候选（带 FIX1 标记的），基线代候选放行
                if FIX1 in candidate:
                    return [ConstraintResult(name="fake_violation", passed=False,
                                             message="测试替身：修复候选违规")]
                return [ConstraintResult(name="fake_violation", passed=True,
                                         message="放行")]

        judge = _MarkerJudge(
            baseline_scores={"a": 0.5, "b": 0.5, "c": 0.5},
            candidate_scores={"a": 1.0, "b": 1.0, "c": 0.1},
            fix1_scores={"a": 1.0, "b": 1.0, "c": 1.0},
        )
        runner = SkillEvolutionRunner(_config(1), judge=judge, agent=_EchoAgent(),
                                      mutate=mutate, constraints=_RejectingConstraints())
        result = await runner.run(baseline_text=BASELINE, dataset=_dataset(["a", "b", "c"]),
                                  artifact_type="skill", iterations=1)

        assert result.rejected is True
        assert result.reject_reason == "case_regression"
        assert result.repair_attempts[0].get("blocked") == "constraints"
        assert result.deployed_text == BASELINE
