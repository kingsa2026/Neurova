# -*- coding: utf-8 -*-
"""工具循环迭代化（Issue #268 切片 B）——递归形态的机器判据。

根因（方案 §5.2 与切片 A 之后的残余）：轮次态已随 `TurnRunState` 传递（切片 A），
但控制流仍是递归：非流式 `_predict_normal` 自调用（主回环 / 工具超限 / 出口续跑），
流式 `_predict_stream` ↔ `_predict_stream_once` 互递归，溢出与 length 空回复恢复
再各自套一层 `async for … in self._predict_stream(...)`，出口续跑再进一次。

递归本身不炸（方案 §1 实测：默认 `recursionlimit` 下可嵌套 493 轮，远高于合法上限
100），**但它把"这一轮"这件事切成了多层栈帧**：轮次态、门控执行器、溢出恢复的
重试标记都必须逐层手工传递，漏传一处就是一个只在多轮 + 特定分支下才现形的缺陷
（切片 A 的 `_settleMainExit` 不传 state 即同型）。故本片把它拉平成一条
`while`：一轮一次迭代，栈深与轮数解耦。

判据（每条都要求"改前实测不成立、改后成立"）：
1. `openai_loop.py` 内不得再有自调用形态（`self._predict_normal(` /
   `self._predict_stream(` / `self._predict_stream_once(`）——静态反证；
2. 栈深与轮数解耦——活体量：同一个多轮工具环里，各轮"请求发出瞬间"的
   `asyncio` 可观测调用深度三档（1 / 10 / 50 轮）差为 0（递归形态下随轮数线性增长）；
3. 溢出恢复：折叠重试**不丢失已产出的正文事件**、不重复 yield 同一段正文；
4. 事件次序契约不变（流式工具环的 typed 事件序列）。

替身只放在模型边界（`chat` / `chat_stream`）与工具执行边界
（`handle_tool_calls`）；门控、装配、轮次预算、溢出恢复全部走生产代码。
"""

from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse, TokenLimitExceeded

OPENAI_LOOP = Path(__file__).resolve().parents[3] / "neurova" / "agent" / "loops" / "openai_loop.py"


def _src() -> str:
    return OPENAI_LOOP.read_text(encoding="utf-8")


def _llmConfig():
    return SimpleNamespace(
        temperature=None, max_tokens=None, top_p=None, frequency_penalty=None, model="gpt-4o",
    )


class ScriptedRounds:
    """模型边界替身：同一个脚本驱动两条 loop 路径，记录每次调用的消息序列。"""

    def __init__(self, rounds):
        self.config = _llmConfig()
        self.rounds = list(rounds)
        self.calls = []

    def _next(self, messages):
        self.calls.append(list(messages))
        return self.rounds[min(len(self.calls) - 1, len(self.rounds) - 1)]

    async def chat(self, messages, **kwargs):
        """非流式：脚本项允许单条 `LLMResponse`（常见形态），也允许列表（取首条响应）。"""
        payload = self._next(messages)
        if isinstance(payload, LLMResponse):
            return payload
        for chunk in payload:
            if isinstance(chunk, LLMResponse):
                return chunk
        return LLMResponse(content="", finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        payload = self._next(messages)
        rounds = payload if isinstance(payload, list) else [payload]
        for chunk in rounds:
            yield chunk


def toolRound(callId="c1", name="probe_read", arguments="{}"):
    return LLMResponse(
        tool_calls=[{
            "index": 0, "id": callId, "type": "function",
            "function": {"name": name, "arguments": arguments},
        }],
        finish_reason="tool_calls",
    )


class RoundProbeGate:
    """只做观测与轮数断点的门控。

    两个用途，都不改变判定语义：
    1. 关掉 `GoalGate` 的缺省 `max_rounds=15` 截断——`_buildGateRunner` 里 `spec` 一旦
       存在，GoalGate 的规格就替代默认构造；探针只声明足够大的预算，让 50 轮工具环
       真的跑到 50 轮（测轮数上限需要长环，而缺省 15 轮会让读数停在 14）。
    2. 在轮内分派点量栈深——它是轮末必经的同步调用，位置对两条路径一致。
    """

    name = "round_probe"
    priority = 99

    def __init__(self, breakAt=None):
        self.rounds = []
        self.breakAt = breakAt

    def check(self, ctx):
        from neurova.agent.gates import StopDecision

        rounds = int(ctx.get("tool_rounds") or 0)
        self.rounds.append((rounds, _frameDepth()))
        if self.breakAt is not None and rounds >= self.breakAt:
            return StopDecision.terminate(f"探针断点：第 {rounds} 轮", self.name)
        return StopDecision.bypass()


def makeLoop(chat, toolRounds=10):
    """真实 `OpenAILoop`：模型边界与工具执行边界用替身，其余全走本仓实现。"""
    agent = SimpleNamespace(
        llm_client=chat,
        config=SimpleNamespace(name="probe", user_id="u1", agent_id="a1", llm_model="gpt-4o"),
        _tool_messages_list=[],
        _round_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        skill_registry=None,
        _skill_registry=None,
        tool_router=None,
        tool_memory=None,
        tool_lifecycle=None,
        skill_packer=None,
        current_session_id="s-slice-b",
        set_current_reasoning=lambda text: None,
    )
    loop = OpenAILoop(agent)
    loop.llm_client = chat
    loop._max_tool_rounds = toolRounds
    # 探针门控：让长工具环不被 GoalGate 缺省预算截断，并在轮末量栈深
    probe = RoundProbeGate()
    loop.registerGate(probe)
    loop._goal_gate_spec = {"goal": {}, "completion_check": None, "max_rounds": 1000}
    executed = {"rounds": 0, "depth": [], "probe": probe}

    async def handle_tool_calls(calls, messages):
        executed["rounds"] += 1
        executed["depth"].append(_frameDepth())
        return [
            {"role": "tool", "tool_call_id": c["id"], "name": "probe_read", "content": "结果"}
            for c in calls
        ]

    loop.handle_tool_calls = handle_tool_calls
    return loop, executed


def _frameDepth() -> int:
    """当前解释器调用栈的帧数（同进程内可比的相对值）。

    递归形态下"第 N 轮"是叠在第 N-1 轮的 `await` 之上的：`_predict_normal` /
    `_predict_stream` 每推进一轮就多留一层帧，读数随轮数线性增长；迭代形态里
    每一轮都在同一层 `while` 上跑完，读数恒定。

    用 `sys._getframe().f_back` 链而不是协程对象链：后者在 `await` 展开后
    `cr_await` 只留最内层一帧（实测父子协程 chain 长度恒为 1），量不到嵌套。
    绝对帧数随解释器与调用路径变化，故判据只看三档轮数之间**差为 0**。
    """
    import sys

    depth = 0
    frame = sys._getframe()
    while frame is not None:
        depth += 1
        frame = frame.f_back
    return depth


async def _collect(gen):
    return [event async for event in gen]


class TestNoSelfRecursionInToolLoops:
    """判据 1（静态）：轮次推进不得靠自调用。"""

    def test_streamPathHasNoSelfCall(self):
        src = _src()
        hits = [
            line.strip()
            for line in src.splitlines()
            if re.search(r"async for\s+\w+\s+in\s+self\._predict_stream\(", line)
        ]
        assert not hits, (
            "流式路径仍有 `async for … in self._predict_stream(...)` 自调用——"
            f"轮次推进靠嵌套生成器委托，栈深随轮数增长：{hits}"
        )

    def test_normalPathHasNoSelfCall(self):
        src = _src()
        hits = [
            line.strip()
            for line in src.splitlines()
            if re.search(r"return await self\._predict_normal\(", line)
        ]
        assert not hits, (
            "非流式路径仍有 `return await self._predict_normal(...)` 自调用——"
            f"主回环/出口续跑靠尾递归推进：{hits}"
        )

    def test_streamEntryDoesNotRecurseIntoItself(self):
        """`_predict_stream` 不得调用 `_predict_stream_once`（反之亦然）的自我委托环。"""
        src = inspect.getsource(OpenAILoop._predict_stream)
        assert "self._predict_stream_once(" not in src, (
            "`_predict_stream` 仍以生成器委托方式调用 `_predict_stream_once`；"
            "迭代化后单轮逻辑应就地展开，不再成环"
        )


class TestStackDepthIsDecoupledFromRounds:
    """判据 2（活体）：三档轮数的 await 链深度差为 0。"""

    @pytest.mark.parametrize("rounds", [1, 10, 50])
    def test_frameDepthConstantAcrossRounds(self, rounds, monkeypatch):
        # 经生产配置点设上限：`max_loop_rounds` 合法域被夹在 [2, 200]，
        # 工具轮上限 = max_loop_rounds // 2（单源，不在此另立一份尺度）
        monkeypatch.setenv("NEUROVA_AGENT_MAX_LOOP_ROUNDS", str(min(200, (rounds + 5) * 2)))
        script = [toolRound(f"c{i}", arguments='{"q": "%d"}' % i) for i in range(rounds)]
        script.append(LLMResponse(content="收尾", finish_reason="stop"))
        chat = ScriptedRounds(script)
        loop, executed = makeLoop(chat, toolRounds=rounds + 5)
        asyncio.run(loop.predict_step([{"role": "user", "content": "跑工具"}], stream=False))

        assert executed["rounds"] == rounds, (
            f"工具轮数应为 {rounds}，实测 {executed['rounds']}（脚本或上限判据有误）"
        )
        depths = [depth for _round, depth in executed["probe"].rounds]
        assert len(depths) == rounds, f"门控探针轮数应为 {rounds}，实测 {len(depths)}"
        assert len(set(depths)) == 1, (
            f"轮末门控点的解释器栈深随轮数增长（递归形态）：{depths}"
        )

    def test_normalRoundsDoNotGrowDepth(self, monkeypatch):
        """非流式三档轮数的深度逐档相等（与流式分开取，两条路径各自成判据）。"""
        measured = {}
        for rounds in (1, 10, 50):
            monkeypatch.setenv("NEUROVA_AGENT_MAX_LOOP_ROUNDS", str(min(200, (rounds + 5) * 2)))
            script = [toolRound(f"c{i}", arguments='{"q": "%d"}' % i) for i in range(rounds)]
            script.append(LLMResponse(content="收尾", finish_reason="stop"))
            loop, executed = makeLoop(ScriptedRounds(script), toolRounds=rounds + 5)
            asyncio.run(loop.predict_step([{"role": "user", "content": "跑工具"}], stream=False))
            assert len(executed["probe"].rounds) == rounds
            measured[rounds] = executed["probe"].rounds[-1][1]
        assert len(set(measured.values())) == 1, (
            f"非流式轮末栈深随轮数变化：{measured}——轮次推进仍在递归"
        )


class TestEventOrderIsPreserved:
    """判据 4：迭代化不得改变流式事件次序与正文拼接。"""

    def test_streamToolRoundEventSequence(self):
        chat = ScriptedRounds([
            [LLMResponse(content="", reasoning_content="先想一步。"), toolRound("c1")],
            [LLMResponse(content="今天"), LLMResponse(content="天气晴。")],
        ])
        loop, executed = makeLoop(chat)
        events = asyncio.run(_collect(loop._predict_stream({
            "messages": [{"role": "user", "content": "查天气"}], "stream": True,
        })))
        types = [e["type"] for e in events]
        assert types == ["reasoning", "tool_call", "tool_result", "content", "content", "done"], types
        assert events[-1]["reply"] == "今天天气晴。"
        assert executed["rounds"] == 1

    def test_streamUsageStillAggregatedPerCall(self):
        usage = SimpleNamespace(prompt_tokens=100, completion_tokens=30, total_tokens=130)
        chat = ScriptedRounds([
            [toolRound("c1")],
            [LLMResponse(content="完成", usage=usage, finish_reason="stop"),
             LLMResponse(content="", finish_reason="stop")],
        ])
        loop, _ = makeLoop(chat)
        events = asyncio.run(_collect(loop._predict_stream({
            "messages": [{"role": "user", "content": "hi"}], "stream": True,
        })))
        done = [e for e in events if e["type"] == "done"][0]
        assert done["usage"] == {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130}


class _OverflowThenOkClient:
    """模型边界替身：首轮以 `token_limit` 错误 dict 结束，重试轮正常出正文。"""

    def __init__(self, rounds):
        self.config = _llmConfig()
        self.rounds = list(rounds)
        self.calls = []

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(list(messages))
        payload = self.rounds[min(len(self.calls) - 1, len(self.rounds) - 1)]
        if isinstance(payload, dict) and payload.get("error"):
            yield {"error": payload["error"], "error_type": "token_limit"}
            return
        for chunk in payload:
            yield chunk


class TestOverflowRecoveryStaysInOneRound:
    """判据 3：溢出恢复的折叠重试仍是"单次、同一轮"，且不吞掉已产出的正文。"""

    def _bigMessages(self):
        msgs = [{"role": "system", "content": "sys"}]
        for i in range(5):
            msgs.append({"role": "user", "content": f"问题 {i}"})
            msgs.append({
                "role": "assistant", "content": "",
                "tool_calls": [{"id": f"c{i}", "type": "function",
                                "function": {"name": "probe_read", "arguments": "{}"}}],
            })
            msgs.append({"role": "tool", "tool_call_id": f"c{i}", "content": f"结果 {i} " * 200})
            msgs.append({"role": "assistant", "content": f"答 {i}"})
        return msgs

    def test_overflowRetryYieldsContentExactlyOnce(self):
        client = _OverflowThenOkClient([
            {"error": "This model's maximum context length is exceeded"},
            [LLMResponse(content="恢复后的正文"), LLMResponse(content="", finish_reason="stop")],
        ])
        loop, _ = makeLoop(client)
        events = asyncio.run(_collect(loop._predict_stream({"messages": self._bigMessages()})))
        contents = [e["data"] for e in events if e["type"] == "content"]
        assert contents == ["恢复后的正文"], f"折叠重试的正文事件重复或缺席：{contents}"
        assert len(client.calls) == 2, "只允许单次折叠重试（防循环）"
        assert len(client.calls[1]) < len(client.calls[0]), "重试消息必须已折叠"

    def test_secondOverflowStillRaises(self):
        client = _OverflowThenOkClient([
            {"error": "maximum context length is exceeded"},
            {"error": "maximum context length is exceeded"},
        ])
        loop, _ = makeLoop(client)
        with pytest.raises(TokenLimitExceeded):
            asyncio.run(_collect(loop._predict_stream({"messages": self._bigMessages()})))
        assert len(client.calls) == 2
