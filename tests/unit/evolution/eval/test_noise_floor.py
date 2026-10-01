"""P0-1 评测噪声地板 — 校准与接受判据升级的红灯测试。

RRSI 对齐：接受判据阈值 = max(min_improvement, δ)，δ 由同一基线在同批用例上
重复评测实测（δ = z·sd）。未校准时行为与旧版逐字节一致（增量不降级）。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2


def _ds(n_holdout: int = 2) -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(n_holdout)],
    )


def _judge_with_gain(gain: float):
    """脚本判分器：基线 0.2，含 IMPROVED 标记的文本 0.2+gain（确定性，无噪声）。"""

    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.2 + gain if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


async def _mutate_appends_improved(*, artifact_text, artifact_type, failures):
    return artifact_text + "\nIMPROVED"


def _runner(config: EvolutionConfig) -> SkillEvolutionRunner:
    return SkillEvolutionRunner(
        config, judge=_judge_with_gain(0.0), mutate=_mutate_appends_improved,
    )


class TestRunnerNoiseFloor:
    @pytest.mark.asyncio
    async def test_band_delta_raises_accept_threshold(self):
        """增益 0.012 > min_improvement(0.01) 但 < δ(0.02) → 拒绝，阈值外露 δ。"""
        cfg = EvolutionConfig(noise_band_delta=0.02)
        runner = SkillEvolutionRunner(
            cfg, judge=_judge_with_gain(0.012), mutate=_mutate_appends_improved,
        )
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill", dataset=_ds())
        assert result.rejected
        assert result.reject_reason == "no_improvement"
        assert result.accept_threshold == pytest.approx(0.02)
        assert result.noise_band["delta"] == pytest.approx(0.02)
        assert result.noise_band["method"] == "config"

    @pytest.mark.asyncio
    async def test_gain_above_band_accepted(self):
        cfg = EvolutionConfig(noise_band_delta=0.02)
        runner = SkillEvolutionRunner(
            cfg, judge=_judge_with_gain(0.03), mutate=_mutate_appends_improved,
        )
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill", dataset=_ds())
        assert not result.rejected
        assert result.accept_threshold == pytest.approx(0.02)

    @pytest.mark.asyncio
    async def test_uncalibrated_falls_back_to_min_improvement(self):
        """未校准（默认）时：阈值 = min_improvement，noise_band 为空 dict，旧行为不变。"""
        runner = _runner(EvolutionConfig())
        result = await runner.run(
            baseline_text=BASELINE, artifact_type="skill", dataset=_ds(),
        )
        assert result.accept_threshold == pytest.approx(0.01)
        assert result.noise_band == {}
        # 阈值真正咬合：0.005 的"增益"仍被拒
        runner_low = SkillEvolutionRunner(
            EvolutionConfig(), judge=_judge_with_gain(0.005), mutate=_mutate_appends_improved,
        )
        low = await runner_low.run(baseline_text=BASELINE, artifact_type="skill", dataset=_ds())
        assert low.rejected and low.reject_reason == "no_improvement"

    @pytest.mark.asyncio
    async def test_injected_band_wins_over_config(self):
        """run(noise_band=...) 注入的校准产物优先于 config.noise_band_delta。"""
        from neurova.evolution.eval.calibration import NoiseBand

        cfg = EvolutionConfig(noise_band_delta=0.005)
        runner = SkillEvolutionRunner(
            cfg, judge=_judge_with_gain(0.012), mutate=_mutate_appends_improved,
        )
        band = NoiseBand(delta=0.02, sd_null=0.01, z=2.0,
                         method="repeated_baseline_evals", n_repeats=3,
                         scores=[0.2, 0.21, 0.2])
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), noise_band=band)
        assert result.rejected and result.reject_reason == "no_improvement"
        assert result.accept_threshold == pytest.approx(0.02)
        assert result.noise_band["method"] == "repeated_baseline_evals"


class TestCalibration:
    async def _seq_eval(self, scores: list[float]):
        calls = {"n": 0}

        async def evaluate_fn(skill_text, examples, artifact_type):
            v = scores[calls["n"]]
            calls["n"] += 1
            return v

        return evaluate_fn, calls

    @pytest.mark.asyncio
    async def test_delta_is_z_times_sd(self):
        from neurova.evolution.eval.calibration import calibrate_noise_band

        evaluate_fn, calls = await self._seq_eval([0.50, 0.54, 0.52])
        band = await calibrate_noise_band(
            baseline_text=BASELINE, artifact_type="skill", examples=_ds().holdout,
            evaluate_fn=evaluate_fn, z=2.0, repeats=3,
        )
        # sd([0.50,0.54,0.52]) = 0.02（样本标准差）→ δ = 0.04
        assert band.delta == pytest.approx(0.04, abs=1e-9)
        assert band.sd_null == pytest.approx(0.02, abs=1e-9)
        assert band.method == "repeated_baseline_evals"
        assert band.n_repeats == 3 and calls["n"] == 3
        assert band.scores == pytest.approx([0.50, 0.54, 0.52])

    @pytest.mark.asyncio
    async def test_deterministic_eval_gives_zero_delta(self):
        from neurova.evolution.eval.calibration import calibrate_noise_band

        evaluate_fn, _ = await self._seq_eval([0.2, 0.2, 0.2])
        band = await calibrate_noise_band(
            baseline_text=BASELINE, artifact_type="skill", examples=_ds().holdout,
            evaluate_fn=evaluate_fn, z=2.0, repeats=3,
        )
        assert band.delta == 0.0 and band.sd_null == 0.0

    @pytest.mark.asyncio
    async def test_repeats_below_two_is_uncalibrated(self):
        from neurova.evolution.eval.calibration import calibrate_noise_band

        evaluate_fn, calls = await self._seq_eval([0.2])
        band = await calibrate_noise_band(
            baseline_text=BASELINE, artifact_type="skill", examples=_ds().holdout,
            evaluate_fn=evaluate_fn, z=2.0, repeats=1,
        )
        assert band.delta == 0.0 and band.method == "uncalibrated"
        assert calls["n"] == 0  # 不花评测预算

    @pytest.mark.asyncio
    async def test_empty_examples_is_uncalibrated(self):
        from neurova.evolution.eval.calibration import calibrate_noise_band

        evaluate_fn, calls = await self._seq_eval([0.2, 0.2])
        band = await calibrate_noise_band(
            baseline_text=BASELINE, artifact_type="skill", examples=[],
            evaluate_fn=evaluate_fn, z=2.0, repeats=3,
        )
        assert band.delta == 0.0 and calls["n"] == 0


class TestBandCache:
    def test_round_trip_by_fingerprint(self, tmp_path):
        from neurova.evolution.eval.calibration import (
            NoiseBand,
            load_cached_band,
            save_cached_band,
        )

        cache = tmp_path / "calibration.json"
        band = NoiseBand(delta=0.04, sd_null=0.02, z=2.0,
                         method="repeated_baseline_evals", n_repeats=3,
                         scores=[0.5, 0.54, 0.52])
        save_cached_band(cache, "fp-aaa", band)
        loaded = load_cached_band(cache, "fp-aaa")
        assert loaded is not None and loaded.delta == pytest.approx(0.04)
        assert loaded.method == "repeated_baseline_evals"
        assert load_cached_band(cache, "fp-other") is None

    def test_fingerprint_order_insensitive_and_distinct(self):
        from neurova.evolution.eval.calibration import dataset_fingerprint

        a = EvalExample(task_input="任务一", expected_behavior="输出 JSON")
        b = EvalExample(task_input="任务二", expected_behavior="输出表格")
        assert dataset_fingerprint([a, b]) == dataset_fingerprint([b, a])
        assert dataset_fingerprint([a, b]) != dataset_fingerprint([a])

    def test_cache_corrupt_returns_none(self, tmp_path):
        from neurova.evolution.eval.calibration import load_cached_band

        cache = tmp_path / "calibration.json"
        cache.write_text("不是 JSON", encoding="utf-8")
        assert load_cached_band(cache, "fp-aaa") is None


class TestServiceWiring:
    async def _judge(self, *, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.9 if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    @pytest.mark.asyncio
    async def test_service_calibrates_when_repeats_gt_one(self, tmp_path, monkeypatch):
        """noise_repeats>1：service 自动校准并落指纹缓存。"""
        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("agent-x", base_dir=tmp_path / "evo")
        cfg = EvolutionConfig(noise_repeats=2)
        result, _ = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=None, judge=self._judge, mutate=_mutate_appends_improved, config=cfg,
        )
        assert not result.rejected
        assert (tmp_path / "evo" / "calibration.json").exists()
        assert result.noise_band.get("method") == "repeated_baseline_evals"

    @pytest.mark.asyncio
    async def test_service_default_skips_calibration(self, tmp_path, monkeypatch):
        """默认 noise_repeats=0：不花校准预算，无缓存文件，行为与旧版一致。"""
        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("agent-y", base_dir=tmp_path / "evo")
        result, _ = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=None, judge=self._judge, mutate=_mutate_appends_improved,
        )
        assert not result.rejected
        assert not (tmp_path / "evo" / "calibration.json").exists()
        assert result.noise_band == {}

    @pytest.mark.asyncio
    async def test_calibration_failure_degrades_honestly(self, tmp_path, monkeypatch):
        """校准失败（judge 故障）→ 无带（回退 min_improvement），进化走既有
        judge_unavailable 拒绝语义，不因校准产生新异常形态。"""

        class _BrokenJudge:
            async def score(self, **kw):
                raise RuntimeError("judge boom")

        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("agent-z", base_dir=tmp_path / "evo")
        cfg = EvolutionConfig(noise_repeats=2)
        result, _ = await svc.evolve(
            skill_id="s1", skill_text=BASELINE, dataset=_ds(),
            agent=None, judge=_BrokenJudge(), mutate=_mutate_appends_improved, config=cfg,
        )
        assert result.judge_available is False
        assert result.rejected and result.reject_reason == "judge_unavailable"
        assert not (tmp_path / "evo" / "calibration.json").exists()
