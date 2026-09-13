"""反射式变异器 — 读失败原因,做定向修改。

这是本波的价值核心,对位 GEPA(Genetic-Pareto Prompt Evolution)的
"reads execution traces to understand WHY things fail (not just that they
failed)"。

对照现有 `neurova/skills/prompt_optimizer.generate_variants`:那个是"加角色段
/加结构段"的**盲目变异**;本模块把上一轮在 val 集上得分最低用例的
(task, output, judge feedback)带进 prompt,让 LLM 提出定向修改。

安全性:LLM 失败或返回空 → 保留基线原文,绝不产出空技能。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from neurova.core.logger import get_logger
from neurova.evolution.eval.config import EvolutionConfig

logger = get_logger(__name__)


@dataclass
class JudgeFailure:
    """上一轮评分最低的用例,供反射分析。"""

    task_input: str
    output: str
    feedback: str
    score: float = 0.0


_MUTATOR_SYSTEM = (
    "你是一个提示词/技能文本的优化器,工作方式是**反射式进化**:\n"
    "你不做盲目改写,而是先读懂下面列出的失败原因,再针对性地做最小够用的修改。\n\n"
    "硬要求:\n"
    "1. 保持原文的**核心意图与用途**不变——这是同一个技能,不是新技能;\n"
    "2. 只针对失败原因做改进,不要大段重写或堆砌套话;\n"
    "3. 不得超出长度预算;\n"
    "4. 直接输出修改后的完整正文,不要任何解释、前言或 markdown 围栏。"
)


class ReflectiveMutator:
    """反射式变异器。

    llm_call 签名:`async (messages, model) -> {"success": bool, "response": str}`
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
        except Exception as e:  # noqa: BLE001
            logger.debug("mutator LLM 调用失败: %s", e)
            return {"success": False, "error": str(e)}

    def _size_budget(self, artifact_type: str) -> int:
        if artifact_type == "tool_description":
            return self.config.max_tool_desc_size
        if artifact_type == "param_description":
            return self.config.max_param_desc_size
        return self.config.max_skill_size

    async def mutate(
        self,
        *,
        artifact_text: str,
        artifact_type: str,
        failures: list[JudgeFailure],
    ) -> str:
        """基于失败反馈生成定向改进后的文本;失败时返回原文。"""
        budget = self._size_budget(artifact_type)

        if failures:
            failure_block = "\n\n".join(
                f"【失败用例 {i + 1}】(得分 {f.score:.2f})\n"
                f"任务:{f.task_input}\n"
                f"实际输出:{f.output}\n"
                f"评审反馈:{f.feedback}"
                for i, f in enumerate(failures)
            )
            instruction = (
                f"以下是一个 {artifact_type} 的当前正文,以及它在评测中失败的原因。\n"
                f"请针对失败原因改进它。\n\n"
                f"【当前正文】\n{artifact_text}\n\n"
                f"【失败原因】\n{failure_block}"
            )
        else:
            instruction = (
                f"以下是一个 {artifact_type} 的当前正文。请在保持核心意图的前提下,"
                f"让它更清晰、更可执行。\n\n【当前正文】\n{artifact_text}"
            )

        instruction += f"\n\n【长度预算】修改后的正文不得超过 {budget} 个字符。"

        messages = [
            {"role": "system", "content": _MUTATOR_SYSTEM},
            {"role": "user", "content": instruction},
        ]
        result = await self._call_llm(messages, self.config.optimizer_model)
        if not result.get("success"):
            return artifact_text
        text = (result.get("response") or "").strip()
        if not text:
            return artifact_text
        text = _strip_fence(text)
        # 硬预算保护:超出预算的变异直接退回基线(约束闸还会二次校验)
        if len(text) > budget:
            logger.debug("变异产物超预算(%d > %d),退回基线", len(text), budget)
            return artifact_text
        return text


def _strip_fence(text: str) -> str:
    """剥掉可能的 ``` 围栏(系统提示已禁,但模型仍可能加)。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped
