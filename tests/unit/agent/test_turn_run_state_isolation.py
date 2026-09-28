"""轮次态归属红测（G1 方案 §8.1，Issue #268）。

根因（缺陷 A）：轮次控制状态（`_tool_rounds` / `_stagnation_count` /
`_round_user_key` / 门控会话窗口）挂在 loop 实例上，而 loop 是 per-agent 单例
（`agent_core.py` 的 `loop_manager.get_loop()`）。同一 agent 上两个会话交叠时，
后进入者 `predict_step` 入口的清零会改写前一个会话正在累加的计数。

判据（三条都要求会话交叠时的读数与会话单独跑时**一致**）：
1. 轮次预算：B 会话单独跑收敛的调用次数，不因 A 会话交叠而变多；
2. 死循环窗口：A 会话的调用签名不得进入 B 会话的窗口（B 不得被判重复）；
3. 停滞计数：A 会话入口不得把 B 会话正在累加的停滞计数清零。

替身只放在模型边界（`chat` / `chat_stream`）与工具执行边界
（`handle_tool_calls` 返回 tool 消息）；被断言的计数与门控全部走真实 loop 代码。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse

STAGNATION_HINT = "检测到重复的工具调用模式"
AGENT_LIMITS = {"token_budget": 100000, "max_loop_rounds": 4}


def _llm_config():
    return SimpleNamespace(
        temperature=None,
        max_tokens=None,
        top_p=None,
        frequency_penalty=None,
        model="gpt-4o",
    )


class ScriptedChat:
    """模型边界替身：按会话（首条 user 内容）分别出牌，并把每次收到的消息留档。"""

    def __init__(self, rounds):
        self.config = _llm_config()
        self.rounds = rounds            # {会话名: [LLMResponse, ...]}
        self.calls = {}                 # {会话名: [messages, ...]}

    def _who(self, messages):
        return str(messages[0].get("content") or "")[:1]

    async def chat(self, messages, **kwargs):
        who = self._who(messages)
        self.calls.setdefault(who, []).append([dict(m) for m in messages])
        script = self.rounds[who]
        idx = min(len(self.calls[who]) - 1, len(script) - 1)
        return script[idx]


def tool_call_response(call_id, name="web_search", arguments="{}"):
    """构造工具调用响应。

    `arguments` 必须逐轮区分（见 `TestDoomLoopWindowIsPerTurn`）：参数相同即签名相同，
    会被死循环门正确地判成重复调用，与被交叠会话无关。
    """
    return LLMResponse(
        content="",
        tool_calls=[{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": arguments},
        }],
        finish_reason="tool_calls",
    )


def make_loop(chat, max_tool_rounds=2, suspend_at=None):
    """真实 OpenAILoop：模型边界与工具执行边界用替身，其余全走本仓实现。"""
    agent = SimpleNamespace(
        llm_client=chat,
        config=SimpleNamespace(name="probe", llm_model="gpt-4o"),
        _round_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        _tool_messages_list=[],
        skill_registry=None,
        _skill_registry=None,
        tool_router=None,
        tool_memory=None,
        tool_lifecycle=None,
        skill_packer=None,
        set_current_reasoning=lambda text: None,
    )
    loop = OpenAILoop(agent)
    loop.llm_client = chat
    loop._max_tool_rounds = max_tool_rounds
    state = {"held": None, "rounds": 0}

    async def handle_tool_calls(calls, messages):
        state["rounds"] += 1
        if suspend_at and state["rounds"] == suspend_at:
            state["held"] = asyncio.get_running_loop().create_future()
            await state["held"]
        return [
            {"role": "tool", "tool_call_id": c["id"], "content": "结果"}
            for c in calls
        ]

    loop.handle_tool_calls = handle_tool_calls
    return loop, state


class TestRoundBudgetIsPerTurn:
    def test_concurrentTurnDoesNotRewriteOtherTurnRoundBudget(self):
        """A 会话入口的清零不得改写 B 会话正在累加的轮次计数。"""
        rounds = {"B": [tool_call_response(f"b{i}") for i in range(8)],
                  "A": [LLMResponse(content="A 的普通回复", finish_reason="stop")]}

        async def scenario_conflicting():
            chat = ScriptedChat(rounds)
            loop, state = make_loop(chat, max_tool_rounds=2, suspend_at=1)
            taskB = asyncio.create_task(
                loop.predict_step([{"role": "user", "content": "B 会话"}])
            )
            while state["held"] is None:
                await asyncio.sleep(0)
            await loop.predict_step([{"role": "user", "content": "A 会话"}])
            state["held"].set_result(True)
            await taskB
            return len(chat.calls["B"])

        async def scenario_solo():
            chat = ScriptedChat(rounds)
            loop, _ = make_loop(chat, max_tool_rounds=2)
            await loop.predict_step([{"role": "user", "content": "B 会话"}])
            return len(chat.calls["B"])

        solo = asyncio.run(scenario_solo())
        interleaved = asyncio.run(scenario_conflicting())
        assert solo == 3, f"B 会话单独跑应在上限 2 的下一轮收尾（3 次调用），实际 {solo}"
        assert interleaved == solo, (
            f"B 会话的轮次预算被 A 会话改写：单独跑 {solo} 次调用，交叠时 {interleaved} 次"
        )


class TestDoomLoopWindowIsPerTurn:
    def test_otherTurnSignatureDoesNotPolluteThisTurnWindow(self):
        """A 会话的调用签名不得被 B 会话判成重复调用。

        构造要点：B 的**每一轮工具调用签名必须彼此不同**。门控判据是"调用签名
        在窗口内重复"，若 B 自己两轮发出同签名的调用（如各轮都用 `web_search({})`），
        死循环门判重复是**正确行为**，与 A 会话无关——那样的断言会自我触发
        （实测：B 单独跑也会在第 2 轮收到重复提示，交叠与否都一样）。
        故这里让 B 各轮参数不同，只剩"A 的签名是否漏进 B 的窗口"这一个变量。
        """
        rounds = {
            "B": [
                tool_call_response("shared", arguments='{"q": "b1"}'),
                tool_call_response("b2", arguments='{"q": "b2"}'),
                # 收尾轮：不再调工具（B 必须能自然收口，否则脚本尾项会被反复
                # 复用成自己的"重复调用"，污染判据的来源就说不清了）
                LLMResponse(content="B 完成", finish_reason="stop"),
            ],
            "A": [tool_call_response("shared", arguments='{"q": "a1"}')],
        }

        async def scenario_conflicting():
            chat = ScriptedChat(rounds)
            loop, state = make_loop(chat, max_tool_rounds=5, suspend_at=1)
            taskB = asyncio.create_task(
                loop.predict_step([{"role": "user", "content": "B 会话"}])
            )
            while state["held"] is None:
                await asyncio.sleep(0)
            await loop.predict_step([{"role": "user", "content": "A 会话"}])
            state["held"].set_result(True)
            await taskB
            return chat.calls["B"]

        calls = asyncio.run(scenario_conflicting())
        polluted = [
            msgs for msgs in calls
            if any(STAGNATION_HINT in str(m.get("content") or "") for m in msgs)
        ]
        assert not polluted, (
            f"A 会话的签名进入了 B 会话的死循环窗口：B 的第 {len(polluted)} 次请求被注入重复调用提示"
        )


class TestStagnationCountIsPerTurn:
    def test_otherTurnEntryDoesNotResetThisTurnStagnation(self):
        """A 会话入口不得把 B 会话正在累加的停滞计数清零。"""
        same_reply = "我搜索一下。"
        rounds = {"B": [tool_call_response(f"b{i}") for i in range(8)],
                  "A": [LLMResponse(content="A 的普通回复", finish_reason="stop")]}

        async def scenario(suspend_at):
            chat = ScriptedChat(rounds)

            async def _call(messages, **kwargs):
                who = str(messages[0].get("content") or "")[:1]
                chat.calls.setdefault(who, []).append([dict(m) for m in messages])
                idx = min(len(chat.calls[who]) - 1, len(rounds[who]) - 1)
                resp = rounds[who][idx]
                if who == "B":
                    # 每轮内容完全一致：停滞检测必须逐轮累加
                    resp = LLMResponse(
                        content=same_reply,
                        tool_calls=resp.tool_calls,
                        finish_reason="tool_calls",
                    )
                return resp

            chat.chat = _call
            loop, state = make_loop(chat, max_tool_rounds=6, suspend_at=suspend_at)
            if suspend_at is None:
                await loop.predict_step([{"role": "user", "content": "B 会话"}])
            else:
                taskB = asyncio.create_task(
                    loop.predict_step([{"role": "user", "content": "B 会话"}])
                )
                while state["held"] is None:
                    await asyncio.sleep(0)
                await loop.predict_step([{"role": "user", "content": "A 会话"}])
                state["held"].set_result(True)
                await taskB
            return len(chat.calls["B"])

        solo = asyncio.run(scenario(None))
        interleaved = asyncio.run(scenario(1))
        assert interleaved == solo, (
            f"B 会话的停滞计数被 A 会话入口清零：单独跑 {solo} 次调用，交叠时 {interleaved} 次"
        )


class TestAnthropicLoopStateOwnership:
    """Anthropic 侧同一根因的第二命中点（教义第 5 条）。

    `AnthropicLoop` 同样把轮次计数挂在实例上，且上限硬编码 10、
    经公有 `predict_step` 自递归（`_top_level=False` 绕开入口清零）。
    """

    def _make_loop(self, chat):
        from neurova.agent.loops.anthropic_loop import AnthropicLoop

        agent = SimpleNamespace(
            llm_client=chat,
            config=SimpleNamespace(name="probe", llm_model="claude-3-5-sonnet"),
            set_current_reasoning=lambda text: None,
            _tool_messages_list=[],
        )
        loop = AnthropicLoop(agent)
        loop.llm_client = chat

        async def handle_tool_calls(calls, messages):
            return [{"role": "tool", "tool_call_id": c["id"], "content": "结果"} for c in calls]

        loop.handle_tool_calls = handle_tool_calls
        return loop

    def test_no_recursionGuardFlagOnPublicEntry(self):
        """公有入口签名不得再带 `_top_level` 这类内部递归补丁参数。"""
        import inspect

        from neurova.agent.loops.anthropic_loop import AnthropicLoop

        src = inspect.getsource(AnthropicLoop.predict_step)
        assert "_top_level" not in src, (
            "公有 predict_step 仍靠 `_top_level` 区分内外层调用——这是为绕开"
            "「公有入口自递归」而生的第二份控制通道，状态显式传递后必须删净"
        )

    def test_roundBudgetFollowsConfigurationNotHardcoded(self, monkeypatch):
        """轮次上限取自生产配置点，不硬编码 10。

        T-04 把这条上限收成**一份派生**（`turn_run_state.resolveToolRoundBudget()`）：
        守卫与 `IterationGate` 同取它，不再有 `// 2` 的第二个尺度。故本用例的
        期望值改为**问生产要那个数**，而不是在测试里复算一遍折半——测试里复算
        等于把旧尺度抄成第二份定义，收口后它会继续替旧形态背书。
        """
        monkeypatch.setenv("NEUROVA_AGENT_MAX_LOOP_ROUNDS", "2")
        from neurova.agent.loops.turn_run_state import resolveToolRoundBudget

        expected = resolveToolRoundBudget()

        class _AlwaysToolCalls:
            def __init__(self):
                self.calls = 0

            async def chat(self, messages, **kwargs):
                self.calls += 1
                return tool_call_response(f"c{self.calls}")

        chat = _AlwaysToolCalls()
        loop = self._make_loop(chat)
        asyncio.run(loop.predict_step([{"role": "user", "content": "hi"}], []))
        assert chat.calls == expected + 1, (
            f"配置 max_loop_rounds=2 时 Anthropic 侧应停在第 {expected + 1} 次调用，"
            f"实际 {chat.calls} 次（硬编码上限 10 的形态）"
        )

    def test_concurrentTurnDoesNotRewriteOtherTurnCounter(self):
        """Anthropic 侧的轮次计数同样不得跨调用存活：交叠与否读数一致。"""

        class _PerSession:
            """按会话（首条 user 内容）计数，永远返回工具调用（不会自然收尾）。"""

            def __init__(self):
                self.counts = {}

            async def chat(self, messages, **kwargs):
                # 会话标识取转换后的 Anthropic 文本块（首块常为 system 之外的用户文本）
                blob = json.dumps(messages, ensure_ascii=False)[:400]
                who = "A" if "A 会话" in blob else "B"
                n = self.counts.get(who, 0) + 1
                self.counts[who] = n
                return tool_call_response(f"{who}{n}")

        async def run(interleaved):
            chat = _PerSession()
            loop = self._make_loop(chat)
            state = {"held": None, "calls": 0}
            original = loop.handle_tool_calls

            async def handle(calls, messages):
                state["calls"] += 1
                if interleaved and state["calls"] == 1:
                    state["held"] = asyncio.get_running_loop().create_future()
                    await state["held"]
                return await original(calls, messages)

            loop.handle_tool_calls = handle
            if not interleaved:
                await loop.predict_step([{"role": "user", "content": "B 会话"}], [])
            else:
                task = asyncio.create_task(
                    loop.predict_step([{"role": "user", "content": "B 会话"}], [])
                )
                while state["held"] is None:
                    await asyncio.sleep(0)
                await loop.predict_step([{"role": "user", "content": "A 会话"}], [])
                state["held"].set_result(True)
                await task
            return chat.counts["B"]

        solo = asyncio.run(run(False))
        interleaved = asyncio.run(run(True))
        assert solo == interleaved, (
            f"Anthropic 侧轮次计数被交叠会话改写：单独跑 {solo} 次，交叠时 {interleaved} 次"
        )
