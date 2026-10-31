"""交叠会话的轮次态必须各归各（交接文档 2026-10-31 C1 / Issue #268）。

修前 `_rounds`、`_gate_runner`、`agent._round_usage` 三件仍挂在 per-agent 单例
loop/agent 上：同一 agent 两会话交叠时，B 的入口会替换/清零 A 正在用的状态。
本用例让 A 停在第一轮工具调用之后、第二轮之前，B 整轮跑完，再放行 A：

- 用量：A 的两轮各 10 → 20；B 一轮 20。修前两轮共写同一个 agent 属性，A 读到 40、
  B 读到 30（互相污染）。
- 轮间标志：B 的入口不得替换 A 的 `rounds`（`lengthEmptyRetried` 哨兵必须存活）。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse


def make_loop():
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.tool_router = SimpleNamespace(
        execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
    )
    return OpenAILoop(agent)


async def collect(gen):
    return [event async for event in gen]


def _usage(total: int):
    return SimpleNamespace(prompt_tokens=total - 4, completion_tokens=4, total_tokens=total)


class InterleavedLLM:
    """A 第一轮出工具调用、第二轮阻塞到放行；B 一轮完成。"""

    def __init__(self):
        self.blockedA = asyncio.Event()
        self.releaseA = asyncio.Event()
        self.aCalls = 0

    async def chat_stream(self, messages, **kwargs):
        isA = any(m.get("role") == "user" and m.get("content") == "A" for m in messages)
        if isA:
            self.aCalls += 1
            if self.aCalls == 1:
                yield LLMResponse(
                    tool_calls=[
                        {"index": 0, "id": "call_a1", "type": "function",
                         "function": {"name": "web_search", "arguments": "{}"}}
                    ],
                    usage=_usage(10),
                    finish_reason="tool_calls",
                )
                return
            self.blockedA.set()
            await self.releaseA.wait()
            yield LLMResponse(content="A完成", usage=_usage(10), finish_reason="stop")
            return
        yield LLMResponse(content="B完成", usage=_usage(20), finish_reason="stop")


@pytest.mark.asyncio
async def test_overlapping_turns_keep_usage_and_rounds_separate():
    loop = make_loop()
    llm = InterleavedLLM()
    loop.llm_client = llm
    loop.agent.llm_client = llm

    messagesA = [{"role": "user", "content": "A"}]
    messagesB = [{"role": "user", "content": "B"}]
    stateA = loop._startTurnState(messagesA)
    stateB = loop._startTurnState(messagesB)

    taskA = asyncio.create_task(
        collect(loop._predict_stream({"messages": messagesA, "stream": True}, stateA))
    )
    await asyncio.wait_for(llm.blockedA.wait(), timeout=5)
    # A 停在第二轮入口：把"本轮标志"放一个哨兵，B 整轮跑完后必须还在。
    stateA.rounds.lengthEmptyRetried = True

    eventsB = await collect(loop._predict_stream({"messages": messagesB, "stream": True}, stateB))
    llm.releaseA.set()
    eventsA = await asyncio.wait_for(taskA, timeout=5)

    doneA = [e for e in eventsA if e.get("type") == "done"][-1]
    doneB = [e for e in eventsB if e.get("type") == "done"][-1]

    assert doneA["usage"]["total_tokens"] == 20, (
        f"A 自己的两轮合计应为 20，实得 {doneA['usage']}（被 B 的用量污染）"
    )
    assert doneB["usage"]["total_tokens"] == 20, (
        f"B 一轮应为 20，实得 {doneB['usage']}（继承了 A 的累计）"
    )
    assert stateA.roundUsage["total_tokens"] == 20
    assert stateB.roundUsage["total_tokens"] == 20
    assert stateA.rounds is not stateB.rounds, "两会话不得共用同一份轮间标志"
    assert stateA.rounds.lengthEmptyRetried is True, "B 的入口清零了 A 的轮间标志"
