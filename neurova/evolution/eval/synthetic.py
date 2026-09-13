"""合成评测集生成器 — 强模型读产物文本 → 产出评测用例(解冷启动)。

对位 Hermes `core/dataset_builder.SyntheticDatasetBuilder`:技能多数没有
历史使用数据,评测集先从合成开始(GEPA 最少 3 条样例即可工作)。

expected_behavior 是**评分细则(rubric)**,不是精确文本(如"应指出第 42 行
的 SQL 注入",不是"输出这段字符串")。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Optional

from neurova.core.logger import get_logger
from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.dataset import EvalDataset, EvalExample

logger = get_logger(__name__)

_GEN_SYSTEM = (
    "你是一名评测工程师。给定一段 agent 技能/提示词文本,生成多样、真实的评测用例,"
    "每条包含:\n"
    "- task_input: 用户会真实提出的问题/任务\n"
    "- expected_behavior: 好响应的评分细则(rubric,描述应做到什么,不是精确输出文本)\n"
    "- difficulty: easy|medium|hard\n"
    "- category: 考察的技能侧面\n"
    "只输出一个 JSON 数组,不要其它文字。"
)


def _extract_json_array(text: str) -> Optional[list]:
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        parsed = json.loads(m.group())
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


class SyntheticDatasetBuilder:
    """LLM 合成评测集;llm_call 可注入以便离线测试。"""

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
            logger.debug("合成数据集 LLM 调用失败: %s", e)
            return {"success": False, "error": str(e)}

    async def generate(
        self,
        artifact_text: str,
        artifact_type: str = "skill",
        num_cases: Optional[int] = None,
    ) -> EvalDataset:
        n = num_cases or self.config.eval_dataset_size
        result = await self._call_llm(
            [
                {"role": "system", "content": _GEN_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"【{artifact_type} 文本】\n{artifact_text[:12000]}\n\n"
                        f"请生成 {n} 条评测用例。"
                    ),
                },
            ],
            self.config.judge_model,
        )
        if not result.get("success"):
            return EvalDataset()
        cases = _extract_json_array(result.get("response") or "")
        if not cases:
            logger.debug("合成数据集输出不可解析为 JSON 数组")
            return EvalDataset()
        examples = [
            EvalExample(
                task_input=str(c.get("task_input", "")).strip(),
                expected_behavior=str(c.get("expected_behavior", "")).strip(),
                difficulty=str(c.get("difficulty", "medium")).strip() or "medium",
                category=str(c.get("category", "general")).strip() or "general",
                source="synthetic",
            )
            for c in cases
            if isinstance(c, dict) and str(c.get("task_input", "")).strip()
            and str(c.get("expected_behavior", "")).strip()
        ]
        return EvalDataset.split(examples, seed=self.config.seed)
