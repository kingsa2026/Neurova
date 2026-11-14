# -*- coding: utf-8 -*-
"""V2 保留分支一等对象（分支引导进化）—— 红灯测试。

对照档：docs/08-research/videoevolve_vs_neurova_harness_evolution_comparison_2026-11-14.md §3-V2。
论文（arXiv 2610.01766）机制：有希望的非冠军分支保留为后续精炼的父代，晋升或重试
额度耗尽后重置——「别急着砍第二名」。本文件钉：

1. BranchPool 单元语义：seed/retain/markFailed（额度耗尽即退役）/markPromoted；
2. 默认 branch_retries=0：颗粒无收的基线轮即弃（与既有递归行为一致，预算不放大）；
3. branch_retries>0：颗粒无收的分支保留到下一轮继续精炼；
4. 递归报告带分支账本（branches）与逐轮 branch_id/parent_id 轨迹；晋升入账。
"""

import pytest

from neurova.evolution.eval.branch_pool import BranchPool
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.runner import EvolutionRunResult
from neurova.evolution.eval.service import SkillEvolutionService

BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 10


def _ds():
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _res(*, rejected=False, reason="", before=0.5, after=0.5, deployed=None,
         variants=None):
    """构造 evolveRecursive 桩所需的运行结果；changed 由 deployed_text 推导。"""
    deployed_text = BASELINE if deployed is None else deployed
    r = EvolutionRunResult(baseline_text=BASELINE, deployed_text=deployed_text)
    r.rejected = rejected
    r.reject_reason = reason
    r.holdout_before = before
    r.holdout_after = after
    r.cost_summary = {}
    r.exec_suite = {}
    r.pareto_variants = list(variants or [])
    return r


def _install_script(svc, monkeypatch, outcomes):
    """把 svc.evolve 换成按调用序回放的桩，记录每次收到的基线正文。"""
    calls: list = []

    async def fake_evolve(**kwargs):
        calls.append(str(kwargs.get("skill_text") or ""))
        idx = min(len(calls) - 1, len(outcomes) - 1)
        return outcomes[idx], None

    monkeypatch.setattr(svc, "evolve", fake_evolve)
    return calls


class TestBranchPoolUnit:
    """分支池单元语义：身份、继承、重试额度、晋升/退役。"""

    def test_seed_creates_active_root_branch(self):
        pool = BranchPool(retry_budget=1)
        b = pool.seed(BASELINE, score=0.5)
        assert pool.active() == [b]
        assert b.status == "active"
        assert b.parent_id == ""
        assert b.retries_left == 1

    def test_mark_failed_decrements_then_exhausts(self):
        pool = BranchPool(retry_budget=1)
        b = pool.seed("x")
        pool.markFailed(b.branch_id)
        assert b.status == "active"
        assert b.retries_left == 0
        pool.markFailed(b.branch_id)
        assert b.status == "exhausted"
        assert pool.active() == []

    def test_mark_failed_zero_budget_exhausts_immediately(self):
        """默认额度 0：一次颗粒无收即退役（既有行为逐字保持）。"""
        pool = BranchPool(retry_budget=0)
        b = pool.seed("x")
        pool.markFailed(b.branch_id)
        assert b.status == "exhausted"
        assert pool.active() == []

    def test_retain_child_carries_parent_and_fresh_budget(self):
        pool = BranchPool(retry_budget=2)
        parent = pool.seed("p")
        child = pool.retain(text="c", score=0.8, parent_id=parent.branch_id, epoch=2)
        assert child.parent_id == parent.branch_id
        assert child.epoch_created == 2
        assert child.retries_left == 2
        assert child.status == "active"
        assert child.branch_id != parent.branch_id

    def test_mark_promoted_retires_branch_with_epoch(self):
        pool = BranchPool(retry_budget=1)
        b = pool.seed("p")
        pool.markPromoted(b.branch_id, epoch=3)
        assert b.status == "promoted"
        assert b.promoted_epoch == 3
        assert pool.active() == []

    def test_to_dict_carries_audit_fields(self):
        pool = BranchPool(retry_budget=1)
        root = pool.seed("root-text", score=0.5)
        child = pool.retain(text="child-text", score=0.7,
                            parent_id=root.branch_id, epoch=2)
        rows = pool.to_dict()
        by_id = {r["branch_id"]: r for r in rows}
        assert by_id[root.branch_id]["text_head"] == "root-text"
        assert by_id[child.branch_id]["parent_id"] == root.branch_id
        assert by_id[child.branch_id]["score"] == 0.7
        assert {"branch_id", "parent_id", "epoch_created", "status",
                "retries_left", "score", "promoted_epoch", "text_head"} <= set(rows[0])

    def test_unknown_branch_ids_are_ignored(self):
        """晋升/受挫记到不存在的分支上必须出声而不是静默吞掉。"""
        pool = BranchPool(retry_budget=1)
        with pytest.raises(KeyError):
            pool.markPromoted("ghost", epoch=1)
        with pytest.raises(KeyError):
            pool.markFailed("ghost")


class TestEvolveRecursiveBranches:
    """递归演化的分支账本与保留语义（evolve 打桩，只测编排）。"""

    @pytest.mark.asyncio
    async def test_fruitless_branch_dropped_by_default(self, monkeypatch, tmp_path):
        """branch_retries 缺省 0：颗粒无收的轮次即停（既有行为）。"""
        svc = SkillEvolutionService("br-agent", base_dir=tmp_path)
        calls = _install_script(svc, monkeypatch, [
            _res(rejected=True, reason="no_improvement"),
        ])
        report = await svc.evolveRecursive(
            skill_id="sk", skill_text=BASELINE, dataset=_ds(), epochs=3,
            iterations=1, pool_size=1,
            config=EvolutionConfig(noise_repeats=1, exec_suite_enabled=False))

        assert len(calls) == 1
        assert report["epochs_run"] == 1
        assert report["stopped_reason"] == "no_improvement"
        assert report["deployed_text"] == BASELINE

    @pytest.mark.asyncio
    async def test_fruitless_branch_retained_then_promoted(self, monkeypatch, tmp_path):
        """branch_retries=1：首轮颗粒无收的分支保留一轮，次轮翻身并晋升。"""
        svc = SkillEvolutionService("br-agent", base_dir=tmp_path)
        improved = BASELINE + " IMPROVED"
        calls = _install_script(svc, monkeypatch, [
            _res(rejected=True, reason="no_improvement"),       # epoch1：种子颗粒无收
            _res(after=0.6, deployed=improved),                 # epoch2：保留分支翻身
            _res(rejected=True, reason="no_improvement"),       # epoch3：子分支无收（额度尽）
        ])
        report = await svc.evolveRecursive(
            skill_id="sk", skill_text=BASELINE, dataset=_ds(), epochs=3,
            iterations=1, pool_size=1, branch_retries=1,
            config=EvolutionConfig(noise_repeats=1, exec_suite_enabled=False))

        assert len(calls) == 3, "保留分支应在次轮再被精炼一次"
        assert report["epochs_run"] == 3
        assert report["deployed_text"] == improved
        assert report["total_improvement"] == pytest.approx(0.1)
        # 分支账本：种子分支受挫后保留、晋升；子分支额度耗尽退役
        branches = {b["branch_id"]: b for b in report["branches"]}
        seed_rows = [b for b in branches.values() if b["parent_id"] == ""]
        assert len(seed_rows) == 1
        assert seed_rows[0]["status"] == "promoted"
        assert seed_rows[0]["promoted_epoch"] == 2
        child_rows = [b for b in branches.values() if b["parent_id"] == seed_rows[0]["branch_id"]]
        assert child_rows
        # 子分支首轮受挫后保留（额度 1 用掉、尚未耗尽）——这正是「别急着砍第二名」
        assert child_rows[0]["status"] == "active"
        assert child_rows[0]["retries_left"] == 0
        # 逐轮轨迹携带分支身份
        assert report["epochs"][0]["branch_id"] == seed_rows[0]["branch_id"]
        assert report["epochs"][1]["branch_id"] == seed_rows[0]["branch_id"]
        assert report["epochs"][2]["parent_id"] == seed_rows[0]["branch_id"]

    @pytest.mark.asyncio
    async def test_multi_branch_pool_keeps_second_lineage(self, monkeypatch, tmp_path):
        """pool_size=2：非劣双谱系并行推进，胜者晋升、败者不挤占冠军线。"""
        svc = SkillEvolutionService("br-agent", base_dir=tmp_path)
        text_a = BASELINE + " AA"
        text_b = BASELINE + " B"
        text_b2 = BASELINE + " B2"
        calls = _install_script(svc, monkeypatch, [
            # epoch1：种子产出双非劣变体（分数/长度互不支配）
            _res(after=0.6, deployed=text_a,
                 variants=[{"text": text_a, "score": 0.61, "tier": "standard",
                            "cost_usd": 1.0, "tokens": 10},
                           {"text": text_b, "score": 0.60, "tier": "lite",
                            "cost_usd": 0.8, "tokens": 8}]),
            # epoch2：A 谱系颗粒无收；B 谱系翻身成新冠军
            _res(rejected=True, reason="no_improvement"),
            _res(after=0.7, deployed=text_b2),
        ])
        report = await svc.evolveRecursive(
            skill_id="sk", skill_text=BASELINE, dataset=_ds(), epochs=2,
            iterations=1, pool_size=2,
            config=EvolutionConfig(noise_repeats=1, exec_suite_enabled=False))

        assert len(calls) == 3, "epoch2 应对池内两个谱系各跑一次"
        assert report["deployed_text"] == text_b2
        branches = {b["branch_id"]: b for b in report["branches"]}
        statuses = [b["status"] for b in branches.values()]
        assert statuses.count("promoted") == 2, "种子（产出双谱系）与 B 谱系各晋升一次"
        assert "exhausted" in statuses, "A 谱系颗粒无收应退役（默认额度 0）"

    @pytest.mark.asyncio
    async def test_branch_retries_do_not_expand_budget_beyond_pool_cap(self, monkeypatch, tmp_path):
        """保留分支与孩子共享 pool_size 容量：孩子优先，保留者补空位。"""
        svc = SkillEvolutionService("br-agent", base_dir=tmp_path)
        calls = _install_script(svc, monkeypatch, [
            _res(after=0.6, deployed=BASELINE + " IMPROVED"),   # epoch1：胜者孩子入池
            _res(rejected=True, reason="no_improvement"),       # epoch2：孩子颗粒无收→保留
            _res(rejected=True, reason="no_improvement"),       # epoch3：保留者再受挫→退役
        ])
        report = await svc.evolveRecursive(
            skill_id="sk", skill_text=BASELINE, dataset=_ds(), epochs=3,
            iterations=1, pool_size=1, branch_retries=1,
            config=EvolutionConfig(noise_repeats=1, exec_suite_enabled=False))

        # 池容量 1：每轮最多一个基被进化；保留不放大每轮评测数
        assert len(calls) == 3
        assert report["epochs_run"] == 3
        assert report["final_pool_size"] <= 1
