"""R4 轨迹联合诊断消费层 —— 红灯测试。

§10.2 R4：tool_trace/缺口证据/判分反馈已采集，但没有一层把它们聚合成
结构化诊断喂给变异器（HarnessPro 的 Trajectory Analyzer 形态）。本文件钉：

1. buildDiagnosis：按失败模式（归一化反馈首行）聚合——计数/占比/最差分/
   例证任务/环节证据并集，按次数降序（平次按模式名字典序，确定性）；
2. diagnosisDigest：渲染成变异器可读的紧凑文本（含模式/次数/例证）；
3. runner 把诊断随变异调用传入（mutate 签名接受时），空失败 ⇒ 空诊断；
4. ReflectiveMutator 提示含「联合诊断」段（有诊断时），无诊断时提示词与
   旧版逐字节一致。
"""

import json

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.failure_analysis import buildDiagnosis, diagnosisDigest
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.mutator import JudgeFailure
from neurova.evolution.eval.runner import SkillEvolutionRunner


def _f(task: str, feedback: str, score: float = 0.2, envs: list = None):
    return JudgeFailure(task_input=task, output="out", feedback=feedback,
                        score=score, environments=list(envs or []))


class TestBuildDiagnosis:
    def test_groups_by_normalized_pattern(self):
        failures = [
            _f("t1", "输出缺少必要的校验步骤", 0.1),
            _f("t2", "输出缺少必要的校验步骤", 0.2),
            _f("t3", "输出缺少必要的校验步骤", 0.3),
            _f("t4", "超时未返回结果", 0.0),
        ]
        entries = buildDiagnosis(failures)
        assert len(entries) == 2
        assert entries[0]["count"] == 3
        assert entries[0]["pattern"].startswith("输出缺少必要的校验步骤")
        assert entries[0]["worst_score"] == pytest.approx(0.1)
        assert set(entries[0]["tasks"]) == {"t1", "t2", "t3"}
        assert entries[1]["pattern"].startswith("超时未返回结果")

    def test_env_kinds_union(self):
        failures = [
            _f("t1", "模式甲", envs=["goal_gap"]),
            _f("t2", "模式甲", envs=["tool_failure"]),
        ]
        entries = buildDiagnosis(failures)
        assert set(entries[0]["env_kinds"]) == {"goal_gap", "tool_failure"}

    def test_digits_normalized_into_same_pattern(self):
        """反馈里的数字差异不拆分模式（同因不同参数算同一类）。"""
        failures = [
            _f("t1", "第 1 行校验失败"),
            _f("t2", "第 42 行校验失败"),
        ]
        assert len(buildDiagnosis(failures)) == 1

    def test_empty_failures_empty_diagnosis(self):
        assert buildDiagnosis([]) == []

    def test_deterministic_order(self):
        failures = [_f("t1", "模式乙"), _f("t2", "模式乙"),
                    _f("t3", "模式甲"), _f("t4", "模式甲")]
        entries = buildDiagnosis(failures)
        assert [e["count"] for e in entries] == [2, 2]
        assert entries[0]["pattern"] <= entries[1]["pattern"]


class TestDiagnosisDigest:
    def test_digest_contains_pattern_and_count(self):
        failures = [
            _f("任务一", "缺少语义校验", 0.1),
            _f("任务二", "缺少语义校验", 0.2),
        ]
        digest = diagnosisDigest(buildDiagnosis(failures))
        assert "缺少语义校验" in digest
        assert "2" in digest
        assert "任务一" in digest

    def test_empty_digest(self):
        assert diagnosisDigest([]) == ""


# ── 3/4. 消费接线：runner 传入 + mutator 渲染 ────────────────────

BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 4


def _ds():
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _judge():
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.2 + 0.02 if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="统一反馈：输出缺少语义校验")
    return judge


class TestDiagnosisWiring:
    @pytest.mark.asyncio
    async def test_runner_passes_diagnosis_to_mutate(self):
        seen: dict = {}

        async def mutate(*, artifact_text, artifact_type, failures, diagnosis=None):
            seen["diagnosis"] = diagnosis
            return artifact_text + " IMPROVED"

        runner = SkillEvolutionRunner(EvolutionConfig(noise_repeats=1),
                                      judge=_judge(), mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert seen["diagnosis"], "runner 必须把联合诊断传给变异器"
        assert seen["diagnosis"][0]["count"] >= 1

    @pytest.mark.asyncio
    async def test_mutate_without_diagnosis_kwarg_still_works(self):
        """旧签名 mutate（不收 diagnosis）不受影响——装配契约不漂移。"""
        seen: dict = {}

        async def mutate(*, artifact_text, artifact_type, failures):
            seen["called"] = True
            return artifact_text + " IMPROVED"

        runner = SkillEvolutionRunner(EvolutionConfig(noise_repeats=1),
                                      judge=_judge(), mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert seen["called"]

    @pytest.mark.asyncio
    async def test_reflective_mutator_renders_diagnosis_section(self):
        """有诊断时提示词出现「联合诊断」段；无诊断时与旧版同形。"""
        from neurova.evolution.eval.mutator import ReflectiveMutator

        captured: list = []

        async def llm(messages, model):
            captured.append(messages)
            return {"success": True, "response": "改进后的正文"}

        mutator = ReflectiveMutator(EvolutionConfig(), llm_call=llm)
        failures = [_f("任务一", "缺少语义校验", 0.1), _f("任务二", "缺少语义校验", 0.2)]
        diagnosis = buildDiagnosis(failures)

        await mutator.mutate(artifact_text=BASELINE, artifact_type="skill",
                             failures=failures, diagnosis=diagnosis)
        rendered = json.dumps(captured[-1], ensure_ascii=False)
        assert "联合诊断" in rendered
        assert "缺少语义校验" in rendered

        captured.clear()
        await mutator.mutate(artifact_text=BASELINE, artifact_type="skill",
                             failures=failures)
        rendered = json.dumps(captured[-1], ensure_ascii=False)
        assert "联合诊断" not in rendered

    @pytest.mark.asyncio
    async def test_rollouts_attribute_stability(self, monkeypatch):
        """N3：G=2 采样——偶发失败（1/2 采样挂）标 flaky，全挂标 stable。"""
        v0_calls = {"n": 0}

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            if "IMPROVED" in skill_text:
                c = 0.42
            elif task_input == "v0":
                # v0 的第 2 次调用（= 失败收割的首采样）抛错——1/2 采样失败 ⇒ flaky
                v0_calls["n"] += 1
                if v0_calls["n"] == 2:
                    raise RuntimeError("flaky rollout failure")
                c = 0.5
            else:
                c = 0.2
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c,
                                feedback="统一反馈：输出缺少语义校验")

        seen: dict = {}

        async def mutate(*, artifact_text, artifact_type, failures, diagnosis=None):
            seen["diagnosis"] = diagnosis
            return artifact_text + " IMPROVED"

        runner = SkillEvolutionRunner(EvolutionConfig(noise_repeats=1,
                                                      diagnosis_rollouts=2),
                                      judge=judge, mutate=mutate)
        await runner.run(baseline_text=BASELINE, artifact_type="skill",
                         dataset=_ds(), iterations=1)
        entries = seen["diagnosis"]
        by_stability = {e.get("stability"): e for e in entries if e.get("stability")}
        assert "flaky" in by_stability, "偶发失败必须被标为 flaky"
        assert by_stability["flaky"]["sample_failures"] >= 1
        assert by_stability["flaky"]["sample_total"] >= 2

    @pytest.mark.asyncio
    async def test_rollouts_default_one_keeps_legacy(self):
        """diagnosis_rollouts=1（默认）：诊断无 stability 字段（旧形态一致）。"""
        seen: dict = {}

        async def mutate(*, artifact_text, artifact_type, failures, diagnosis=None):
            seen["diagnosis"] = diagnosis
            return artifact_text + " IMPROVED"

        runner = SkillEvolutionRunner(EvolutionConfig(noise_repeats=1),
                                      judge=_judge(), mutate=mutate)
        await runner.run(baseline_text=BASELINE, artifact_type="skill",
                         dataset=_ds(), iterations=1)
        assert all("stability" not in e for e in seen["diagnosis"])

    def test_build_diagnosis_stability_from_sample_fields(self):
        """buildDiagnosis 直接消费采样字段：全挂=stable、部分挂=flaky、单采样无标记。"""
        stable = JudgeFailure(task_input="t1", output="o", feedback="模式甲", score=0.0,
                              environments=[], sample_count=3, failed_samples=3)
        flaky = JudgeFailure(task_input="t2", output="o", feedback="模式乙", score=0.2,
                             environments=[], sample_count=2, failed_samples=1)
        single = JudgeFailure(task_input="t3", output="o", feedback="模式丙", score=0.3,
                              environments=[])
        entries = buildDiagnosis([stable, flaky, single])
        by_pattern = {e["pattern"][:3]: e for e in entries}
        assert by_pattern["模式甲"]["stability"] == "stable"
        assert by_pattern["模式甲"]["sample_failures"] == 3
        assert by_pattern["模式乙"]["stability"] == "flaky"
        assert "stability" not in by_pattern["模式丙"]
