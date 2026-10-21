"""N5：实验身份指纹与噪声带缓存键。"""

from types import SimpleNamespace

import pytest

from neurova.evolution.eval.calibration import experiment_fingerprint
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset


def _examples():
    return [
        SimpleNamespace(task_input="a", expected_behavior="A"),
        SimpleNamespace(task_input="b", expected_behavior="B"),
    ]


def _fingerprint(**overrides):
    args = dict(
        skill_id="sk",
        baseline_text="baseline",
        model_under_test="model-a",
        artifact_type="skill",
        examples=_examples(),
        config=EvolutionConfig(),
    )
    args.update(overrides)
    return experiment_fingerprint(**args)


def test_experiment_fingerprint_is_order_insensitive_and_config_sensitive():
    base = _fingerprint()
    assert base == _fingerprint()
    assert base == _fingerprint(examples=list(reversed(_examples())))
    assert base != _fingerprint(model_under_test="model-b")
    assert base != _fingerprint(baseline_text="baseline-v2")
    assert base != _fingerprint(examples=_examples()[:1])

    cfg = EvolutionConfig()
    cfg.min_improvement = 0.2
    assert base != _fingerprint(config=cfg)
    assert base != _fingerprint(config=EvolutionConfig(judge_fallback="off"))


def test_best_anchor_filters_by_experiment_fingerprint():
    from neurova.evolution.eval.service import best_anchor_from_ledger

    entries = [
        {"holdout_after": 0.9, "experiment_fingerprint": "old"},
        {"holdout_after": 0.5, "experiment_fingerprint": "current"},
        {"holdout_after": 0.7},
    ]
    assert best_anchor_from_ledger(entries, fingerprint="current") == 0.5
    assert best_anchor_from_ledger(entries, fingerprint="missing") is None
    assert best_anchor_from_ledger(entries) == 0.9


def test_evolution_pass_identity_changes_with_settings(tmp_path, monkeypatch):
    from neurova.evolution.evolution_settings import (
        evolutionJobIdentityRejected,
        evolutionPassIdentity,
        update_settings,
    )

    monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(tmp_path / "evolution_settings.json"))
    first = evolutionPassIdentity("agent")
    assert evolutionJobIdentityRejected({"identity": first}, "agent") is False
    assert evolutionJobIdentityRejected({"identity": "stale"}, "agent") is True
    assert evolutionJobIdentityRejected({}, "agent") is True

    update_settings(judge_model="judge-b")
    assert evolutionPassIdentity("agent") != first


@pytest.mark.asyncio
async def test_noise_band_cache_is_keyed_by_experiment_fingerprint(tmp_path):
    from neurova.evolution.eval.service import SkillEvolutionService

    class _Runner:
        def __init__(self):
            self.evaluations = 0
            self._run_eval_errors = 0

        async def _judge_available(self, *args, **kwargs):
            return True

        async def _evaluate_avg(self, baseline_text, examples, artifact_type):
            self.evaluations += 1
            return 0.5

    service = SkillEvolutionService("agent", base_dir=tmp_path)
    runner = _Runner()
    cfg = EvolutionConfig(noise_repeats=2)
    dataset = EvalDataset(holdout=_examples())

    first = await service._noise_band_for(
        cfg, runner, dataset, "skill", baseline_text="baseline", fingerprint="fp-a"
    )
    assert first is not None
    evaluations_after_first = runner.evaluations

    cached = await service._noise_band_for(
        cfg, runner, dataset, "skill", baseline_text="baseline", fingerprint="fp-a"
    )
    assert cached is not None
    assert runner.evaluations == evaluations_after_first

    await service._noise_band_for(
        cfg, runner, dataset, "skill", baseline_text="baseline", fingerprint="fp-b"
    )
    assert runner.evaluations > evaluations_after_first
