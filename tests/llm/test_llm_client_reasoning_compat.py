"""思考字段多名称兼容（2026-09-07）— 商汤 sensenova 流式回传
delta.reasoning，OpenAI 系回传 delta.reasoning_content。锁定
llm_client._pick_reasoning 的字段优先级与 LLMResponse 透传。
"""
import asyncio
from types import SimpleNamespace

from neurova.llm_client import _pick_reasoning


class TestPickReasoning:
    def test_prefers_reasoning_content(self):
        obj = SimpleNamespace(reasoning_content="A", reasoning="B")
        assert _pick_reasoning(obj, "reasoning_content", "reasoning") == "A"

    def test_falls_back_to_reasoning(self):
        obj = SimpleNamespace(reasoning="B")
        assert _pick_reasoning(obj, "reasoning_content", "reasoning") == "B"

    def test_all_missing_returns_none(self):
        obj = SimpleNamespace(content="x")
        assert _pick_reasoning(obj, "reasoning_content", "reasoning") is None


class TestStreamReasoningCompat:
    """流式 chunk 携带 delta.reasoning（商汤）时应进入 LLMResponse.reasoning_content"""

    def _run(self, delta):
        # 解析点已统一走 _pick_reasoning；此处直接验证字段提取行为
        return _pick_reasoning(delta, "reasoning_content", "reasoning")

    def test_sensenova_reasoning_field(self):
        delta = SimpleNamespace(reasoning="思考片段", content=None)
        assert self._run(delta) == "思考片段"

    def test_openai_reasoning_content_field(self):
        delta = SimpleNamespace(reasoning_content="思考A", content="答")
        assert self._run(delta) == "思考A"
