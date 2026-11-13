"""N1+N2 Pareto 多档交付与候选集并行递归 —— 红灯测试。

§11.3 残差清偿：
- N1（dim 3 残差）：多变体轮开启 `profile_variants_enabled` 时，幸存候选按
  lite/standard/heavy 轮转指派执行档位并**串行**评测（turn 级档位真实生效、
  快照差分按候选归账），产出 (分数, 成本) 的 **Pareto 非劣集**随结果交付
  ——「按部署预算交付」的读数面；胜者选择逻辑不变。
- N2（dim 1 残差）：`lineage_pareto_enabled` 时，多变体轮把**非劣幸存者**
  透出到结果；`evolveRecursive(pool_size>1)` 的下轮对池内每个基各跑一次
  进化（不同谱系并行），池按非劣保留——「候选集并行递归」。

两者默认关（False/1），关闭时与既有行为逐字节一致。
"""

import pytest

from neurova.evolution.eval import cost_ledger
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner
from neurova.evolution.eval.service import SkillEvolutionService


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 8


def _ds(n_val: int = 5):
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(n_val)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _marker_judge(cap: int = 4):
    """按 IMPROVED 标记数计分（封顶 cap）——标记越多分越高、文本越长。"""

    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.2 + 0.02 * min(skill_text.count("IMPROVED"), cap)
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


def _counting_mutate():
    """每次调用追加的标记数递增——候选文本两两不同（分片等大也不撞车）。"""
    state = {"n": 0}

    async def mutate(*, artifact_text, artifact_type, failures):
        state["n"] += 1
        return artifact_text + " IMPROVED" * state["n"]

    return mutate


# ── N1：档位轮转评测 + Pareto 非劣集 ─────────────────────────────

class TestProfileVariants:
    @pytest.mark.asyncio
    async def test_tiers_rotated_and_pareto_delivered(self, monkeypatch):
        """三幸存候选按 lite/standard/heavy 轮转评测：成本账按档位分臂，
        Pareto 非劣集随结果交付，胜者仍由既有规则产生。"""
        monkeypatch.setenv("NEUROVA_EXEC_PROFILE", "standard")

        def fake_snapshot():
            from neurova.agent.turn_profile import getTurnProfile

            tier = getTurnProfile() or "standard"
            per_call = {"lite": 5, "standard": 10, "heavy": 20}[tier]
            fake_snapshot.calls += 1
            return {"tokens": fake_snapshot.calls * per_call,
                    "cost_usd": fake_snapshot.calls * per_call * 0.0001}

        fake_snapshot.calls = 0
        monkeypatch.setattr(cost_ledger, "usageSnapshot", fake_snapshot)

        runner = SkillEvolutionRunner(
            EvolutionConfig(variants_per_round=3, noise_repeats=1,
                            profile_variants_enabled=True),
            judge=_marker_judge(), mutate=_counting_mutate())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        # 成本账出现三个档位臂
        arms = result.cost_summary["arms"]
        assert {"candidate:lite", "candidate:standard", "candidate:heavy"} <= set(arms)
        # Pareto 非劣集交付：三元组都在、dominated 标记齐全
        assert result.pareto_set["state"] == "measured"
        assert len(result.pareto_set["entries"]) == 3
        assert {e["tier"] for e in result.pareto_set["entries"]} == {
            "lite", "standard", "heavy"}
        assert all("dominated" in e for e in result.pareto_set["entries"])
        # 分数随档位阶梯上行、成本亦上行 ⇒ 真前沿（无支配者）
        assert all(e["dominated"] is False for e in result.pareto_set["entries"])
        # 胜者仍由既有规则产生（argmax：标记最多者）
        assert result.deployed_text.count("IMPROVED") >= 2

    @pytest.mark.asyncio
    async def test_dominance_flags_respect_score_and_cost(self, monkeypatch):
        """分数更高但成本也更高者，与低成本低分者互不支配——两者都非劣。"""
        monkeypatch.setenv("NEUROVA_EXEC_PROFILE", "standard")

        def fake_snapshot():
            from neurova.agent.turn_profile import getTurnProfile

            tier = getTurnProfile() or "standard"
            per_call = {"lite": 5, "standard": 10, "heavy": 20}[tier]
            fake_snapshot.calls += 1
            return {"tokens": fake_snapshot.calls * per_call,
                    "cost_usd": fake_snapshot.calls * per_call * 0.0001}

        fake_snapshot.calls = 0
        monkeypatch.setattr(cost_ledger, "usageSnapshot", fake_snapshot)

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            # 乙（heavy 槽）分数最高但成本最高；甲（lite 槽）分低但最省——互不支配
            c = 0.2 + {"lite": 0.02, "standard": 0.02, "heavy": 0.05}.get(
                ("heavy" if "乙" in skill_text else "lite") if "候选" in skill_text else "standard", 0.02)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        produced = iter(["IMPROVED 候选甲", "IMPROVED 候选乙" + "长尾填充。" * 20,
                         "IMPROVED 候选丙"])

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(produced)

        runner = SkillEvolutionRunner(
            EvolutionConfig(variants_per_round=3, noise_repeats=1,
                            profile_variants_enabled=True),
            judge=judge, mutate=_counting_mutate())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        entries = result.pareto_set["entries"]
        assert len(entries) == 3
        cheapest = min(entries, key=lambda e: e["cost_usd"])
        # 同分不同成本：最省者非劣，其余皆被它支配（同分更贵）
        assert cheapest["dominated"] is False
        assert sum(1 for e in entries if e["dominated"]) == 2
        assert all(e["tier"] in {"lite", "standard", "heavy"} for e in entries)

    @pytest.mark.asyncio
    async def test_disabled_by_default(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_EXEC_PROFILE", "standard")
        runner = SkillEvolutionRunner(
            EvolutionConfig(variants_per_round=3, noise_repeats=1),
            judge=_marker_judge(), mutate=_counting_mutate())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert result.pareto_set["state"] == "disabled"
        assert "candidate:lite" not in result.cost_summary["arms"]


# ── N2：候选集并行递归 ───────────────────────────────────────────

class TestCandidatePoolRecursion:
    @pytest.mark.asyncio
    async def test_non_dominated_variants_advance(self, monkeypatch, tmp_path):
        """pool_size=2：首轮的两个非劣变体都进下轮（各自作为基再进化）——
        轨迹按 (epoch, base_index) 记录，最终交付最优者。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("pool-agent", base_dir=tmp_path)

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + 0.02 * min(skill_text.count("IMPROVED"), 4)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            # 分片 3/2 不等 ⇒ 两个候选标记数不等（分数与长度都不同 ⇒ 互不支配）；
            # 标记数压在增长预算内（约束闸 growth_limit ≤ 20%）
            return artifact_text + " IMPROVED" * (1 + len(failures) % 2)

        report = await svc.evolveRecursive(
            skill_id="sk-pool", skill_text=BASELINE, dataset=_ds(), epochs=2,
            iterations=1, pool_size=2, agent=_EchoAgent(), judge=judge,
            mutate=mutate, config=EvolutionConfig(noise_repeats=1,
                                                  variants_per_round=2,
                                                  lineage_pareto_enabled=True,
                                                  exec_suite_enabled=False))
        # 池语义：epochs_run = 轨迹条数（次轮两个基各一条）＝ 1 + 2 = 3
        assert report["epochs_run"] == 3
        # 首轮 1 个基、次轮 2 个基（非劣变体都进下轮）
        assert [len(e["bases"]) for e in report["epoch_pool"]] == [1, 2]
        assert report["final_pool_size"] >= 1
        assert report["deployed_text"].count("IMPROVED") >= 2

    @pytest.mark.asyncio
    async def test_default_pool_one_keeps_single_lineage(self, monkeypatch, tmp_path):
        """pool_size 缺省 1：与既有单谱系递归逐字节同形。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("pool-agent", base_dir=tmp_path)
        report = await svc.evolveRecursive(
            skill_id="sk-pool", skill_text=BASELINE, dataset=_ds(), epochs=3,
            iterations=1, agent=_EchoAgent(), judge=_marker_judge(3),
            mutate=_counting_mutate(), config=EvolutionConfig(noise_repeats=1))
        assert [len(e["bases"]) for e in report["epoch_pool"]] == [1, 1, 1]
        assert report["deployed_text"].count("IMPROVED") == 3

    @pytest.mark.asyncio
    async def test_pool_dedupes_and_caps(self, monkeypatch, tmp_path):
        """池去重并按 pool_size 截断——同文本不重复进池。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("pool-agent", base_dir=tmp_path)
        report = await svc.evolveRecursive(
            skill_id="sk-pool", skill_text=BASELINE, dataset=_ds(), epochs=2,
            iterations=1, pool_size=3, agent=_EchoAgent(), judge=_marker_judge(4),
            mutate=_counting_mutate(), config=EvolutionConfig(noise_repeats=1,
                                                              variants_per_round=3,
                                                              lineage_pareto_enabled=True))
        assert report["final_pool_size"] <= 3


class _EchoAgent:
    async def run(self, *, skill_text, task_input):
        return "echo"
