# -*- coding: utf-8 -*-
"""P3（ZCode agent-loop 对照 #6/#7）：

- #6 工具批按流内序号稳定排序——分片合并保留 `_stream_index`，执行顺序与
  流内声明顺序一致（到达顺序不同也不重排错）；
- #7 工具结果终止回合控制面——工具结果携带 `turn_control` 时，本批结算后
  以诚实文案收口回合，不再开下一轮模型请求。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.agent.loops.turn_phase import TurnPhase
from neurova.llm_client import LLMResponse


def _make_agent():
    return SimpleNamespace(
        llm_client=None,
        config=SimpleNamespace(name="probe", llm_model="gpt-4o"),
        _tool_messages_list=[],
        skill_registry=None,
        _skill_registry=None,
        tool_router=None,
        tool_memory=None,
        tool_lifecycle=None,
        skill_packer=None,
        set_current_reasoning=lambda text: None,
        append_tool_messages=lambda records: None,
    )


class TestStreamIndexStableSort:
    def test_merge_retains_stream_index(self):
        loop = OpenAILoop(_make_agent())
        pending: list = []
        # 分片按 index 顺序到达（真实 provider 形态）：合并后序号保留
        loop._merge_tool_call_delta(pending, {"index": 0, "id": "a", "function": {"name": "t1", "arguments": "{}"}})
        loop._merge_tool_call_delta(pending, {"index": 1, "id": "b", "function": {"name": "t2", "arguments": "{}"}})
        assert [tc.get("_stream_index") for tc in pending] == [0, 1]
        # 无 index 的 delta 退化为追加，序号取当时长度
        loop._merge_tool_call_delta(pending, {"id": "c", "function": {"name": "t3", "arguments": "{}"}})
        assert pending[2].get("_stream_index") == 2

    def test_handle_tool_calls_executes_in_stream_order(self):
        """到达顺序与流内序号不同时，执行按流内序号（稳定排序）。"""
        loop = OpenAILoop(_make_agent())
        calls = [
            {"id": "late", "type": "function",
             "function": {"name": "write_tool", "arguments": "{}"}, "_stream_index": 1},
            {"id": "early", "type": "function",
             "function": {"name": "read_tool", "arguments": "{}"}, "_stream_index": 0},
        ]
        executed: list = []

        async def stubUnit(tc):
            executed.append((tc.get("function") or {}).get("name"))
            msg = {"role": "tool", "tool_call_id": tc.get("id"), "content": "ok"}
            return msg, []

        loop._executeToolCallUnit = stubUnit

        async def scenario():
            return await loop.handle_tool_calls(calls, [])

        msgs = asyncio.run(scenario())
        assert executed == ["read_tool", "write_tool"]
        assert len(msgs) == 2

    def test_unnumbered_calls_keep_arrival_order(self):
        """无序号（非流式/旧数据）：保持到达顺序，不重排。"""
        loop = OpenAILoop(_make_agent())
        calls = [
            {"id": "x", "type": "function", "function": {"name": "t_x", "arguments": "{}"}},
            {"id": "y", "type": "function", "function": {"name": "t_y", "arguments": "{}"}},
        ]
        executed: list = []

        async def stubUnit(tc):
            executed.append((tc.get("function") or {}).get("name"))
            msg = {"role": "tool", "tool_call_id": tc.get("id"), "content": "ok"}
            return msg, []

        loop._executeToolCallUnit = stubUnit

        async def scenario():
            return await loop.handle_tool_calls(calls, [])

        asyncio.run(scenario())
        assert executed == ["t_x", "t_y"]


class TestTurnControlStopsTurn:
    def test_worker_records_turn_control(self, monkeypatch):
        """工具结果携带 turn_control → 执行链写回调用的 tool_call 字典
        （并行子任务里 ContextVar 传不回父任务，故走调用方持有的字典）。"""
        import neurova.agent.native_tool_dispatch as dispatch

        async def fakeExec(agent, name, params):
            return {"success": True, "result": {"ok": True, "turn_control": {"reason": "配额已用尽"}}, "error": None}

        monkeypatch.setattr(dispatch, "execute_native_tool", fakeExec)
        loop = OpenAILoop(_make_agent())
        tool_call = {"id": "c1", "type": "function",
                     "function": {"name": "some_tool", "arguments": "{}"}}
        asyncio.run(loop._executeToolCallUnit(tool_call))
        assert tool_call.get("_turn_control", {}).get("reason") == "配额已用尽"

    def test_loop_finishes_turn_on_turn_control(self, monkeypatch):
        """工具批命中 turn_control：一轮工具执行后即收口，不开第二次模型请求。"""
        import neurova.agent.native_tool_dispatch as dispatch

        async def fakeExec(agent, name, params):
            return {"success": True,
                    "result": {"ok": True, "turn_control": {"reason": "任务配额已用尽"}},
                    "error": None}

        monkeypatch.setattr(dispatch, "execute_native_tool", fakeExec)

        class OneToolCallChat:
            config = SimpleNamespace(
                temperature=None, max_tokens=None, top_p=None, frequency_penalty=None,
                model="gpt-4o",
            )

            def __init__(self):
                self.calls = 0

            async def chat(self, messages, **kwargs):
                self.calls += 1
                return LLMResponse(
                    content="",
                    tool_calls=[{"id": "c1", "type": "function",
                                 "function": {"name": "some_tool", "arguments": "{}"}}],
                    finish_reason="tool_calls",
                )

        agent = _make_agent()
        chat = OneToolCallChat()
        agent.llm_client = chat
        loop = OpenAILoop(agent)

        async def scenario():
            return await loop.predict_step([{"role": "user", "content": "问"}])

        result = asyncio.run(scenario())
        assert chat.calls == 1, "turn_control 命中后不得开第二次模型请求"
        assert "任务配额已用尽" in (result.content or "")
        assert "收口" in (result.content or "")
