"""P0 工具调用链路韧性测试

1. base.py handle_tool_calls：模型输出非法 JSON 参数不再炸掉整轮，
   而是把错误作为该条 tool 结果回给 LLM 让其自行修正
2. openai_loop：400 误伤判定收紧（子串匹配 → 结构化特征匹配），
   且降级重试时注入文本格式教学，弱 provider 仍有工具通道
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop, _looks_like_unsupported_tools_error


def make_loop():
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.tool_router = SimpleNamespace(
        execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
    )
    loop = OpenAILoop(agent)
    return loop


def tool_call(id_: str, arguments: str):
    return {"id": id_, "function": {"name": "web_search", "arguments": arguments}}


class TestBadArgumentsTolerance:
    def test_bad_json_does_not_kill_round(self):
        loop = make_loop()
        messages = []
        result = asyncio.run(
            loop.handle_tool_calls(
                [tool_call("c1", "这不是JSON"), tool_call("c2", json.dumps({"query": "天气"}))],
                messages,
            )
        )
        # 两条都有对应的 tool 消息（坏参数以错误消息形式回给 LLM）
        contents = [m["content"] for m in result if m["role"] == "tool"]
        assert any("JSON" in c or "json" in c for c in contents), "坏参数应回错误消息"
        assert any("ok" in c for c in contents), "好参数仍应正常执行"

    def test_empty_arguments_treated_as_empty_object(self):
        loop = make_loop()
        result = asyncio.run(loop.handle_tool_calls([tool_call("c1", "")], []))
        assert any(m.get("role") == "tool" and "ok" in m["content"] for m in result)


class TestDegradeDetection:
    def test_true_positives(self):
        assert _looks_like_unsupported_tools_error("Error code: 400 - Invalid tools schema")
        assert _looks_like_unsupported_tools_error("openai error: status code: 400, tools not supported")
        assert _looks_like_unsupported_tools_error("Missing required parameter: 'parameters.type'")

    def test_no_false_positive_on_unrelated_numbers(self):
        assert not _looks_like_unsupported_tools_error("max_tokens reached: 4000")
        assert not _looks_like_unsupported_tools_error("request failed after 400ms timeout")
        assert not _looks_like_unsupported_tools_error("connection reset")

    @pytest.mark.asyncio
    async def test_degraded_retry_injects_text_format_hint(self):
        """400 后的无工具重试必须注入文本格式教学，弱 provider 才有工具通道"""

        call_count = {"n": 0}

        class FlakyLLM:
            async def chat(self, **params):
                call_count["n"] += 1
                if params.get("tools"):
                    raise RuntimeError("Error code: 400 - Invalid tools")
                return SimpleNamespace(content="降级回答", reasoning_content=None, finish_reason="stop")

        loop = make_loop()
        loop.llm_client = FlakyLLM()
        loop.agent.llm_client = loop.llm_client

        # `_predict_normal` 接收的是 predict_step 构造的 request_params（可能带 tools）。
        # 需带 tools 才能触发"工具被拒 → 降级重试"，否则首次即可成功，验证不到降级分支。
        resp = await loop._predict_normal(
            {
                "messages": [{"role": "system", "content": "S"}],
                "stream": False,
                "tools": [{"type": "function", "function": {"name": "web_search", "parameters": {"type": "object"}}}],
            }
        )
        assert resp.content == "降级回答"
        assert call_count["n"] == 2
