"""HN6/HC6 演化评测集核选（难度加权多样性，DPP 思想自研贪心）——红灯测试。

断点 HN6：评测集三级回退解决「有没有」，不做「选哪几个最划算」的核选；
评测成本随评测集线性走。本文件钉：

1. selectCoreset 确定性（同输入同输出）；
2. k ≥ n 全保留；k < n 恰好 k 个；
3. 多样性：近重复任务挤同一位次时， distinct 的那条必须入选；
4. 难度加权：多样性相同时，信息量更大（更长/更结构化）的任务优先；
5. 进化接线：eval_coreset_k>0 且评测集更大时，判据集收缩到 K
   （以成本账的 baseline 臂任务数佐证），运行照常完成。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.coreset import selectCoreset
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner
from neurova.evolution.eval.service import SkillEvolutionService


def _ex(task: str) -> EvalExample:
    return EvalExample(task_input=task, expected_behavior="输出要点")


class TestSelectCoreset:
    def test_k_ge_n_returns_all(self):
        cases = [_ex(f"task{i}") for i in range(3)]
        assert len(selectCoreset(cases, 5)) == 3

    def test_exactly_k_and_deterministic(self):
        cases = [_ex(f"task{i}") for i in range(10)]
        a = selectCoreset(cases, 4)
        b = selectCoreset(cases, 4)
        assert len(a) == 4
        assert [c.task_input for c in a] == [c.task_input for c in b]

    def test_duplicate_inputs_deduped_by_diversity(self):
        """三条近重复 + 一条 distinct：核选必须带上 distinct 那条。"""
        cases = [
            _ex("读取 data.csv 的前 10 行并输出列名"),
            _ex("读取 data.csv 的前 20 行并输出列名"),   # 近重复
            _ex("读取 data.csv 的前 30 行并输出列名"),   # 近重复
            _ex("把数据库里的用户表迁移到新的分片集群"),  # distinct
        ]
        picked = {c.task_input for c in selectCoreset(cases, 2)}
        assert "把数据库里的用户表迁移到新的分片集群" in picked

    def test_difficulty_weight_prefers_richer_task(self):
        """多样性等价时，更长/更结构化（更难）的任务优先入选。"""
        cases = [
            _ex("列目录"),
            _ex("分析这套微服务架构的并发瓶颈，给出重构方案并论证取舍"),
        ]
        picked = {c.task_input for c in selectCoreset(cases, 1)}
        assert "分析这套微服务架构的并发瓶颈，给出重构方案并论证取舍" in picked

    def test_empty_and_zero_k(self):
        assert selectCoreset([], 3) == []
        assert selectCoreset([_ex("a")], 0) == []


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 4


def _ds(n_train: int = 8) -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"任务 {i}：处理数据块并输出结果要点", expected_behavior="输出要点")
               for i in range(n_train)],
        val=[EvalExample(task_input=f"校验 {i}：核对输出格式与完整性", expected_behavior="输出要点")
             for i in range(2)],
        holdout=[EvalExample(task_input=f"终审 {i}：验证端到端行为", expected_behavior="输出要点")
                 for i in range(2)],
    )


def _judge_with_gain(gain: float):
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.2 + gain if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


async def _mutate(*, artifact_text, artifact_type, failures):
    return artifact_text + " IMPROVED"


class TestCoresetWiring:
    @pytest.mark.asyncio
    async def test_coreset_shrinks_eval_cost(self, monkeypatch):
        """开核选（K=4）后判据集变小：以成本账 baseline 臂任务数佐证。"""
        calls = {"n": 0}

        def fake_snapshot():
            calls["n"] += 1
            return {"tokens": calls["n"] * 10, "cost_usd": calls["n"] * 0.001}

        from neurova.evolution.eval import cost_ledger

        monkeypatch.setattr(cost_ledger, "usageSnapshot", fake_snapshot)

        async def runner_run_size(coreset_k: int) -> int:
            runner = SkillEvolutionRunner(
                EvolutionConfig(eval_coreset_k=coreset_k, noise_repeats=1),
                judge=_judge_with_gain(0.02), mutate=_mutate)
            result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                      dataset=_ds())
            assert not result.rejected
            return result.cost_summary["arms"]["baseline"]["tasks"]

        full = await runner_run_size(0)
        cored = await runner_run_size(4)
        assert full > cored
        assert cored == 4  # train(4) 全量 + val/holdout 从核选集再分


# ── 设置项化（治理面 K 值）────────────────────────────────────────

class TestCoresetSettings:
    def test_default_zero_and_roundtrip(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_EVAL_CORESET_SETTINGS", str(tmp_path / "cs.json"))
        monkeypatch.delenv("NEUROVA_EVAL_CORESET_K", raising=False)
        from neurova.security import eval_coreset_settings as ecs

        assert ecs.coreset_k() == 0
        assert ecs.save_settings(6) is True
        assert ecs.coreset_k() == 6

    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_EVAL_CORESET_SETTINGS", str(tmp_path / "cs.json"))
        from neurova.security import eval_coreset_settings as ecs

        ecs.save_settings(6)
        monkeypatch.setenv("NEUROVA_EVAL_CORESET_K", "2")
        assert ecs.coreset_k() == 2

    def test_clamped_to_domain(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_EVAL_CORESET_SETTINGS", str(tmp_path / "cs.json"))
        from neurova.security import eval_coreset_settings as ecs

        ecs.save_settings(9999)
        assert ecs.coreset_k() == 200
        ecs.save_settings(-3)
        assert ecs.coreset_k() == 0

    @pytest.mark.asyncio
    async def test_runner_uses_max_of_config_and_settings(self, monkeypatch, tmp_path):
        """生效 K = max(代码级配置, 治理设置)——治理设置抬底线，测试配置不失效。"""
        seen: list = []
        import neurova.evolution.eval.coreset as coreset_mod

        real = coreset_mod.selectCoreset

        def spy(cases, k):
            seen.append(k)
            return real(cases, k)

        monkeypatch.setattr(coreset_mod, "selectCoreset", spy)
        monkeypatch.setenv("NEUROVA_EVAL_CORESET_SETTINGS", str(tmp_path / "cs.json"))
        from neurova.security import eval_coreset_settings as ecs

        ecs.save_settings(6)
        runner = SkillEvolutionRunner(
            EvolutionConfig(noise_repeats=1),  # config K=0
            judge=_judge_with_gain(0.02), mutate=_mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert seen and seen[0] == 6  # 治理设置抬到 6

        seen.clear()
        runner2 = SkillEvolutionRunner(
            EvolutionConfig(noise_repeats=1, eval_coreset_k=4),
            judge=_judge_with_gain(0.02), mutate=_mutate)
        await runner2.run(baseline_text=BASELINE, artifact_type="skill",
                          dataset=_ds(), iterations=1)
        assert seen[0] == 6  # max(4, 6) = 6


# ── 双段复核（核选探路 → 全量留出复核）────────────────────────────

class TestFullRecheck:
    def _fixed_coreset(self, monkeypatch):
        """把核选钉成「前 4 条」，使核选留出与全量留出（终审任务）可区分。"""
        import neurova.evolution.eval.coreset as coreset_mod

        real = coreset_mod.selectCoreset

        def fixed(cases, k):
            return real(list(cases)[:4], min(4, len(cases)))

        monkeypatch.setattr(coreset_mod, "selectCoreset", fixed)

    @pytest.mark.asyncio
    async def test_recheck_measured_on_full_holdout(self, monkeypatch):
        """核选选出的胜者在**全量留出**上复核，读数落 coreset_recheck。"""
        self._fixed_coreset(monkeypatch)
        runner = SkillEvolutionRunner(
            EvolutionConfig(noise_repeats=1, eval_coreset_k=4),
            judge=_judge_with_gain(0.02), mutate=_mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert result.coreset_recheck["state"] == "measured"
        assert result.coreset_recheck["full_improvement"] == pytest.approx(0.02)

    @pytest.mark.asyncio
    async def test_recheck_rejects_full_holdout_regression(self, monkeypatch):
        """核选留出过关、但全量留出被改坏 ⇒ coreset_recheck_failed 拒绝。"""
        self._fixed_coreset(monkeypatch)

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            if "IMPROVED" not in skill_text:
                c = 0.2
            elif "终审" in task_input:
                c = 0.0  # 只在全量留出任务上改坏——核选集里看不到
            else:
                c = 0.42
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        runner = SkillEvolutionRunner(
            EvolutionConfig(noise_repeats=1, eval_coreset_k=4),
            judge=judge, mutate=_mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert result.rejected
        assert result.reject_reason == "coreset_recheck_failed"
        assert result.deployed_text == BASELINE

    @pytest.mark.asyncio
    async def test_no_shrink_no_recheck(self, monkeypatch):
        """未核选（K=0）⇒ 无复核读数（旧行为逐字节不变）。"""
        runner = SkillEvolutionRunner(
            EvolutionConfig(noise_repeats=1),
            judge=_judge_with_gain(0.02), mutate=_mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert result.coreset_recheck == {}
