"""HN2/HC2 可执行测试判据层 —— 红灯测试。

HarnessPro 对照（2026-11-13）断点 HN2：合成评测停在 rubric 文本，判分靠
LLM judge——没有可执行断言套件。本文件钉五件事：

1. 断言引擎：七种 op（contains/not_contains/equals/regex/non_empty/
   length_le/length_ge）的确定性判定，非法 op 出声；
2. 套件冻结：suite_hash 对用例集稳定，isUsable 判可用性；
3. TestSynthesizer：从技能契约+参考任务生成用例（解析/校验/限量/哈希），
   LLM 失败 ⇒ 空套件（不可用），绝不臆造；
4. run_exec_suite：输出缺失 ⇒ unevidenced（不是通过）；pass_rate 口径；
5. runner 集成：套件作为独立判据层——基线/胜者各跑一遍，候选通过率
   低于基线 ⇒ exec_suite_regression 拒绝；套件不可用 ⇒ 诚实回退 judge，
   运行不中断。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.exec_suite import (
    ExecCase,
    ExecutableTestSuite,
    TestSynthesizer,
    evaluateAssertions,
    run_exec_suite,
)
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 4


def _ds() -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _judge_with_gain(gain: float):
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.2 + gain if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


def _echo_mutate():
    async def mutate(*, artifact_text, artifact_type, failures):
        return artifact_text + " IMPROVED"
    return mutate


# ── 1. 断言引擎 ─────────────────────────────────────────────────

class TestAssertionEngine:
    def test_all_ops_deterministic(self):
        assert evaluateAssertions("Done: 42 items", [
            {"op": "non_empty", "value": ""},
            {"op": "contains", "value": "42"},
            {"op": "not_contains", "value": "error"},
            {"op": "regex", "value": r"Done:\s+\d+"},
            {"op": "length_ge", "value": 5},
            {"op": "length_le", "value": 100},
        ]) == []

    def test_failures_reported_with_reasons(self):
        failures = evaluateAssertions("short", [
            {"op": "contains", "value": "missing-token"},
            {"op": "length_ge", "value": 100},
            {"op": "equals", "value": "exact"},
        ])
        assert len(failures) == 3
        assert any("contains" in f for f in failures)

    def test_unknown_op_is_a_failure_not_a_crash(self):
        failures = evaluateAssertions("x", [{"op": "exec_python", "value": "os.system"}])
        assert len(failures) == 1
        assert "未知" in failures[0] or "unknown" in failures[0].lower()

    def test_case_insensitive_contains(self):
        assert evaluateAssertions("OK", [{"op": "contains", "value": "ok"}]) == []


# ── 2/3. 套件冻结与合成器 ────────────────────────────────────────

def _suite_from(cases: list[dict], *, skill_id: str = "sk") -> ExecutableTestSuite:
    return TestSynthesizer._build(skill_id=skill_id, raw_cases=cases, source="test")


class TestSuiteFreezeAndSynthesizer:
    def test_hash_stable_and_usable(self):
        cases = [{"task_input": "t", "assertions": [{"op": "contains", "value": "x"}]}]
        s1 = _suite_from(cases)
        s2 = _suite_from(cases)
        assert s1.suite_hash == s2.suite_hash
        assert s1.isUsable()
        empty = _suite_from([])
        assert not empty.isUsable()

    def test_synthesizer_parses_validates_and_caps(self):
        raw = [
            {"task_input": f"task{i}", "assertions": [{"op": "contains", "value": "ok"}],
             "description": "d"}
            for i in range(10)
        ]
        raw.append({"task_input": "bad", "assertions": [{"op": "exec_python", "value": "x"}]})
        raw.append({"task_input": "", "assertions": [{"op": "contains", "value": "x"}]})
        suite = TestSynthesizer._build(skill_id="sk", raw_cases=raw, source="test")
        assert len(suite.cases) == 10  # 非法 op 与空任务被剔除，10 条合法用例保留
        assert all(c.assertions for c in suite.cases)

    @pytest.mark.asyncio
    async def test_synthesizer_llm_failure_honest_empty(self):
        async def llm_fail(messages, model):
            return {"success": False, "error": "no llm"}
        synth = TestSynthesizer(EvolutionConfig(), llm_call=llm_fail)
        suite = await synth.generate(skill_text=BASELINE, reference_tasks=["t1", "t2"])
        assert not suite.isUsable()

    @pytest.mark.asyncio
    async def test_synthesizer_uses_injected_llm_and_caps_size(self):
        raw = [{"task_input": f"task{i}", "assertions": [{"op": "contains", "value": "ok"}]}
               for i in range(8)]

        async def llm_ok(messages, model):
            import json

            return {"success": True, "response": json.dumps(raw, ensure_ascii=False)}

        cfg = EvolutionConfig(exec_suite_size=4)
        synth = TestSynthesizer(cfg, llm_call=llm_ok)
        suite = await synth.generate(skill_text=BASELINE, reference_tasks=["t1"])
        assert len(suite.cases) == 4  # 配置限量
        assert suite.suite_hash


# ── 4. 执行器 ───────────────────────────────────────────────────

class TestRunExecSuite:
    def test_outputs_missing_is_unevidenced_not_pass(self):
        suite = _suite_from([
            {"task_input": "a", "assertions": [{"op": "contains", "value": "ok"}]},
            {"task_input": "b", "assertions": [{"op": "contains", "value": "ok"}]},
        ])
        readout = run_exec_suite(suite, {"a": "ok output"})  # b 缺输出
        # 部分跑到 ⇒ partially_measured（分母不一致，门不判这种形态）
        assert readout["state"] == "partially_measured"
        assert readout["total"] == 2
        assert readout["evaluated"] == 1
        assert readout["passed"] == 1
        assert readout["pass_rate"] == pytest.approx(1.0)  # 分母=已评测数
        assert readout["cases"][1]["state"] == "unevidenced"

    def test_pass_rate_counts_failures(self):
        suite = _suite_from([
            {"task_input": "a", "assertions": [{"op": "contains", "value": "ok"}]},
            {"task_input": "b", "assertions": [{"op": "contains", "value": "ok"}]},
        ])
        readout = run_exec_suite(suite, {"a": "ok", "b": "nope"})
        assert readout["state"] == "measured"
        assert readout["passed"] == 1
        assert readout["pass_rate"] == pytest.approx(0.5)
        assert readout["cases"][1]["passed"] is False


# ── 5. runner 集成：独立判据层 + 非回归门 ────────────────────────

def _suite() -> ExecutableTestSuite:
    return _suite_from([
        {"task_input": "x1", "assertions": [{"op": "contains", "value": "GOOD"}]},
        {"task_input": "x2", "assertions": [{"op": "contains", "value": "GOOD"}]},
    ])


class _RoutedAgent:
    """基线输出不带 GOOD（断言全挂）、候选输出带 GOOD（断言全过）——
    与 judge 增益方向一致。reverse=True 反转（候选改坏断言面）。"""

    def __init__(self, reverse: bool = False):
        self._reverse = reverse

    async def run(self, *, skill_text: str, task_input: str) -> str:
        improved = "IMPROVED" in skill_text
        good = improved != self._reverse
        return f"GOOD {task_input}" if good else f"BAD {task_input}"


class TestRunnerExecSuiteGate:
    @pytest.mark.asyncio
    async def test_exec_improvement_passes_with_readout(self):
        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_judge_with_gain(0.02), mutate=_echo_mutate(),
            agent=_RoutedAgent())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), exec_suite=_suite())
        assert not result.rejected
        assert result.exec_suite["state"] == "measured"
        assert result.exec_suite["baseline_pass_rate"] == pytest.approx(0.0)
        assert result.exec_suite["candidate_pass_rate"] == pytest.approx(1.0)
        assert result.exec_suite["suite_hash"]

    @pytest.mark.asyncio
    async def test_exec_regression_rejected(self):
        """judge 面涨了、断言面被改坏 ⇒ exec_suite_regression 拒绝。"""
        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_judge_with_gain(0.02), mutate=_echo_mutate(),
            agent=_RoutedAgent(reverse=True))
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), exec_suite=_suite())
        assert result.rejected
        assert result.reject_reason == "exec_suite_regression"
        assert result.deployed_text == BASELINE
        assert result.exec_suite["candidate_pass_rate"] == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_unusable_suite_degrades_honestly(self):
        """套件不可用 ⇒ 诚实回退 judge（不中断、不臆造通过）。"""
        runner = SkillEvolutionRunner(
            EvolutionConfig(), judge=_judge_with_gain(0.02), mutate=_echo_mutate(),
            agent=_RoutedAgent())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), exec_suite=_suite_from([]))
        assert not result.rejected
        assert result.exec_suite["state"] == "unavailable"

    @pytest.mark.asyncio
    async def test_disabled_by_config(self):
        runner = SkillEvolutionRunner(
            EvolutionConfig(exec_suite_enabled=False), judge=_judge_with_gain(0.02),
            mutate=_echo_mutate(), agent=_RoutedAgent())
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), exec_suite=_suite())
        assert not result.rejected
        assert result.exec_suite["state"] == "disabled"
