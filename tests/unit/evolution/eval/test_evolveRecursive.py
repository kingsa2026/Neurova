"""R5 递归多轮演化 —— 红灯测试。

§10.2 R5：技能进化此前是单轮提案形态；HarnessPro/ModularRSI 的递归是
「上轮胜者作下轮基线、逐轮成本/增益轨迹入账」。本文件钉：

1. 多轮增益累积：上轮 deployed_text 作下轮基线，轨迹逐轮记录
   （rejected/reason/holdout 前后/improvement/成本态/提案 id）；
2. 早停：某轮 no_improvement/rejected ⇒ 停止并记 stopped_reason，
   deployed 停在最后一个被接受的状态；
3. 总改善 = 各轮 holdout 改善之和；最后一轮的 pending 提案随结果返回。
"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.service import SkillEvolutionService


BASELINE = "基础技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 10


def _ds():
    return EvalDataset(
        train=[EvalExample(task_input=f"t{i}", expected_behavior="输出要点") for i in range(4)],
        val=[EvalExample(task_input=f"v{i}", expected_behavior="输出要点") for i in range(2)],
        holdout=[EvalExample(task_input=f"h{i}", expected_behavior="输出要点") for i in range(2)],
    )


def _judge_counting(max_improvements: int = 3):
    """每含一个 IMPROVED 标记涨一档（封顶 max_improvements 档）。"""

    async def judge(*, task_input, expected_behavior, output, skill_text, **kw):
        count = min(skill_text.count("IMPROVED"), max_improvements)
        c = 0.2 + 0.02 * count
        return FitnessScore(correctness=c, procedure_following=c, conciseness=c, feedback="")

    return judge


async def _mutate(*, artifact_text, artifact_type, failures):
    return artifact_text + " IMPROVED"


class _EchoAgent:
    async def run(self, *, skill_text, task_input):
        return "echo"


def _svc(tmp_path):
    return SkillEvolutionService("recursive-agent", base_dir=tmp_path)


def _cfg():
    return EvolutionConfig(noise_repeats=1, exec_suite_enabled=False)


class TestEvolveRecursive:
    @pytest.mark.asyncio
    async def test_multi_epoch_accumulates(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = _svc(tmp_path)
        report = await svc.evolveRecursive(
            skill_id="sk-rec", skill_text=BASELINE, dataset=_ds(), epochs=3,
            iterations=1, agent=_EchoAgent(), judge=_judge_counting(3),
            mutate=_mutate, config=_cfg())
        assert report["epochs_run"] == 3
        assert report["deployed_text"].count("IMPROVED") == 3
        assert report["total_improvement"] == pytest.approx(0.06)
        assert report["stopped_reason"] == "epochs_exhausted"
        assert [e["epoch"] for e in report["epochs"]] == [1, 2, 3]
        assert all(e["reject_reason"] == "" for e in report["epochs"])
        assert report["proposal"] is not None

    @pytest.mark.asyncio
    async def test_stops_on_no_improvement(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = _svc(tmp_path)
        report = await svc.evolveRecursive(
            skill_id="sk-rec", skill_text=BASELINE, dataset=_ds(), epochs=3,
            iterations=1, agent=_EchoAgent(), judge=_judge_counting(1),
            mutate=_mutate, config=_cfg())
        assert report["epochs_run"] == 2
        assert report["stopped_reason"] == "no_improvement"
        assert report["deployed_text"].count("IMPROVED") == 1
        assert report["epochs"][-1]["reject_reason"] == "no_improvement"

    @pytest.mark.asyncio
    async def test_stops_on_rejection(self, monkeypatch, tmp_path):
        """首轮就被拒（disabled）⇒ 轨迹一条、原因如实。"""
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "0")
        svc = _svc(tmp_path)
        report = await svc.evolveRecursive(
            skill_id="sk-rec", skill_text=BASELINE, dataset=_ds(), epochs=3,
            iterations=1, agent=_EchoAgent(), judge=_judge_counting(3),
            mutate=_mutate, config=_cfg())
        assert report["epochs_run"] == 1
        assert report["stopped_reason"] == "disabled"
        assert report["deployed_text"] == BASELINE
        assert report["total_improvement"] == 0.0

    @pytest.mark.asyncio
    async def test_epochs_minimum_one(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_TEXT_EVOLUTION", "1")
        svc = _svc(tmp_path)
        report = await svc.evolveRecursive(
            skill_id="sk-rec", skill_text=BASELINE, dataset=_ds(), epochs=0,
            iterations=1, agent=_EchoAgent(), judge=_judge_counting(3),
            mutate=_mutate, config=_cfg())
        assert report["epochs_run"] == 1
