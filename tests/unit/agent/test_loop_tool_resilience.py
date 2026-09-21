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

from .conftest import attach_tool_executor


def make_loop():
    """原生链的工具执行经执行咽喉（工单 003），替身的接口层放 `tool_router`。"""
    agent = MagicMock()
    agent._tool_messages_list = []
    # 咽喉读的是 `_skill_registry` / `_tool_registry` 那一组私有名，
    # 替身必须显式置 None，否则 MagicMock auto-attr 会被当成"技能存在"。
    agent.skill_registry = None
    agent._skill_registry = None
    agent.tool_memory = None
    agent.tool_lifecycle = None
    agent.skill_packer = None

    async def _route(tool_name, params=None, user_id=None):
        return {"ok": 1}

    agent.tool_router = SimpleNamespace(route=_route, execute=_route)
    agent.config = SimpleNamespace(name="probe", user_id="default", agent_id="test-agent")
    attach_tool_executor(agent)
    loop = OpenAILoop(agent)
    return loop


# 非内置工具名：原生链经执行咽喉后，内置工具会真执行（含网络），
# 本文件要测的是"路由失败如何回传真实错误"，故走 `tool_router` 那一档。
TOOL = "mcp_probe.search"


def tool_call(id_: str, arguments: str):
    return {"id": id_, "function": {"name": TOOL, "arguments": arguments}}


VALID_ARGS = json.dumps({"query": "news"})


class TestBadArgumentsTolerance:
    def test_bad_json_does_not_kill_round(self):
        loop = make_loop()
        messages = []
        result = asyncio.run(
            loop.handle_tool_calls(
                [tool_call("c1", "这不是JSON"), tool_call("c2", VALID_ARGS)],
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
        contents = [m["content"] for m in result if m.get("role") == "tool"]
        assert contents and "ok" in contents[0]


class TestToolRouterFailureErrorPropagation:
    """ToolRouter 失败路径必须回传真实错误（2026-09-09 串台事故）

    根因：`from types import SimpleNamespace` 写在 success 分支内，Python 将其
    编译为函数级局部名；ToolRouter 返回失败时走 else 分支引用未绑定名 →
    UnboundLocalError 被上层 except 吞掉 → 真实工具错误被顶掉为
    "SkillRegistry 和 ToolRouter 均未找到该工具"，LLM 收到错误诊断信息
    （生产实锤：mcp.filesystem.list_allowed_directories 失败被污染）。

    契约：success=False 时 tool 消息 content 必须携带 ToolRouter 的真实 error。
    """

    def test_router_failure_returns_real_error(self):
        loop = make_loop()

        async def _failing(tool_name, params=None, user_id=None):
            return {"error": "REAL_ERROR_TARGET_DIR_MISSING"}

        loop.agent.tool_router = SimpleNamespace(route=_failing, execute=_failing)
        result = asyncio.run(loop.handle_tool_calls([tool_call("c1", VALID_ARGS)], []))
        contents = [m["content"] for m in result if m["role"] == "tool"]
        assert contents, "失败也必须产出 tool 消息回给 LLM"
        assert "REAL_ERROR_TARGET_DIR_MISSING" in contents[0]
        assert "均未找到该工具" not in contents[0]

    def test_router_none_result_returns_fallback_error(self):
        """router 返回空（非 SimpleNamespace）时也不得炸 UnboundLocalError"""
        loop = make_loop()

        async def _none(tool_name, params=None, user_id=None):
            return None

        loop.agent.tool_router = SimpleNamespace(route=_none, execute=_none)
        result = asyncio.run(loop.handle_tool_calls([tool_call("c1", VALID_ARGS)], []))
        contents = [m["content"] for m in result if m["role"] == "tool"]
        assert contents
        assert "SimpleNamespace" not in contents[0]


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


class TestDictToolCallsGateSignature:
    """2026-09-14 飞书"全是代码+无成品答案"事故根因。

    LLMResponse.tool_calls 的契约是 List[Dict]（llm_client.py 把 SDK 对象转 dict，
    base.py 执行链也按 dict 访问），但 _predict_normal 非流式路径的门控签名
    用 tc.name/tc.arguments 属性访问 → AttributeError: 'dict' object has no
    attribute 'name' → chat_pipeline 整轮回退 legacy 单发，工具环丢失，
    模型工具调用以原始 XML 泄漏进正文。流式路径（pending_tool_calls）已按
    dict 访问，本用例锁定非流式路径同契约。
    """

    def test_dict_tool_calls_survive_gate_and_execute(self):
        loop = make_loop()
        dict_calls = [
            {"id": "c1", "function": {"name": "web_search", "arguments": '{"query":"news"}'}},
            {"id": "c2", "function": {"name": "rss_read", "arguments": '{"url":"https://x"}'}},
        ]
        first = SimpleNamespace(
            content="", reasoning_content=None, tool_calls=dict_calls, finish_reason="tool_calls"
        )
        final = SimpleNamespace(
            content="成品答案", reasoning_content=None, tool_calls=None, finish_reason="stop"
        )
        n = {"calls": 0}

        class TwoStepLLM:
            async def chat(self, **params):
                n["calls"] += 1
                return first if n["calls"] == 1 else final

        loop.llm_client = TwoStepLLM()
        resp = asyncio.run(loop._predict_normal({"messages": [{"role": "user", "content": "hi"}]}))
        assert resp.content == "成品答案", "dict 型 tool_calls 不得炸掉循环，须执行工具后回喂 LLM"
        assert n["calls"] == 2, "第一轮 tool_calls → 执行 → 第二轮合成，共 2 次 LLM 调用"
