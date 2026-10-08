"""协议转换只许一处实现：环交 OpenAI 形态，provider 层负责线形状（§6-76 修法 A）。

改前的形态是**同一份转换做两遍**：`AnthropicLoop._convert_messages_to_anthropic` /
`_convert_tools_to_anthropic` 在请求装配点转一次，路由层 `build_anthropic_body` 在
`provider_kind == "anthropic"` 时又转一次。后果分两层——

- 走 OpenAI 兼容网关（如 OpenRouter 的 `anthropic/claude-*` 路由）时，环内那份转换把
  tools 变成 `input_schema` 形态直接送进 OpenAI 校验，回 400
  `invalid_literal tools[0].type expected "function"`；
- 走真 anthropic-kind 时，路由层那份只做 `str(content)`，于是**环内转换变成承重的**：
  它一被删掉，`role == "tool"` 与 `assistant.tool_calls` 就没人产块，函数调用静默退化。

本文件钉的是"两处变一处"这个结果本身（教义第 6/7 条），不是某条分支的行为：
环侧不再定义转换方法、交出去的就是 OpenAI 形态，线形状只在 provider 层出现一次。
"""

import asyncio
import inspect

import pytest

from neurova.agent.loops.anthropic_loop import AnthropicLoop
from neurova.agent.loops.openai_loop import OpenAILoop


def _makeLoop():
    """不经 `__init__` 构造一条环——本文件判的是请求装配的形状，不跑网络。"""
    from unittest.mock import MagicMock

    loop = object.__new__(AnthropicLoop)
    loop.agent = MagicMock()
    return loop


_OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {"name": "search_files", "description": "按关键词搜文件",
                     "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}},
    }
]

_TOOL_ROUND = [
    {"role": "system", "content": "你是助手"},
    {"role": "user", "content": "搜索文件"},
    {"role": "assistant", "content": None,
     "tool_calls": [{"id": "call_1", "type": "function",
                     "function": {"name": "search_files", "arguments": '{"q": "x"}'}}]},
    {"role": "tool", "tool_call_id": "call_1", "content": '{"found": true}'},
]


class TestLoopStopsPreConverting:
    def test_conversion_helpers_are_gone(self):
        """两个转换方法不得回来——回来了就是第二份定义又长出来了。"""
        assert not hasattr(AnthropicLoop, "_convert_messages_to_anthropic"), (
            "AnthropicLoop 又自带消息转换了：路由层那份是唯一的线形状实现"
        )
        assert not hasattr(AnthropicLoop, "_convert_tools_to_anthropic"), (
            "AnthropicLoop 又自带 tools 转换了：input_schema 由 provider 层拼"
        )

    def test_build_request_hands_openai_shapes(self):
        loop = _makeLoop()
        params = asyncio.run(loop._build_request(_OPENAI_TOOLS, None, list(_TOOL_ROUND)))

        assert params["messages"] == _TOOL_ROUND, (
            "环交出去的必须是 OpenAI 形态原样：改写它等于在 provider 层之外又转一遍"
        )
        assert params["tools"] == _OPENAI_TOOLS

    def test_wire_only_anthropic_literals_stay_out_of_the_loop(self):
        """`computer_*` 版本串是线协议细节，只能出现在 provider 层。"""
        for cls in (AnthropicLoop, OpenAILoop):
            src = inspect.getsource(cls)
            assert "computer_20241022" not in src, (
                f"{cls.__name__} 里出现线协议版本串：Agent 环不该知道哪版协议"
            )


class TestComputerToolTravelsNeutral:
    async def _handler(self):
        class _H:
            async def get_dimensions(self):
                return 1280, 800

            async def get_environment(self):
                return "en"

        return _H()

    def test_computer_tool_is_a_capability_descriptor(self):
        loop = _makeLoop()
        handler = asyncio.run(self._handler())
        params = asyncio.run(loop._build_request(None, handler, [{"role": "user", "content": "点一下"}]))

        tool = params["tools"][0]
        assert tool["type"] == "computer", f"该交中立描述符，实际 {tool!r}"
        assert (tool["display_width_px"], tool["display_height_px"]) == (1280, 800)
        assert tool["name"] == "computer"
