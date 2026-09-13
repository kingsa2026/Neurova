"""适应度函数 — LLM-as-judge 多维细则 + 长度惩罚。

对位 Hermes `hermes-agent-self-evolution/evolution/core/fitness.py`。

判分公式(原样对齐 Hermes 数值,便于两边结果可直接比较):
    composite = max(0, 0.5·correctness + 0.3·procedure_following
                       + 0.2·conciseness − length_penalty)
长度惩罚:artifact_size/max_size > 0.9 后线性爬升,上限 0.3。

设计取舍:
  - judge 走可注入的 llm_call(默认用 llm_router),测试可毫秒级 mock;
  - LLM 失败/输出不可解析 → 退回中性 0.5,不因模型抖动崩掉整轮进化;
  - 快速代理(关键词重叠)仅在优化期使用,留出集对比永远用真 judge。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from neurova.core.logger import get_logger
from neurova.evolution.eval.config import EvolutionConfig

logger = get_logger(__name__)

_NEUTRAL = 0.5
_LENGTH_PENALTY_START = 0.9
_LENGTH_PENALTY_SLOPE = 3.0
_LENGTH_PENALTY_CAP = 0.3


@dataclass
class FitnessScore:
    """多维适应度分。"""

    correctness: float = 0.0
    procedure_following: float = 0.0
    conciseness: float = 0.0
    length_penalty: float = 0.0
    feedback: str = ""  # 供反射式变异消费的文本反馈

    @property
    def composite(self) -> float:
        raw = 0.5 * self.correctness + 0.3 * self.procedure_following + 0.2 * self.conciseness
        return max(0.0, raw - self.length_penalty)


def parse_score(value: Any) -> float:
    """解析 LLM 输出的分值,夹到 [0,1];不可解析退回中性 0.5。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return min(1.0, max(0.0, float(value)))
    try:
        return min(1.0, max(0.0, float(str(value).strip())))
    except (ValueError, TypeError):
        return _NEUTRAL


def length_penalty_for(artifact_size: Optional[int], max_size: Optional[int]) -> float:
    """长度惩罚曲线(与 Hermes 同曲线)。"""
    if not artifact_size or not max_size or max_size <= 0:
        return 0.0
    ratio = artifact_size / max_size
    if ratio <= _LENGTH_PENALTY_START:
        return 0.0
    return min(_LENGTH_PENALTY_CAP, (ratio - _LENGTH_PENALTY_START) * _LENGTH_PENALTY_SLOPE)


_JUDGE_SYSTEM = (
    "你是一个严格、公正的评审。请对 agent 的响应按三个维度各打 0.0-1.0 分:\n"
    "1. correctness:响应是否正确解决了任务?\n"
    "2. procedure_following:是否遵循了技能规定的流程?\n"
    "3. conciseness:是否足够简洁而没有遗漏重要信息?\n"
    "并给出具体、可操作的改进反馈。\n"
    "只输出一个 JSON 对象,字段:correctness, procedure_following, conciseness, feedback。"
)


class LLMJudge:
    """LLM-as-judge 判分器。

    llm_call 签名:`async (messages, model) -> {"success": bool, "response": str, "error": str}`
    默认走 neurova.llm.multi_model_client;测试注入 mock 即可离线跑。
    """

    def __init__(self, config: EvolutionConfig, llm_call: Optional[Callable[..., Any]] = None):
        self.config = config
        self._llm_call = llm_call

    async def _call_llm(self, messages: list[dict[str, str]], model: str) -> dict[str, Any]:
        if self._llm_call is not None:
            return await self._llm_call(messages, model)
        try:
            from neurova.llm.multi_model_client import get_multi_model_client

            client = get_multi_model_client()
            return await client.chat(messages, model=model or None)
        except Exception as e:  # noqa: BLE001 - LLM 不可用时退回中性,不让整轮进化崩
            logger.debug("judge LLM 调用失败: %s", e)
            return {"success": False, "error": str(e)}

    async def score(
        self,
        *,
        task_input: str,
        expected_behavior: str,
        output: str,
        skill_text: str,
        artifact_size: Optional[int] = None,
        max_size: Optional[int] = None,
    ) -> FitnessScore:
        messages = [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"【任务】\n{task_input}\n\n"
                    f"【期望行为/评分细则】\n{expected_behavior}\n\n"
                    f"【所遵循的技能/指令】\n{skill_text}\n\n"
                    f"【agent 的实际输出】\n{output}"
                ),
            },
        ]
        result = await self._call_llm(messages, self.config.judge_model)
        penalty = length_penalty_for(artifact_size, max_size)
        if not result.get("success"):
            return FitnessScore(
                correctness=_NEUTRAL,
                procedure_following=_NEUTRAL,
                conciseness=_NEUTRAL,
                length_penalty=penalty,
                feedback="judge 调用失败,退回中性分",
            )
        parsed = _extract_json(result.get("response") or "")
        if parsed is None:
            return FitnessScore(
                correctness=_NEUTRAL,
                procedure_following=_NEUTRAL,
                conciseness=_NEUTRAL,
                length_penalty=penalty,
                feedback="judge 输出不可解析,退回中性分",
            )
        return FitnessScore(
            correctness=parse_score(parsed.get("correctness")),
            procedure_following=parse_score(parsed.get("procedure_following")),
            conciseness=parse_score(parsed.get("conciseness")),
            length_penalty=penalty,
            feedback=str(parsed.get("feedback", "")),
        )


def _extract_json(text: str) -> Optional[dict]:
    """从 LLM 输出提取 JSON 对象,容忍 ```json 围栏与前后缀文本。"""
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    # 花括号配平提取(容忍嵌套与字符串内花括号)
    start = text.find("{")
    if start == -1:
        return None
    depth, in_string, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def quick_proxy_score(expected_behavior: str, output: str) -> float:
    """优化期快速代理分:关键词重叠率。

    只在训练集迭代期使用(省钱);留出集对比永远用真 judge。
    对齐 Hermes `skill_fitness_metric` —— 非空保底 0.3。
    """
    if not (output or "").strip():
        return 0.0
    expected_words = set(re.split(r"\s+", (expected_behavior or "").lower()))
    output_words = set(re.split(r"\s+", output.lower()))
    expected_words.discard("")
    if not expected_words:
        return _NEUTRAL
    overlap = len(expected_words & output_words) / len(expected_words)
    return min(1.0, 0.3 + 0.7 * overlap)
