"""红绿灯 TDD：OpenAILoop._predict_stream 流式事件契约。

根因：_predict_stream 期望 chat_stream 产出
{"type": "content"|"reasoning"|"tool_calls"|"done", "data": ...} 字典事件，
但 multi_model_client.chat_stream 实际逐 chunk 产出 LLMResponse 对象
（llm_client.chat_stream_async）。非 dict 分支把 str(LLMResponse)（dataclass
repr）当作正文流出，reasoning/tool_calls 全部丢失，"done" 事件永不产生，
工具循环与思考过程在流式路径下整体失效。

本测试以 LLMResponse chunk 序列为输入，断言目标契约：
1. reasoning/content 逐 chunk 增量转发为 typed 事件；
2. 流式 tool_calls 分片（首片带 id/name，后续仅 arguments 片段，按 index 合并）
   合并为一条完整 tool_call 事件后执行，tool_result 事件随之产出；
3. 工具执行后以流式续写（而非一次性整块），整个生成器恰好一个 done 事件，
   done.reply 为最终轮正文快照；
4. chat_stream 包装的 {"error": ...} 必须抛错让管线降级，而不是静默空回复。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse


def make_loop():
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.tool_router = SimpleNamespace(
        execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
    )
    loop = OpenAILoop(agent)
    return loop


class ChunkLLM:
    """按轮次依次产出预设 chunk 的假流式客户端。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []

    async def chat_stream(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), "kwargs": dict(kwargs)})
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk


async def collect(gen):
    return [event async for event in gen]


class TestStreamReasoningAndContent:
    def test_incremental_reasoning_and_content_events(self):
        loop = make_loop()
        llm = ChunkLLM(
            [
                [
                    LLMResponse(content="", reasoning_content="先想一步。"),
                    LLMResponse(content="", reasoning_content="再想一步。"),
                    LLMResponse(content="你好，"),
                    LLMResponse(content="世界。"),
                    LLMResponse(content="", finish_reason="stop"),
                ]
            ]
        )
        loop.llm_client = llm
        loop.agent.llm_client = llm

        events = asyncio.run(
            collect(loop._predict_stream({"messages": [{"role": "user", "content": "hi"}], "stream": True}))
        )
        types = [e["type"] for e in events]
        assert types == ["reasoning", "reasoning", "content", "content", "done"], types
        assert [e["data"] for e in events if e["type"] == "reasoning"] == ["先想一步。", "再想一步。"]
        assert [e["data"] for e in events if e["type"] == "content"] == ["你好，", "世界。"]
        assert events[-1]["reply"] == "你好，世界。"
        assert events[-1]["finish_reason"] == "stop"


class TestStreamToolCallDeltaMerge:
    def test_split_tool_call_deltas_merged_executed_then_streamed_continuation(self):
        loop = make_loop()
        round1 = [
            LLMResponse(content="", reasoning_content="需要搜索。"),
            # 流式 tool_calls 分片：首片带 id/name，后续仅 arguments 片段
            LLMResponse(
                tool_calls=[
                    {"index": 0, "id": "call_1", "type": "function",
                     "function": {"name": "web_search", "arguments": ""}}
                ]
            ),
            LLMResponse(
                tool_calls=[
                    {"index": 0, "id": None, "type": None,
                     "function": {"name": None, "arguments": "{\"query\":"}}
                ]
            ),
            LLMResponse(
                tool_calls=[
                    {"index": 0, "id": None, "type": None,
                     "function": {"name": None, "arguments": " \"天气\"}"}}
                ],
                finish_reason="tool_calls",
            ),
        ]
        round2 = [
            LLMResponse(content="", reasoning_content="拿到结果了。"),
            LLMResponse(content="今天"),
            LLMResponse(content="天气晴。"),
            LLMResponse(content="", finish_reason="stop"),
        ]
        llm = ChunkLLM([round1, round2])
        loop.llm_client = llm
        loop.agent.llm_client = llm

        events = asyncio.run(
            collect(loop._predict_stream({"messages": [{"role": "user", "content": "查天气"}], "stream": True}))
        )
        types = [e["type"] for e in events]
        assert types == [
            "reasoning", "tool_call", "tool_result",
            "reasoning", "content", "content", "done",
        ], types

        tool_call_ev = next(e for e in events if e["type"] == "tool_call")
        fn = tool_call_ev["data"]["function"]
        assert fn["name"] == "web_search"
        assert json.loads(fn["arguments"]) == {"query": "天气"}, "分片 arguments 必须按 index 合并为完整 JSON"
        assert tool_call_ev["data"]["id"] == "call_1"

        # 续写必须是第二次流式调用，且带上了 tool 结果消息
        assert len(llm.calls) == 2, "工具执行后应发起续写调用"
        assert any(m.get("role") == "tool" for m in llm.calls[1]["messages"]), (
            "续写消息必须包含 tool 结果"
        )

        # 整个生成器恰好一个 done，reply 为最终轮正文
        done_events = [e for e in events if e["type"] == "done"]
        assert len(done_events) == 1
        assert done_events[0]["reply"] == "今天天气晴。"


class TestStreamErrorPropagation:
    def test_error_dict_raises_instead_of_silent_empty_reply(self):
        loop = make_loop()
        llm = ChunkLLM([[{"error": "No client available"}]])
        loop.llm_client = llm
        loop.agent.llm_client = llm

        try:
            asyncio.run(
                collect(loop._predict_stream({"messages": [{"role": "user", "content": "hi"}], "stream": True}))
            )
        except RuntimeError as e:
            assert "No client available" in str(e)
        else:
            raise AssertionError("chat_stream 的 error 字典必须抛出 RuntimeError，不能静默返回空回复")
