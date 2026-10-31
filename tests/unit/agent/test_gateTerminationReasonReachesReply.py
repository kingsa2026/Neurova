# -*- coding: utf-8 -*-
"""门控终止原因必须进正文（2026-10-22 default 会话「停在半截」事故）。

事故形态：一次回合被 `TokenBudgetGate` 以「累计 token 达到预算上限 100000」终止，
落库的助手正文停在一个冒号上（「命令被分段审批拦截了。我改用单条命令重试：」），
用户完全看不出这是被门控掐断的——看起来像模型自己说了一半就没了。

根因不是"门控太严"，而是**门控的终止理由只写不读**：

1. 两条环的工具轮 TERMINATE 只 `yield {"type":"gate_terminate"}` 就 `return`，
   **连 done 都不发**（openai_loop.py:922-931、anthropic_loop.py:303-306）——整条流
   "恰好一个 done"的契约在这条路上根本不成立，管道侧的 done 兜底也就无从执行；
2. `gate_terminate` 在 `chat_pipeline._call_loop_stream` 里**没有分支**
   （content/done/reasoning/retry_status/tool_call/tool_result 五种之外，其余一律不入
   回复），全仓除测试与 manual 脚本外零消费者——`openai_loop.py:907` 的注释写着
   「由 chat_pipeline 终止循环」，而被点名的那一支不存在（文档承诺与实测相反）；
3. 非流式路径连事件都没有：TERMINATE 直接 `_TurnOutcome.finished(response)`，
   reason 只进 `logger.warning`（openai_loop.py:500-502、:550-552、anthropic_loop.py:152-156）。

本批口径（终止原因的**唯一可见通道是正文**，正文同时是落库面）：
- 环侧终止仍交 `gate_terminate`（既有档钉它）并补交恰好一个 `done`；
- 管道侧接住 `gate_terminate`，把原因并进正文（直播与落库同源），空正文时也不会是空气泡；
- 主出口那条 `reasoning: 已停止继续尝试：…` 撤除——同一事实不留两份可见面
  （教义第 6 条），思考面板那份是瞬时的、正文那份才持久；
- 判据不钉文案措辞，钉"门控给出的 reason 原文出现在正文里"。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline
from neurova.agent.gates import StopAction, StopDecision
from neurova.agent.loops.anthropic_loop import AnthropicLoop
from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.llm_client import LLMResponse

REASON = "累计 token 达到预算上限 100000"
GATE = "token_budget"
# 事故里停在半截的那句正文（结尾就是冒号）
HALF_REPLY = "命令被分段审批拦截了。我改用单条命令重试："


def run(coro):
    return asyncio.run(coro)


class TerminatingGate:
    """必开火的观测门：任何一轮都判 TERMINATE，reason 用可控文本。

    构造走 `StopDecision(action=…)` 的实装形态——本仓**没有** `StopDecision.terminate`
    这个工厂方法，写了会被 `GateRunner` 的故障隔离（门控异常＝BYPASS）静默吞掉，
    探针门就成了恒不开火的假装置（`test_tool_loop_iteration_slice_b.py:115` 正是这一
    形态，已另登台账）。
    """

    name = "probe_budget"
    priority = 1

    def check(self, ctx):
        return StopDecision(action=StopAction.TERMINATE, reason=REASON, gate_name=GATE)


def makePipeline(loop):
    """绕过 __init__ 的重依赖，构造最小可用 pipeline（与既有 retry 事件档同形）。"""
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline._agent = MagicMock()
    pipeline._agent._tool_messages_list = []
    pipeline._agent.loop = loop
    return pipeline


def makeLoopStream(events):
    async def gen():
        for e in events:
            yield e

    loop = MagicMock()

    async def predict_step(**kwargs):
        return gen()

    loop.predict_step = AsyncMock(side_effect=predict_step)
    return loop


class TestPipelinePutsTerminationCauseInBody:
    def _drive(self, events, metadata=None):
        pipeline = makePipeline(loop=makeLoopStream(events))
        ctx = ChatContext(user_input="q", stream=True, metadata=metadata or {})
        collected = []
        ctx.event_emitter = lambda t, d: collected.append((t, d))
        reply = run(pipeline._call_loop_stream(ctx, tools_for_llm=None))
        return reply, collected

    def testReasonReachesPersistedReply(self):
        """事故本体：终止原因必须出现在落库正文里，而不是只进日志。"""
        reply, _ = self._drive([
            {"type": "content", "data": HALF_REPLY},
            {"type": "gate_terminate", "reason": REASON, "gate": GATE},
            {"type": "done", "reply": HALF_REPLY, "finish_reason": ""},
        ])
        assert REASON in reply, f"正文停在半截且没交代为什么：{reply!r}"
        assert reply.startswith(HALF_REPLY), f"已有的半截正文不得被改写：{reply!r}"

    def testReasonReachesLiveStream(self):
        """直播面同样要收到（前端气泡与落库同源，不是只有事后翻库才看得见）。"""
        _reply, collected = self._drive([
            {"type": "content", "data": HALF_REPLY},
            {"type": "gate_terminate", "reason": REASON, "gate": GATE},
            {"type": "done", "reply": HALF_REPLY, "finish_reason": ""},
        ])
        assert any(t == "content" and REASON in str(d) for t, d in collected), collected

    def testNotGatedByEmitStatusEvents(self):
        """正文并入不受 `emit_status_events` 门控——那是状态事件（倒计时）的门，
        正文是持久面，蜂群子 Agent 的纯文本流同样不该看到无解释的半截话。"""
        reply, _ = self._drive(
            [
                {"type": "content", "data": HALF_REPLY},
                {"type": "gate_terminate", "reason": REASON, "gate": GATE},
                {"type": "done", "reply": HALF_REPLY, "finish_reason": ""},
            ],
            metadata={},
        )
        assert REASON in reply, reply

    def testEmptyBodyStillNotAirBubble(self):
        """正文为空时并入原因即非空气泡（与 `_LENGTH_EMPTY_NOTICE` 杜绝空气泡同律）。"""
        reply, _ = self._drive([
            {"type": "gate_terminate", "reason": REASON, "gate": GATE},
            {"type": "done", "reply": "", "finish_reason": ""},
        ])
        assert REASON in reply and reply.strip(), repr(reply)

    def testReasonAppearsOnceOnly(self):
        """同一事实一份可见面：正文里原因只出现一次（改一次并一次会重复拼接）。"""
        reply, _ = self._drive([
            {"type": "content", "data": HALF_REPLY},
            {"type": "gate_terminate", "reason": REASON, "gate": GATE},
            {"type": "done", "reply": HALF_REPLY, "finish_reason": ""},
        ])
        assert reply.count(REASON) == 1, reply

    def testNormalStopAddsNothing(self):
        """反向格（改前就该绿）：正常收口的回合不得被追加任何终止说明。"""
        reply, _ = self._drive([
            {"type": "content", "data": "这是完整回复。"},
            {"type": "done", "reply": "这是完整回复。", "finish_reason": "stop"},
        ])
        assert reply == "这是完整回复。", repr(reply)


class _StreamClient:
    """流式假客户端：第一轮产工具调用，随后不再被请求（终止即整条流结束）。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []

    async def chat_stream(self, messages, **kwargs):
        self.calls.append(dict(kwargs))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk


def toolCallChunks(callId="call_1", name="probe_read"):
    return [
        LLMResponse(tool_calls=[{
            "index": 0, "id": callId, "type": "function",
            "function": {"name": name, "arguments": "{}"},
        }], finish_reason="tool_calls"),
    ]


def makeOpenAiLoop(client):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.tool_router = SimpleNamespace(
        execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
    )
    loop = OpenAILoop(agent)
    loop.llm_client = client
    loop.agent.llm_client = client
    loop.registerGate(TerminatingGate())
    return loop


def makeAnthropicLoop(client):
    agent = MagicMock()
    agent._tool_messages_list = []
    agent.skill_registry = None
    agent.config.name = "gate-visibility-probe"
    agent.config.agent_id = "gate-visibility-probe-id"
    agent.config.llm_model = "claude-3-5-sonnet"
    loop = AnthropicLoop(agent)
    loop.llm_client = client
    loop.agent.llm_client = client
    loop.registerGate(TerminatingGate())
    return loop


def collect(gen_factory):
    async def go():
        gen = gen_factory()
        if not hasattr(gen, "__aiter__"):
            gen = await gen
        return [e async for e in gen]

    return run(go())


class TestToolRoundTerminationStillEmitsDone:
    """工具轮被门控掐断时，整条流仍必须恰好一个 done——否则管道侧所有收尾判据落空。"""

    def testOpenAiToolRoundTerminateEmitsOneDone(self):
        client = _StreamClient([toolCallChunks()])
        loop = makeOpenAiLoop(client)
        events = collect(lambda: loop._predict_stream(
            {"messages": [{"role": "user", "content": "读一下"}], "stream": True}
        ))
        gateEvents = [e for e in events if e.get("type") == "gate_terminate"]
        assert len(gateEvents) == 1, gateEvents
        assert gateEvents[0].get("reason") == REASON, gateEvents[0]
        dones = [e for e in events if e.get("type") == "done"]
        assert len(dones) == 1, f"工具轮终止那条 return 不发 done（契约「恰好一个」破功）：{events[-2:]}"

    def testAnthropicToolRoundTerminateEmitsOneDone(self):
        client = _StreamClient([toolCallChunks()])
        loop = makeAnthropicLoop(client)
        events = collect(lambda: loop.predict_step(
            [{"role": "user", "content": "读一下"}], tools=None, stream=True
        ))
        gateEvents = [e for e in events if e.get("type") == "gate_terminate"]
        assert len(gateEvents) == 1 and gateEvents[0]["reason"] == REASON, gateEvents
        dones = [e for e in events if e.get("type") == "done"]
        assert len(dones) == 1, f"Anthropic 环同形缺口：{[e.get('type') for e in events]}"


class TestMainExitTerminationHasSingleVisibleChannel:
    def testCauseAppearsOnceInBodyEvenIfLoopAlsoTalks(self):
        """并正文要幂等：即使环侧仍发着旧文案，正文里原因也只有一份。"""

        async def gen():
            yield {"type": "content", "data": "我再试一次。"}
            yield {"type": "gate_terminate", "reason": REASON, "gate": GATE}
            yield {"type": "reasoning", "data": f"已停止继续尝试：{REASON}"}
            yield {"type": "done", "reply": "我再试一次。", "finish_reason": ""}

        loop = MagicMock()

        async def predict_step(**kwargs):
            return gen()

        loop.predict_step = AsyncMock(side_effect=predict_step)
        pipeline = makePipeline(loop=loop)
        ctx = ChatContext(user_input="q", stream=True, metadata={})
        collected = []
        ctx.event_emitter = lambda t, d: collected.append((t, d))
        reply = run(pipeline._call_loop_stream(ctx, tools_for_llm=None))
        assert REASON in reply, reply
        assert reply.count(REASON) == 1, f"正文里原因重复：{reply!r}"

    def testRetiredThinkingChannelNoticeIsGoneFromBothLoops(self):
        """退役守卫：终止原因的可见面只剩正文一条。

        主出口终止那条路上，环侧原来另发一条 `reasoning: 已停止继续尝试：…`——与管道
        并入正文的那份是同一事实的两个可见面，而思考面板那份关页即失、不持久。
        这条路要真的开火需要"目标 + 目标校验"同时在场（`evaluateLoopExit` 无目标即
        直接 done），夹具喂不出来，故钉代码形态：两条环的源文件不得再出现那句文案。
        """
        import pathlib

        repoRoot = pathlib.Path(__file__).resolve().parents[3]
        banned = ("已停止继续尝试", "已停止工具循环")
        offenders = []
        for name in ("openai_loop.py", "anthropic_loop.py"):
            src = (repoRoot / "neurova" / "agent" / "loops" / name).read_text(
                encoding="utf-8", errors="replace"
            )
            # 路标口径：注释行一律算路标（本批改完留下的"原来此处另有…"说明必然
            # 含该串），要钉的是**代码行**里不再产出这两句终止文案
            codeLines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
            hit = [b for b in banned if any(b in ln for ln in codeLines)]
            if hit:
                offenders.append((name, hit))
        assert not offenders, f"终止原因又长出第二份可见面（应只在 gates.py 单源）：{offenders}"

    def testGateTerminateEventStillProduced(self):
        """撤的是文案，不是事件：既有档钉的 `gate_terminate` 必须照发。"""
        client = _StreamClient([toolCallChunks()])
        loop = makeOpenAiLoop(client)
        events = collect(lambda: loop._predict_stream(
            {"messages": [{"role": "user", "content": "读一下"}], "stream": True}
        ))
        gateEvents = [e for e in events if e.get("type") == "gate_terminate"]
        assert len(gateEvents) == 1, gateEvents
        assert gateEvents[0].get("reason") == REASON, gateEvents[0]


class TestStagnationTerminationIsAlsoVisible:
    """活体补上来的一格：停滞判定（连续重复响应/调用）终止时同样只发 reasoning、
    不发 done ⇒ 门控那三支修绿了，落库正文照旧没交代为什么停。
    （同一根因的第五个命中点，由真 `/api/v1/chat/stream` 活体抓到，不是推出来的。）"""

    def testStagnationTerminateEmitsGateTerminateAndOneDone(self):
        # 本批新符号按**格内局部 import**取：写成模块级会让 A/B 的基线侧整档
        # ImportError——档没跑起来就抽不出条目，"仅基线红"那 12 格交付证据会静默消失
        from neurova.agent.gates import STAGNATION_GATE, STAGNATION_REASON
        # 与活体同形：工具参数逐轮不同（顶掉 DoomLoopGate 的重复签名判据），
        # 正文近似重复（落到停滞判定）。两轮同签名会让死循环门抢先开火，
        # 这一格就测不到停滞那条路（实测踩过一次）。
        def roundChunks(n):
            return [
                LLMResponse(content=f"第{n}步已执行，继续下一步。"),
                LLMResponse(tool_calls=[{
                    "index": 0, "id": f"c{n}", "type": "function",
                    "function": {"name": "probe_read", "arguments": json.dumps({"round": n})},
                }], finish_reason="tool_calls"),
            ]

        client = _StreamClient([roundChunks(n) for n in range(1, 7)])
        agent = MagicMock()
        agent._tool_messages_list = []
        agent.skill_registry = None
        agent.tool_router = SimpleNamespace(
            execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
        )
        loop = OpenAILoop(agent)
        loop.llm_client = client
        loop.agent.llm_client = client
        events = collect(lambda: loop._predict_stream(
            {"messages": [{"role": "user", "content": "列目录"}], "stream": True}
        ))
        terminated = [e for e in events if e.get("type") == "gate_terminate"]
        assert terminated, f"停滞终止没有把成因交给管道：{[e.get('type') for e in events]}"
        # 成因引用 `gates` 那一份单源常量，不在本档另抄一遍措辞
        assert terminated[0].get("reason") == STAGNATION_REASON, terminated[0]
        assert terminated[0].get("gate") == STAGNATION_GATE, terminated[0]
        dones = [e for e in events if e.get("type") == "done"]
        assert len(dones) == 1, f"停滞终止那条 return 也没交 done：{[e.get('type') for e in events]}"


class TestNonStreamPathsCarryCause:
    def testOpenAiNormalToolRoundTerminateNamesCause(self):
        client = SimpleNamespace(
            config=SimpleNamespace(max_tokens=4096),
            chat=AsyncMock(return_value=LLMResponse(
                content=HALF_REPLY,
                tool_calls=[{
                    "index": 0, "id": "c1", "type": "function",
                    "function": {"name": "probe_read", "arguments": "{}"},
                }],
                finish_reason="tool_calls",
            )),
        )
        agent = MagicMock()
        agent._tool_messages_list = []
        agent.skill_registry = None
        agent.tool_router = SimpleNamespace(
            execute=lambda **kw: SimpleNamespace(success=True, result={"ok": 1}, error=None)
        )
        loop = OpenAILoop(agent)
        loop.llm_client = client
        loop.agent.llm_client = client
        loop.registerGate(TerminatingGate())
        response = run(loop.predict_normal(
            {"messages": [{"role": "user", "content": "读一下"}], "stream": False}
        ))
        assert REASON in (response.content or ""), (
            f"非流式终止只进日志、正文停在半截：{response.content!r}"
        )
