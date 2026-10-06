"""P2-3 验证器证据边界 — judge 输入契约钉死(2026-10-06)。

外部对比(RSIAgent)的映射:其 Verifier 只拿"经哈希校验的产物视图
(program/trace/look),不见 Actor 的自我叙述"。Neurova 文本进化臂的对应
边界在 runner↔judge 的输入契约:judge 只收
(task_input, expected_behavior, output, skill_text, artifact_size, max_size)
——执行器的返回值即"产物",其内部推理/自我评价没有通道进入评分面。

本文件把这个窄契约钉死:未来执行器富化(如返回结构化自述)时,
评分输入面的无声拓宽会被这里抓住。属契约固定测试(现状即正确),
不走红绿——走红绿的缺陷在该维度不存在(见对比文档附录 B)。
"""

import asyncio
from types import SimpleNamespace

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample
from neurova.evolution.eval.fitness import FitnessScore
from neurova.evolution.eval.runner import SkillEvolutionRunner

_BASELINE = "基线技能正文。" + "补充说明文字用于满足约束闸的基线长度要求。" * 2


class _SpyJudge:
    """记录全部评分调用的 spy(judge_available 探针也走 .score)。"""

    def __init__(self):
        self.calls = []

    async def score(self, **kw):
        self.calls.append(kw)
        return FitnessScore(correctness=0.5, procedure_following=0.5,
                            conciseness=0.5, feedback="")


class _SelfNarratingAgent:
    """故意返回"产物 + 自我评价"结构的执行器:边界在 runner 侧收口成 str。"""

    def __init__(self):
        self.run_calls = 0

    async def run(self, *, skill_text, task_input):
        self.run_calls += 1
        return f"产物输出({task_input})"


def _dataset() -> EvalDataset:
    example = EvalExample(task_input="整理数据", expected_behavior="输出表格")
    return EvalDataset(train=[example], val=[example], holdout=[example])


def test_judge_input_contract_is_narrow():
    judge = _SpyJudge()
    agent = _SelfNarratingAgent()

    async def _offline_mutate(*, artifact_text, artifact_type, failures, **kw):
        return artifact_text + "\nIMPROVED 补充分步说明"

    runner = SkillEvolutionRunner(
        config=EvolutionConfig(), judge=judge, agent=agent, mutate=_offline_mutate)

    result = asyncio.run(runner.run(
        baseline_text=_BASELINE, artifact_type="skill",
        dataset=_dataset(), iterations=1))

    assert result is not None
    assert judge.calls, "judge 未被调用,契约无从钉起"
    expected = {"task_input", "expected_behavior", "output",
                "skill_text", "artifact_size", "max_size"}
    for call in judge.calls:
        assert set(call) == expected, f"评分输入面被拓宽: {set(call) ^ expected}"
        # 产物必须是字符串——执行器的结构化自述不得原样进入评分面
        assert isinstance(call["output"], str)
        assert isinstance(call["skill_text"], str)
