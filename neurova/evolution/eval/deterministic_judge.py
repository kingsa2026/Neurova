"""判分不可用时的确定性回退判据。

只检查输出是否可用（非空、无异常标记），不评估任务质量。它产出的分数
不能当作质量分使用；调用方必须把整轮结果标成回退面，并强制人工复核。
"""

from __future__ import annotations

from typing import Any, Optional

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.fitness import FitnessScore, length_penalty_for

_ERROR_MARKERS = (
    "traceback (most recent call last)",
    "exception:",
    "\n错误:",
    "\n异常:",
)


class DeterministicJudge:
    """确定性可用性判据：与 LLM judge 同形，但只回答「输出能不能用」。"""

    def __init__(self, config: Optional[EvolutionConfig] = None):
        self.config = config or EvolutionConfig()

    async def score(
        self,
        *,
        task_input: str,
        expected_behavior: str,
        output: str,
        skill_text: str,
        artifact_size: Optional[int] = None,
        max_size: Optional[int] = None,
        **_: Any,
    ) -> FitnessScore:
        penalty = length_penalty_for(artifact_size, max_size)
        text = str(output or "").strip()
        if not text:
            return FitnessScore(
                length_penalty=penalty,
                feedback="确定性回退：输出为空（未评估任务质量）",
                judge_available=False,
            )
        lowered = text.lower()
        for marker in _ERROR_MARKERS:
            if marker in lowered:
                return FitnessScore(
                    length_penalty=penalty,
                    feedback=f"确定性回退：输出含异常标记 {marker!r}（未评估任务质量）",
                    judge_available=False,
                )
        return FitnessScore(
            correctness=1.0,
            procedure_following=1.0,
            conciseness=1.0,
            length_penalty=penalty,
            feedback="确定性回退：输出非空且无异常标记（未评估任务质量）",
            judge_available=False,
        )
