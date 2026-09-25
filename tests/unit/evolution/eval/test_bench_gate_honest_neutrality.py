"""bench_gate 的中性必须是**唯一**的中性——不得由注册表派生「假咬合」。

立项锚点（Issue #46 收口复核，实测复现）：

`make_eval_harness_gate` 度量的是四族可优化参数（tool_memory / sleep /
emotion / experience）的**行为地板**。技能正文候选不触及这些参数，所以
"文本候选 → gain 恒 0"是**构造成立**的事实，门只能诚实标注中性。

但 `_registry_apply_fn` 造了一条另一条路：从 `orchestrator.agent._skill_registry`
取注册表，把候选正文挂进各条目的 `config["context_template"]`，据此把
`gate.neutral` 改写成 False（"咬合"）。实测该通道有三个致命问题：

1. **假咬合**：换正文不位移四族参数 → gain 依然恒 0.0，从未咬合过；把
   `neutral` 从 True 改成 False 只是把"这道门没咬合"的可审计痕迹抹掉，
   比诚实的 neutral 更坏（不得把"没量出来"冒充"测过了"）。
2. **恢复是 no-op（真 bug）**：`snapshot = dict(entries)` 是**浅**拷贝，
   快照里的 entry 与现役 entry 是同一对象；就地改写 `config` 后再
   `entries.update(snapshot)` 恢复的仍是那份被改过的内容。实测：
   apply('CAND') → restore() → 条目 config 仍为 'CAND'。
   也就是说这条门一旦真被接线，会**永久改写技能正文**。
3. **零生产调用**：`make_skill_evolution_runner()` 全程无参调用
   `make_eval_harness_gate()`，`_registry_apply_fn` 一次都不会被执行到
   —— 缺陷因此从未暴露。

故本轮收口：删掉这条派生通道，让"apply_fn 只能由调用方能证明位移了参数族的
通道显式提供"，中性理由（`neutral_reason`）保持可审计。
"""

import pytest

from neurova.evolution.eval.bench_gate import (
    NEUTRAL_REASON_MEASUREMENT_BLIND,
    NEUTRAL_REASON_NO_APPLY_FN,
    make_eval_harness_gate,
)

STEPS = [{"tool": "file_read", "params": {"path": "a.txt"}}]


class _RegEntry:
    """被写正文的技能条目替身（只有 config 参与语义）。"""

    def __init__(self, text):
        self.config = {"context_template": text}


class _Registry:
    def __init__(self):
        self._skills = {"s1": _RegEntry("OLD")}


class _Orchestrator:
    """形如 EvolutionOrchestrator：带 agent 与 integration_manager 两个面。"""

    def __init__(self):
        self.agent = type("A", (), {"_skill_registry": _Registry()})()
        self.integration_manager = None


class TestNoFakeEngagement:
    def test_registry_derived_apply_fn_is_gone(self):
        """不得再由技能注册表派生 apply_fn —— 那条路是假咬合。

        判据不是"函数名没了"，而是**行为**：给一个带 `agent._skill_registry`
        的编排器，门仍须如实标注没咬合。旧实现的 `neutral` 会被改写成 False。
        """
        gate = make_eval_harness_gate(orchestrator=_Orchestrator())
        assert getattr(gate, "neutral", False) is True, (
            "四族参数不因技能正文位移 ⇒ 门只能中性；把 neutral 改写成 False "
            "等于把『没量出来』冒充『测过了』"
        )
        assert getattr(gate, "neutral_reason", "") == NEUTRAL_REASON_NO_APPLY_FN

    def test_registry_derived_channel_does_not_mutate_skill_text(self):
        """派生通道若真被接线会**永久改写**技能正文（恢复是 no-op）——不得存在。"""
        orch = _Orchestrator()
        reg = orch.agent._skill_registry
        gate = make_eval_harness_gate(orchestrator=orch)
        gate("baseline", "CANDIDATE")
        assert reg._skills["s1"].config["context_template"] == "OLD", (
            "门跑完必须不留脏状态；旧实现 restore 是浅拷贝 no-op，正文被永久改成候选"
        )

    def test_explicit_apply_fn_still_engages(self):
        """显式提供能位移参数族的 apply_fn 时，门仍须真咬合（收口不得把活路堵死）。

        这里必须给**完整四族参数**：`RSIEvalHarness` 在参数族缺项时自报
        `measurement_blind`（score=None），门按中性处理——那是既有诚实语义
        （工单 007），不是本处要断言的对象。
        """
        state = {"good": True}

        def provider():
            if state["good"]:
                return {"tool_memory": {"success_bonus": 0.1, "failure_penalty": 0.05,
                                        "decay_rate": 0.1, "muscle_memory_threshold": 0.6}}
            return {"tool_memory": {"success_bonus": 0.0, "failure_penalty": 0.0,
                                    "decay_rate": 0.0, "muscle_memory_threshold": 0.6}}

        def apply_fn(candidate_text):
            state["good"] = False
            return lambda: state.update(good=True)

        gate = make_eval_harness_gate(live_params_provider=provider, apply_fn=apply_fn)
        assert getattr(gate, "neutral", True) is False
        assert gate("baseline", "candidate") < 0, "参数劣化必须被门咬出来"

    def test_factory_default_stays_honestly_neutral(self, monkeypatch):
        """装配层缺省保持诚实中性，且理由可审计。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        from neurova.evolution.eval.factory import make_skill_evolution_runner

        runner = make_skill_evolution_runner()
        gate = runner._bench_gate
        assert getattr(gate, "neutral", False) is True
        assert getattr(gate, "neutral_reason", "") == NEUTRAL_REASON_NO_APPLY_FN
        assert pytest.approx(0.0) == gate("a", "b")


class TestBlindMeasurementIsNotClaimedAsEngaged:
    """`neutral` 必须反映**本次调用**是否真的咬合，而不是"调用方能提供 apply_fn"。

    立项锚点：`gate.neutral` 原先只在构造期按 `apply_fn is None` 定死。于是
    "提供了 apply_fn、但活参数取不到（四族参数为空）→ harness 自报
    `measurement_blind`（score=None）→ 门按中性返回 0.0"这条路上，
    `neutral` 仍是 False、`neutral_reason` 仍是空串——对外长得和"真咬合且
    零增益"一模一样。这正是 `neutral_reason` 存在的理由（让审计能看出
    "这道门没咬合"），却在最需要它的那条路上失效。
    """

    def test_blind_call_reports_neutral_with_reason(self):
        gate = make_eval_harness_gate(apply_fn=lambda text: (lambda: None))
        assert getattr(gate, "neutral", True) is False, "构造期 apply_fn 存在 ⇒ 未调用前不预设中性"
        gain = gate("baseline", "candidate")
        assert gain == pytest.approx(0.0)
        assert getattr(gate, "neutral", False) is True, (
            "本轮读数不存在（参数族为空 ⇒ measurement_blind）⇒ 必须自报中性"
        )
        assert getattr(gate, "neutral_reason", "") == NEUTRAL_REASON_MEASUREMENT_BLIND

    def test_engaged_call_clears_neutral(self):
        """真咬合的一轮过后必须把中性标记清掉（标记随实际读数走）。"""

        def provider():
            return {"tool_memory": {"success_bonus": 0.1, "failure_penalty": 0.05,
                                    "decay_rate": 0.1, "muscle_memory_threshold": 0.6}}

        gate = make_eval_harness_gate(live_params_provider=provider,
                                      apply_fn=lambda text: (lambda: None))
        assert gate("baseline", "candidate") == pytest.approx(0.0)
        assert getattr(gate, "neutral", True) is False, "有读数 ⇒ 不得再自称中性"
        assert getattr(gate, "neutral_reason", "x") == ""


class TestNeutralityReachesTheRunResult:
    """中性必须进运行结果面——否则"这道门没咬合"只在门内自说自话。

    立项锚点：`neutral` / `neutral_reason` 修诚实之后，全仓**零读取方**
    （grep 只命中定义处与测试）——门如实标注了"没咬合"，但 `EvolutionRunResult`
    只把它当 `bench_gain=0.0` 收下，与"真咬合且零增益"报告完全同形。
    本类锁住写入→读取→外露这条闭环：跑完一轮后，运行结果必须带上门的
    中性判定与理由。
    """

    @pytest.mark.asyncio
    async def test_blind_bench_is_surfaced_on_result(self):
        from neurova.evolution.eval.config import EvolutionConfig
        from neurova.evolution.eval.dataset import EvalDataset, EvalExample
        from neurova.evolution.eval.fitness import FitnessScore
        from neurova.evolution.eval.runner import SkillEvolutionRunner

        class _Judge:
            async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
                c = 0.9 if "IMPROVED" in skill_text else 0.3
                return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        class _Agent:
            async def run(self, *, skill_text, task_input):
                return skill_text

        async def _mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        ds = EvalDataset(
            train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(3)],
            val=[EvalExample(task_input=f"v{i}", expected_behavior="r") for i in range(2)],
            holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
        )
        cfg = EvolutionConfig(iterations=1, min_improvement=0.0)
        runner = SkillEvolutionRunner(
            cfg, judge=_Judge(), agent=_Agent(), mutate=_mutate,
            bench_gate=make_eval_harness_gate(apply_fn=lambda text: (lambda: None)),
        )
        result = await runner.run(baseline_text="BASE", artifact_type="skill", dataset=ds)
        assert getattr(result, "bench_neutral", False) is True, (
            "门自报中性 ⇒ 运行结果必须带上该判定，否则对外与『真咬合且零增益』同形"
        )
        assert getattr(result, "bench_neutral_reason", "") == NEUTRAL_REASON_MEASUREMENT_BLIND
        assert result.to_dict()["bench_neutral"] is True
        assert result.to_dict()["bench_neutral_reason"] == NEUTRAL_REASON_MEASUREMENT_BLIND

    @pytest.mark.asyncio
    async def test_engaged_bench_reports_not_neutral(self):
        from neurova.evolution.eval.config import EvolutionConfig
        from neurova.evolution.eval.dataset import EvalDataset, EvalExample
        from neurova.evolution.eval.fitness import FitnessScore
        from neurova.evolution.eval.runner import SkillEvolutionRunner

        class _Judge:
            async def score(self, *, task_input, expected_behavior, output, skill_text, **kw):
                c = 0.9 if "IMPROVED" in skill_text else 0.3
                return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        class _Agent:
            async def run(self, *, skill_text, task_input):
                return skill_text

        async def _mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        ds = EvalDataset(
            train=[EvalExample(task_input=f"t{i}", expected_behavior="r") for i in range(3)],
            val=[EvalExample(task_input=f"v{i}", expected_behavior="r") for i in range(2)],
            holdout=[EvalExample(task_input=f"h{i}", expected_behavior="r") for i in range(2)],
        )

        def provider():
            return {"tool_memory": {"success_bonus": 0.1, "failure_penalty": 0.05,
                                    "decay_rate": 0.1, "muscle_memory_threshold": 0.6}}

        cfg = EvolutionConfig(iterations=1, min_improvement=0.0)
        runner = SkillEvolutionRunner(
            cfg, judge=_Judge(), agent=_Agent(), mutate=_mutate,
            bench_gate=make_eval_harness_gate(live_params_provider=provider,
                                              apply_fn=lambda text: (lambda: None)),
        )
        result = await runner.run(baseline_text="BASE", artifact_type="skill", dataset=ds)
        assert getattr(result, "bench_neutral", True) is False
        assert result.to_dict()["bench_neutral"] is False
