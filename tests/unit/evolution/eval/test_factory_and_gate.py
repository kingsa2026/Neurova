"""Wave 2 — benchmark 门接线与装配工厂测试。"""

import pytest

from neurova.evolution.eval.bench_gate import make_eval_harness_gate
from neurova.evolution.eval.factory import make_skill_evolution_runner


class TestEvalHarnessGate:
    def test_gate_returns_float_and_runs_real_harness(self):
        gate = make_eval_harness_gate(live_params_provider=lambda: {})
        gain = gate("baseline", "candidate")
        assert isinstance(gain, float)
        # 同一参数快照跑两遍,确定性评测集 → delta 为 0
        assert gain == pytest.approx(0.0)

    def test_gate_neutral_without_any_provider(self):
        gate = make_eval_harness_gate()
        assert gate("a", "b") == pytest.approx(0.0)

    def test_gate_detects_param_regression(self):
        """给牙齿的语义:apply_fn 把候选挂进系统致参数劣化 → gain < 0;
        恢复后被调用(门绝不留脏状态)。"""
        state = {"good": True}
        restored = {"called": False}

        def provider():
            if state["good"]:
                return {"tool_memory": {"success_bonus": 0.1, "failure_penalty": 0.05,
                                        "decay_rate": 0.1, "muscle_memory_threshold": 0.6}}
            return {"tool_memory": {"success_bonus": 0.0, "failure_penalty": 0.0,
                                    "decay_rate": 0.0, "muscle_memory_threshold": 0.6}}

        def apply_fn(candidate_text):
            state["good"] = False  # 候选劣化参数族

            def restore():
                state["good"] = True
                restored["called"] = True

            return restore

        gate = make_eval_harness_gate(live_params_provider=provider, apply_fn=apply_fn)
        gain = gate("baseline", "bad-candidate")
        assert gain < 0.0, "候选致参数劣化 → 门必须咬合(负 gain)"
        assert restored["called"], "度量后必须恢复系统状态"

    def test_apply_fn_exception_does_not_skip_restore(self):
        state = {"good": True}

        def provider():
            return {}

        def apply_fn(candidate_text):
            def restore():
                state["good"] = True

            raise RuntimeError("度量前崩了")  # restore 未返回,状态本就未变

        gate = make_eval_harness_gate(live_params_provider=provider, apply_fn=apply_fn)
        with pytest.raises(RuntimeError):
            gate("a", "b")
        assert state["good"] is True

    def test_provider_failure_degrades_to_empty_params(self):
        def bad_provider():
            raise RuntimeError("boom")

        gate = make_eval_harness_gate(live_params_provider=bad_provider)
        assert gate("a", "b") == pytest.approx(0.0)


class TestFactory:
    def test_disabled_by_default_returns_none(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_TEXT_EVOLUTION", raising=False)
        assert make_skill_evolution_runner() is None

    def test_enabled_returns_wired_runner(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        runner = make_skill_evolution_runner()
        assert runner is not None
        # judge 已装配;constraints 已装配;bench_gate 为中性门(harness 可用)
        from neurova.evolution.eval.constraints import ConstraintValidator
        from neurova.evolution.eval.fitness import LLMJudge

        assert isinstance(runner.judge, LLMJudge)
        assert isinstance(runner._constraints, ConstraintValidator)
        assert callable(runner._bench_gate)

    def test_explicit_config_respected(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        from neurova.evolution.eval.config import EvolutionConfig

        cfg = EvolutionConfig(iterations=3, max_skill_size=999)
        runner = make_skill_evolution_runner(cfg)
        assert runner.config.iterations == 3
        assert runner.config.max_skill_size == 999
