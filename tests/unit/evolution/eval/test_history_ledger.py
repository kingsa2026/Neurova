"""P1-4 编辑历史结构化回喂 — EvolutionLedger 与变异器历史注入的红灯测试。

RRSI 对齐：逐候选（含被闸拒绝的）落 JSONL 台账；已证伪假设渲染回变异器
提示段，禁止重画。history=None 时变异器提示词与旧版逐字节一致（增量不降级）。
"""

import json

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2


def _ds() -> EvalDataset:
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _judge_by_gain(gain_by_marker: dict[str, float]):
    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.2
        for marker, gain in gain_by_marker.items():
            if marker in skill_text:
                c = 0.2 + gain
                break
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


class TestLedgerUnit:
    def test_append_and_read_back(self, tmp_path):
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        ledger = EvolutionLedger(tmp_path)
        seq = ledger.append("s1", {"hypothesis": "加超时", "accepted": False,
                                   "reject_reason": "no_improvement"})
        assert seq == 0
        again = EvolutionLedger(tmp_path)  # 重启后新实例读同一目录
        assert again.recent("s1")[0]["hypothesis"] == "加超时"

    def test_recent_caps_gate_wall(self, tmp_path):
        """连续 gate 拒绝的'abort 墙'只回最近 4 条 + 汇总标记，不挤占上下文。"""
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        ledger = EvolutionLedger(tmp_path)
        for i in range(7):
            ledger.append("s1", {"hypothesis": f"假设{i}", "accepted": False,
                                 "reject_reason": "leak:task_specialization"})
        records = ledger.recent("s1")
        # 纯墙：4 条真实墙记录（最近 4 条）+ 1 条 {"gate_wall": 7} 汇总
        assert len(records) == 5
        assert [r.get("hypothesis") for r in records[:4]] == [
            "假设3", "假设4", "假设5", "假设6"]
        assert records[-1]["gate_wall"] == 7

    def test_wall_marker_stays_before_later_records(self, tmp_path):
        """墙之后有正常记录：标记插在墙压缩点后，正常记录不被吞。"""
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        ledger = EvolutionLedger(tmp_path)
        for i in range(7):
            ledger.append("s1", {"hypothesis": f"假设{i}", "accepted": False,
                                 "reject_reason": "leak:task_specialization"})
        ledger.append("s1", {"hypothesis": "正常候选", "accepted": True,
                             "reject_reason": ""})
        records = ledger.recent("s1")
        assert records[-1]["hypothesis"] == "正常候选"
        assert records[-2]["gate_wall"] == 7
        assert sum(1 for r in records if "gate_wall" not in r) == 5

    def test_recent_no_wall_no_marker(self, tmp_path):
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        ledger = EvolutionLedger(tmp_path)
        ledger.append("s1", {"hypothesis": "h", "accepted": False,
                             "reject_reason": "no_improvement"})
        records = ledger.recent("s1")
        assert len(records) == 1 and all("gate_wall" not in r for r in records)

    def test_key_sanitized(self, tmp_path):
        """skill_id 含路径字符时文件名安全化，不逃逸目录。"""
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        ledger = EvolutionLedger(tmp_path)
        ledger.append("../../evil", {"hypothesis": "h", "accepted": False})
        assert not (tmp_path / "evil").exists()
        assert list(tmp_path.glob("*.jsonl"))

    def test_render_for_prompt_sections(self):
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        records = [
            {"ts": "T1", "hypothesis": "加了评分攻略", "accepted": False,
             "reject_reason": "no_improvement"},
            {"ts": "T2", "hypothesis": "加了分步说明", "accepted": True,
             "reject_reason": ""},
        ]
        text = EvolutionLedger.render_for_prompt(records)
        assert "已实测无效" in text
        assert "加了评分攻略" in text
        assert EvolutionLedger.render_for_prompt([]) == ""

    def test_patch_updates_winner_record(self, tmp_path):
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        ledger = EvolutionLedger(tmp_path)
        seq = ledger.append("s1", {"hypothesis": "h", "accepted": True,
                                   "delta_holdout": None})
        ledger.patch("s1", seq, {"delta_holdout": 0.03})
        assert EvolutionLedger(tmp_path).recent("s1")[0]["delta_holdout"] == pytest.approx(0.03)


class TestRunnerRecording:
    @pytest.mark.asyncio
    async def test_every_candidate_recorded(self, tmp_path):
        """3 轮迭代（1 接受 2 未胜出）→ JSONL 恰 3 条；胜者补 delta_holdout。"""
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        candidates = iter(["第一版改进", "第二版改进", "第三版改进"])
        gain_map = {"第一版改进": 0.10, "第二版改进": -0.05, "第三版改进": 0.0}

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.2 + gain_map.get(skill_text, 0.0)
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return next(candidates)

        ledger = EvolutionLedger(tmp_path / "history")
        runner = SkillEvolutionRunner(EvolutionConfig(), judge=judge, mutate=mutate,
                                      ledger=ledger)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=3, ledger_key="s1")
        records = ledger.recent("s1")
        assert len(records) == 3
        assert records[0]["accepted"] is True and records[1]["accepted"] is False
        assert records[1]["reject_reason"] == ""
        for r in records:
            assert {"ts", "artifact_type", "hypothesis", "failures_digest",
                    "delta_train", "accepted", "reject_reason",
                    "constraint_failures"} <= set(r)
        # 胜者回填 holdout 实测差
        assert result.improvement == pytest.approx(0.10)
        assert records[0]["delta_holdout"] == pytest.approx(0.10)
        assert records[1]["delta_holdout"] is None

    @pytest.mark.asyncio
    async def test_gate_rejected_candidate_recorded(self, tmp_path):
        """被约束闸拒绝的候选也入账（reject_reason 带 constraints: 前缀）。"""
        from neurova.evolution.eval.constraints import ConstraintValidator
        from neurova.evolution.eval.history_ledger import EvolutionLedger

        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.9
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\n超长尾巴" * 4000  # 超出 max_skill_size

        cfg = EvolutionConfig()
        ledger = EvolutionLedger(tmp_path / "history")
        runner = SkillEvolutionRunner(
            cfg, judge=judge, mutate=mutate, ledger=ledger,
            constraints=ConstraintValidator(cfg),
        )
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1, ledger_key="s1")
        assert result.deployed_text == BASELINE
        records = ledger.recent("s1")
        assert len(records) == 1
        assert records[0]["accepted"] is False
        assert records[0]["reject_reason"].startswith("constraints:")

    @pytest.mark.asyncio
    async def test_no_ledger_unchanged(self, tmp_path):
        """不注入 ledger（默认）：行为与旧版一致，无落盘。"""
        async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
            c = 0.9 if "改进" in skill_text else 0.2
            return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\n改进"

        runner = SkillEvolutionRunner(EvolutionConfig(), judge=judge, mutate=mutate)
        result = await runner.run(baseline_text=BASELINE, artifact_type="skill",
                                  dataset=_ds(), iterations=1)
        assert not result.rejected
        assert not (tmp_path / "history").exists()


class TestMutatorHistory:
    def _capture_llm(self, monkeypatch):
        captured: dict[str, str] = {}

        async def fake_call(self, messages, model):
            captured["user"] = messages[-1]["content"]
            return {"success": True, "response": "改进后的正文"}

        from neurova.evolution.eval import mutator as mutator_mod

        monkeypatch.setattr(mutator_mod.ReflectiveMutator, "_call_llm", fake_call)
        return captured

    @pytest.mark.asyncio
    async def test_history_without_records_is_byte_identical(self, monkeypatch):
        """history=None 与不传 history：提示词逐字节一致（旧契约不漂移）。"""
        from neurova.evolution.eval.mutator import JudgeFailure, ReflectiveMutator

        captured = self._capture_llm(monkeypatch)
        mutator = ReflectiveMutator(EvolutionConfig())
        failures = [JudgeFailure(task_input="t", output="o", feedback="fb", score=0.1)]
        await mutator.mutate(artifact_text="正文", artifact_type="skill", failures=failures)
        prompt_no_arg = captured["user"]
        await mutator.mutate(artifact_text="正文", artifact_type="skill",
                             failures=failures, history=None)
        assert captured["user"] == prompt_no_arg

    @pytest.mark.asyncio
    async def test_falsified_hypotheses_in_prompt(self, monkeypatch):
        from neurova.evolution.eval.mutator import JudgeFailure, ReflectiveMutator

        captured = self._capture_llm(monkeypatch)
        mutator = ReflectiveMutator(EvolutionConfig())
        failures = [JudgeFailure(task_input="t", output="o", feedback="fb", score=0.1)]
        history = [{"ts": "T1", "hypothesis": "给失败任务加重试", "accepted": False,
                    "reject_reason": "no_improvement"}]
        await mutator.mutate(artifact_text="正文", artifact_type="skill",
                             failures=failures, history=history)
        assert "已实测无效" in captured["user"]
        assert "给失败任务加重试" in captured["user"]


class TestServiceAndImproverWiring:
    async def _judge(self, *, task_input, expected_behavior, output, skill_text, **kw):
        c = 0.9 if "IMPROVED" in skill_text else 0.2
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    @pytest.mark.asyncio
    async def test_service_records_to_ledger(self, tmp_path, monkeypatch):
        """service.evolve 自动携带 ledger：候选结局落 history/<skill>.jsonl。"""
        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("agent-x", base_dir=tmp_path / "evo")

        async def mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        await svc.evolve(skill_id="s1", skill_text=BASELINE, dataset=_ds(),
                         agent=None, judge=self._judge, mutate=mutate)
        ledger_file = tmp_path / "evo" / "history" / "s1.jsonl"
        assert ledger_file.exists()
        records = [json.loads(line) for line in ledger_file.read_text(encoding="utf-8").splitlines()]
        assert records and all("hypothesis" in r for r in records)

    @pytest.mark.asyncio
    async def test_service_legacy_mutate_signature_still_works(self, tmp_path, monkeypatch):
        """旧签名 mutate（不收 history kwarg）注入时 runner 不得传 history。"""
        from neurova.evolution.eval.service import SkillEvolutionService

        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = SkillEvolutionService("agent-y", base_dir=tmp_path / "evo")

        async def legacy_mutate(*, artifact_text, artifact_type, failures):
            return artifact_text + "\nIMPROVED"

        result, _ = await svc.evolve(skill_id="s1", skill_text=BASELINE, dataset=_ds(),
                                     agent=None, judge=self._judge, mutate=legacy_mutate)
        assert not result.rejected

    @pytest.mark.asyncio
    async def test_improver_feeds_falsified_history(self, tmp_path, monkeypatch):
        """skill_improver 反射式改进把已证伪假设喂给变异器。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        from neurova.evolution.eval import mutator as mutator_mod
        from neurova.evolution.eval.history_ledger import EvolutionLedger
        from neurova.evolution.skill_improver import get_skill_improver, reset_skill_improver

        # 预写一条已证伪假设
        ledger = EvolutionLedger(tmp_path / "data" / "evolution" / "history")
        ledger.append("sk-hist", {"ts": "T1", "hypothesis": "加浏览器重试三次",
                                  "accepted": False, "reject_reason": "no_improvement"})

        reset_skill_improver()
        improver = get_skill_improver(min_records_for_analysis=2, failure_threshold=0.3)
        for i in range(3):
            improver.record_usage(skill_id="sk-hist", success=False,
                                  error_message=f"timeout upstream-{i}",
                                  input_summary=f"任务{i}", output_summary="")
        captured: dict[str, str] = {}

        async def fake_call(self, messages, model):
            captured["user"] = messages[-1]["content"]
            return {"success": True, "response": "改进正文 v2"}

        monkeypatch.setattr(mutator_mod.ReflectiveMutator, "_call_llm", fake_call)
        try:
            proposals = await improver.propose_pending_improvements_async(
                skill_text_loader=lambda sid: "原始技能正文")
        finally:
            reset_skill_improver()
        assert captured["user"]  # 反射路径确实走到了
        assert "已实测无效" in captured["user"]
        assert "加浏览器重试三次" in captured["user"]
        assert proposals and "improved_text" in proposals[0].changes
