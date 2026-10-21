"""N8：同域已采纳 harness 必须进入变异器提示（只读参考）。"""

import pytest

from neurova.evolution.eval.config import EvolutionConfig
from neurova.evolution.eval.mutator import ReflectiveMutator


class _CaptureLLM:
    def __init__(self):
        self.messages = []

    async def __call__(self, messages, model):
        self.messages = messages
        return {"success": True, "response": "改进后的正文"}


@pytest.mark.asyncio
async def test_mutator_prompt_carries_domain_harnesses():
    llm = _CaptureLLM()
    mutator = ReflectiveMutator(EvolutionConfig(), llm_call=llm)

    await mutator.mutate(
        artifact_text="当前正文",
        artifact_type="skill",
        failures=[],
        domain_harnesses=[
            {
                "skill_id": "peer-1",
                "version": "1.2.0",
                "description": "同域范例",
                "context_template": "PEER-BODY",
            }
        ],
    )

    prompt = llm.messages[-1]["content"]
    assert "同域已采纳 harness" in prompt
    assert "PEER-BODY" in prompt
    assert "peer-1" in prompt
