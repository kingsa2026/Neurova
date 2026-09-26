# -*- coding: utf-8 -*-
"""G2 目标达成验收链（GoalGate 接线）——先红后绿。

根因（对齐 Issue #267 提案 2026-09-26 §1，逐行核实）：

- **RC-1 出口无求值点**：两条路径都在 `if tool_calls:` / `if pending_tool_calls:`
  块内求值门控，"模型不再调工具"这一主出口一行都不过门 ⇒ 假完成（停手且目标未达成）
  无人拦。加 caller 不改变这一点：缺的是求值点，不是调用方。
- **RC-2 goal 只读不写**：全仓唯一读点是 `getattr(self.agent, "_goal", None)`，
  零写入点、`agent` 上从未初始化该属性（协作红线点名的断点形态）。
- **RC-3 两路 ctx 不对称**：非流式缺 `round_reply` / `round_usage` / `goal`，
  且把 `INTERRUPT_AND_CONTINUE` 直接丢弃——同一条门控意见一条路径执行、一条扔掉。
- **RC-4 门控装配两份定义**：`GateRunner([...])` 在 `__init__` 与 `_ensure_gate_runner`
  各写一遍，加门控必然只加到其中一份。

断言口径：替身只放在**模型边界**（`chat` / `chat_stream` 两个契约方法），
门控、门控装配、验收解析、轮次预算全部走生产代码。
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurova.core import turn_context
from neurova.llm_client import LLMResponse

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION = PROJECT_ROOT / "neurova"
OPENAI_LOOP = PRODUCTION / "agent" / "loops" / "openai_loop.py"
BASE_LOOP = PRODUCTION / "agent" / "loops" / "base.py"


def _readText(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


def _verdict(**overrides) -> str:
    payload = {
        "achieved": True,
        "confidence": 0.9,
        "missing": [],
        "explanation": "目标已完成",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


class ScriptedModel:
    """模型边界替身：非流式产出预设响应，流式产出预设 chunk。

    `chatCalls` 计数是"验收子会话是否真的发起"的唯一判据（D-4 的零增量自证）。
    """

    def __init__(self, replies=None, streams=None, config=None):
        self.config = config or SimpleNamespace(model="gpt-4o", temperature=None)
        self._replies = list(replies or [])
        self._streams = list(streams or [])
        self.chatCalls = 0
        self.streamCalls = 0

    async def chat(self, messages, **kwargs):
        self.chatCalls += 1
        idx = min(self.chatCalls - 1, len(self._replies) - 1)
        return self._replies[idx]

    async def chat_stream(self, messages, **kwargs):
        # 未显式给流式脚本时，按 replies 逐个成块（保持 tool_calls/正文原样，
        # 否则工具轮会被"只留正文"的合成丢掉）。
        rounds = self._streams or [[reply] for reply in (self._replies or [LLMResponse(content="")])]
        idx = min(self.streamCalls, len(rounds) - 1)
        self.streamCalls += 1
        for chunk in rounds[idx]:
            yield chunk


def _makeLoop(replies=None, streams=None):
    llm = ScriptedModel(replies=replies, streams=streams)
    agent = SimpleNamespace(
        llm_client=llm,
        config=SimpleNamespace(name="probe", user_id="u1", agent_id="a1"),
        _tool_messages_list=[],
        skill_registry=None,
        tool_router=None,
        current_session_id="s-goal",
    )
    from neurova.agent.loops.openai_loop import OpenAILoop

    return OpenAILoop(agent), llm


def _textChunks(text: str):
    return [LLMResponse(content=text, finish_reason="stop")]


class SpyGate:
    """记录 ctx 的门控（只读观测，不改变判定）。"""

    name = "spy"
    priority = 99

    def __init__(self):
        self.contexts = []

    def check(self, ctx):
        from neurova.agent.gates import StopDecision

        self.contexts.append(dict(ctx))
        return StopDecision.bypass()


class InterruptGate:
    name = "interrupt_probe"
    priority = 1

    def check(self, ctx):
        from neurova.agent.gates import StopAction, StopDecision

        return StopDecision(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="探针软干预",
            gate_name=self.name,
            continuation_prompt="请换一种做法再试一次。",
        )


# ══════════════════════════════════════════════════════════════
# RC-1 · 出口求值点（本方案的心脏）
# ══════════════════════════════════════════════════════════════


class TestMainExitIsGateGuarded:
    @pytest.mark.asyncio
    async def test_exitWithUnmetGoalContinuesInsteadOfDone_stream(self):
        """有 goal、模型零工具调用直接收尾 → 必须注入续跑提示并再跑一轮，而非直接 done。"""
        loop, llm = _makeLoop(
            replies=[
                LLMResponse(content=_verdict(achieved=False, missing=["第二步"])),
                LLMResponse(content=_verdict(achieved=True)),
            ],
            streams=[_textChunks("我先给一半答案。"), _textChunks("补齐后的完整答案。")],
        )
        turn_context.set_turn_goal({"statement": "把两步都做完"})
        try:
            events = [
                event
                async for event in await loop.predict_step(
                    [{"role": "user", "content": "开始"}], stream=True
                )
            ]
        finally:
            turn_context.clear_turn_state()

        # 出口判定三次机会：首轮(未达成) → 续跑后(达成) ⇒ 2 次判定
        assert llm.chatCalls == 2, f"两次出口判定，实测 {llm.chatCalls}"
        assert llm.streamCalls == 2, f"应注入提示后续跑一轮，实测 stream 轮次 {llm.streamCalls}"
        injected = [
            e for e in events if e.get("type") == "reasoning" and "未完成" in str(e.get("data"))
        ]
        assert injected, f"续跑提示必须对用户可见（reasoning 通道），实测事件 {events}"

    @pytest.mark.asyncio
    async def test_exitWithUnmetGoalContinuesInsteadOfReturn_nonStream(self):
        """非流式路径同一语义（RC-1 命中两条路径）。"""
        loop, llm = _makeLoop(
            replies=[
                LLMResponse(content="我先给一半答案。", finish_reason="stop"),
                LLMResponse(content=_verdict(achieved=False, missing=["第二步"])),
                LLMResponse(content="补齐后的完整答案。", finish_reason="stop"),
                LLMResponse(content=_verdict(achieved=True)),
            ],
        )
        turn_context.set_turn_goal({"statement": "把两步都做完"})
        try:
            response = await loop.predict_step([{"role": "user", "content": "开始"}], stream=False)
        finally:
            turn_context.clear_turn_state()

        # 生成 → 判定(未达成) → 续跑生成 → 判定(达成) ⇒ 4 次调用
        assert llm.chatCalls == 4, f"验收两次 + 生成两次，实测 {llm.chatCalls}"
        assert response.content == "补齐后的完整答案。"

    @pytest.mark.asyncio
    async def test_noGoalSkipsVerificationCall(self):
        """D-4：无 goal 的普通会话，验收子会话调用数必须为 0（成本边界）。"""
        loop, llm = _makeLoop(replies=[LLMResponse(content="直接回答")])
        events = [
            event
            async for event in await loop.predict_step(
                [{"role": "user", "content": "你好"}], stream=True
            )
        ]
        assert llm.chatCalls == 0, "无 goal 时不得发起任何验收调用"
        assert any(e.get("type") == "done" for e in events)

    @pytest.mark.asyncio
    async def test_achievedGoalFinishesImmediately(self):
        """已达成 → 正常收口，不续跑。"""
        loop, llm = _makeLoop(
            replies=[LLMResponse(content=_verdict(achieved=True))],
            streams=[_textChunks("答案。")],
        )
        turn_context.set_turn_goal({"statement": "回答一句话"})
        try:
            events = [
                event
                async for event in await loop.predict_step(
                    [{"role": "user", "content": "开始"}], stream=True
                )
            ]
        finally:
            turn_context.clear_turn_state()
        assert llm.streamCalls == 1
        assert any(e.get("type") == "done" for e in events)

    @pytest.mark.asyncio
    async def test_continuationBudgetIsHardBounded(self):
        """第 max+1 次未达成 → TERMINATE 且 reason 点名预算（不得无限续跑）。"""
        unmet = LLMResponse(content=_verdict(achieved=False, missing=["永远做不到"]))
        loop, llm = _makeLoop(
            replies=[unmet, unmet, unmet, unmet],
            streams=[_textChunks("再来一次。")],
        )
        turn_context.set_turn_goal({"statement": "不可能完成的目标"})
        try:
            events = [
                event
                async for event in await loop.predict_step(
                    [{"role": "user", "content": "开始"}], stream=True
                )
            ]
        finally:
            turn_context.clear_turn_state()

        limits = loop._load_agent_limits()
        maxContinuations = int(limits["goal_max_continuations"])
        assert llm.streamCalls == maxContinuations + 1, (
            f"续跑次数必须硬封在上限内：实测 {llm.streamCalls}，上限 {maxContinuations}"
        )
        stopped = [e for e in events if e.get("type") == "gate_terminate"]
        assert stopped, f"预算耗尽必须 TERMINATE，实测事件 {events}"
        assert "预算耗尽" in stopped[0]["reason"]

    @pytest.mark.asyncio
    async def test_parseFailureDoesNotBlockExit(self):
        """判据坏掉（解析失败）→ 照常收口 + 发观测，绝不阻断正常回复。"""
        loop, llm = _makeLoop(
            replies=[LLMResponse(content="我觉得还行，没有 JSON")],
            streams=[_textChunks("正常回复。")],
        )
        turn_context.set_turn_goal({"statement": "回答一句话"})
        try:
            events = [
                event
                async for event in await loop.predict_step(
                    [{"role": "user", "content": "开始"}], stream=True
                )
            ]
            verdict = turn_context.get_turn_goal_verdict()
        finally:
            turn_context.clear_turn_state()

        assert llm.streamCalls == 1, "判据坏掉不得导致续跑"
        assert any(e.get("type") == "done" for e in events)
        assert verdict and verdict.get("parse_ok") is False, "解析失败必须以诚实形态落到观测面"


# ══════════════════════════════════════════════════════════════
# RC-3 · 两条路径 ctx 对称 + 兑现 INTERRUPT_AND_CONTINUE
# ══════════════════════════════════════════════════════════════


class TestPathSymmetry:
    @staticmethod
    def _toolRoundAgent(replies):
        llm = ScriptedModel(replies=replies)
        agent = SimpleNamespace(
            llm_client=llm,
            config=SimpleNamespace(name="probe", user_id="u1", agent_id="a1"),
            _tool_messages_list=[],
            skill_registry=None,
            tool_router=None,
            current_session_id="s-goal",
            _round_usage={"total_tokens": 1234},
        )

        async def _handle(tool_calls, messages):
            return [{"role": "tool", "tool_call_id": "c1", "name": "probe", "content": "ok"}]

        from neurova.agent.loops.openai_loop import OpenAILoop

        loop = OpenAILoop(agent)
        loop.handle_tool_calls = _handle
        return loop, llm

    @pytest.mark.asyncio
    async def test_nonStreamGateCtxCarriesSameKeysAsStream(self):
        """非流式 on_round_end 的 ctx 键集合必须 ⊇ 流式（缺键 = 门控在该路径恒不触发）。"""
        toolCall = LLMResponse(
            content="",
            tool_calls=[{"id": "c1", "function": {"name": "probe", "arguments": "{}"}}],
            finish_reason="tool_calls",
        )
        seen = {}

        # 非流式
        loop, _llm = self._toolRoundAgent([toolCall, LLMResponse(content="完")])
        spy = SpyGate()
        loop.registerGate(spy)
        await loop.predict_step([{"role": "user", "content": "开始"}], stream=False)
        seen["normal"] = spy.contexts[-1]

        # 流式
        loop2, _llm2 = self._toolRoundAgent([toolCall, LLMResponse(content="完")])
        spy2 = SpyGate()
        loop2.registerGate(spy2)
        [
            e
            async for e in await loop2.predict_step(
                [{"role": "user", "content": "开始"}], stream=True
            )
        ]
        seen["stream"] = spy2.contexts[-1]

        missing = set(seen["stream"]) - set(seen["normal"])
        assert not missing, (
            f"非流式 ctx 缺键 {missing}——这些门控在非流式路径上恒不可触发；"
            f"非流式={sorted(seen['normal'])} 流式={sorted(seen['stream'])}"
        )
        for key in ("round_reply", "round_usage", "goal", "round_signature", "tool_rounds"):
            assert key in seen["normal"], f"ctx 缺 {key}"

    @pytest.mark.asyncio
    async def test_nonStreamHonorsInterruptAndContinue(self):
        """非流式收到 INTERRUPT_AND_CONTINUE 时必须注入 continuation_prompt 后继续。"""
        toolCall = LLMResponse(
            content="",
            tool_calls=[{"id": "c1", "function": {"name": "probe", "arguments": "{}"}}],
            finish_reason="tool_calls",
        )
        loop, llm = self._toolRoundAgent([toolCall, LLMResponse(content="完")])
        loop.registerGate(InterruptGate())

        sent = []
        original = llm.chat

        async def _capture(messages, **kwargs):
            sent.append([dict(m) for m in messages])
            return await original(messages, **kwargs)

        llm.chat = _capture
        await loop.predict_step([{"role": "user", "content": "开始"}], stream=False)

        assert len(sent) >= 2, "软干预后必须续跑"
        prompts = [m.get("content") for m in sent[1] if m.get("role") == "user"]
        assert "请换一种做法再试一次。" in prompts, (
            f"非流式路径丢弃了 continuation_prompt（同一条门控意见一条路执行一条路扔掉）：{prompts}"
        )


# ══════════════════════════════════════════════════════════════
# RC-4 · 装配单源
# ══════════════════════════════════════════════════════════════


class TestGateAssemblyIsSingleSource:
    def test_gateRunnerIsConstructedOnce(self):
        """`GateRunner([...])` 只允许在装配单点 `_buildGateRunner` 出现。"""
        src = _readText(OPENAI_LOOP)
        owners = [
            line.strip()
            for line in src.splitlines()
            if "GateRunner([" in line
        ]
        assert len(owners) == 1, (
            f"`GateRunner([` 在 openai_loop.py 出现多次：门控清单有两份定义，"
            f"加门控必然只加到其中一份（修复教义第 6 条）：{owners}"
        )

    def test_gateAssemblyIsSharedByInitAndLazyPath(self):
        """三条装配入口（__init__ / 懒初始化 / 每轮重建）必须同调一个装配函数。

        轮次态归属（Issue #268）要求门控执行器每轮一份，故入口不止 __init__、
        懒初始化两处；判据钉的是"装配实现只有一处"，而不是"调用点只有一处"。
        """
        src = _readText(OPENAI_LOOP)
        assert "_buildGateRunner" in src, "门控装配未收口到单一函数"
        assert "def _buildGateRunner" in src, "装配单点函数未定义"
        callers = [
            line.strip()
            for line in src.splitlines()
            if re.search(r"self\._buildGateRunner\(\)", line)
        ]
        assert len(callers) >= 3, (
            f"装配入口应含 __init__ / 懒初始化 / 每轮重建三处，实测 {callers}"
        )


# ══════════════════════════════════════════════════════════════
# RC-2 · goal 的写入面与读取面（闭合回路）
# ══════════════════════════════════════════════════════════════


class TestGoalHasWriteAndReadSites:
    def test_noNakedGoalAttributeRead(self):
        src = _readText(OPENAI_LOOP)
        assert not re.search(r"\b_goal\b", src), (
            "openai_loop 仍在裸读 `_goal`（全仓零写入点的死属性）——goal 必须走单一解析点"
        )

    def test_goalIsWrittenAndReadAcrossFiles(self):
        """写入点与读取点必须分处不同文件（同一文件内自循环不算接线）。"""
        writers = sorted(
            str(path.relative_to(PRODUCTION))
            for path in PRODUCTION.rglob("*.py")
            if "set_turn_goal(" in _readText(path)
        )
        readers = sorted(
            str(path.relative_to(PRODUCTION))
            for path in PRODUCTION.rglob("*.py")
            if "get_turn_goal(" in _readText(path)
        )
        assert writers, "goal 没有任何写入点：GoalGate 只能拿到空 goal"
        assert readers, "goal 没有任何读取点：写入是断点"
        assert set(readers) - set(writers), (
            "读取点全落在写入它的那个文件里（自循环，不是跨层接线）："
            f"写入 {writers} / 读取 {readers}"
        )


# ══════════════════════════════════════════════════════════════
# 行为绿灯 · 验收执行器纪律
# ══════════════════════════════════════════════════════════════


class TestVerifierDiscipline:
    @pytest.mark.asyncio
    async def test_verificationRequestCarriesNoTools(self):
        """验收调用不携带 tools——判"是否完成"不能产生副作用（判据自我污染）。"""
        from neurova.agent.goal_verifier import verifyGoalCompletion
        from neurova.agent.loop_goal import normalizeGoal

        captured = {}

        def syncChat(messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return SimpleNamespace(content=_verdict(), model="probe-model")

        verdict = await verifyGoalCompletion(
            syncChat, normalizeGoal({"statement": "做一件事"}), "证据正文"
        )
        assert verdict["parse_ok"] is True and verdict["achieved"] is True
        assert captured["kwargs"].get("tools") is None

    @pytest.mark.asyncio
    async def test_verificationAcceptsAsyncChannel(self):
        """llmChat 为 async（生产=agent.llm_client.chat）时必须被 await，
        而不是把 coroutine 当响应体解析（"coroutine was never awaited" 形态）。"""
        from neurova.agent.goal_verifier import verifyGoalCompletion
        from neurova.agent.loop_goal import normalizeGoal

        async def asyncChat(messages, **kwargs):
            return LLMResponse(content=_verdict(achieved=False, missing=["x"]))

        verdict = await verifyGoalCompletion(
            asyncChat, normalizeGoal({"statement": "做一件事"}), "证据"
        )
        assert verdict["parse_ok"] is True, "async 通道未被正确 await"
        assert verdict["achieved"] is False
        assert verdict["missing"] == ["x"]

    @pytest.mark.asyncio
    async def test_verdictIsCostAttributedThroughLlmClient(self):
        """验收调用必须走 agent.llm_client（自动过 @track_llm_call 与成本上下文），
        不得自建第二个客户端。"""
        from neurova.agent.goal_verifier import verifyGoalCompletion

        class Channel:
            def __init__(self):
                self.calls = []

            async def chat(self, messages, **kwargs):
                self.calls.append(kwargs)
                return LLMResponse(content=_verdict())

        channel = Channel()
        from neurova.agent.loop_goal import normalizeGoal

        await verifyGoalCompletion(channel.chat, normalizeGoal({"statement": "s"}), "ev")
        assert len(channel.calls) == 1, "验收调用必须经调用方注入的 llm_client 通道"


class TestGoalThresholdSingleSource:
    def test_goalGateConstructionBindsItsOwnConfigKey(self):
        """阈值可达性必须为 single_source（不得与轮次预算共享同一尺度来源）。"""
        import sys

        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.ci import tool_loop_deadline_ledger as ledger

        rows = {str(row["symbol"]): row for row in ledger.facts()}
        assert "GoalGate" in rows, "GoalGate 未登记进死线台账——阈值可达性无从机器复算"
        assert rows["GoalGate"]["threshold_axis"] == ledger.THRESHOLD_SINGLE_SOURCE, (
            f"GoalGate 阈值可达性为 {rows['GoalGate']['threshold_axis']}，"
            f"原因：{rows['GoalGate']['threshold_detail'].get('reason')}"
        )
        assert rows["GoalGate"]["threshold_detail"]["config_key"] == "goal_max_continuations"

    def test_ledgerReconcilesForGoalEntries(self):
        import sys

        sys.path.insert(0, str(PROJECT_ROOT))
        from scripts.ci import tool_loop_deadline_ledger as ledger

        problems = ledger.reconcile()
        for key, items in problems.items():
            assert not items, f"台账对账失败 [{key}]：{items}"


class TestBudgetIsNotSilentlyUnbounded:
    def test_agentLimitsExposeGoalContinuationBudget(self, monkeypatch, tmp_path):
        from neurova.security import agent_limits_settings as limits

        monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(tmp_path / "limits.json"))
        effective = limits.get_effective_limits()
        assert effective["goal_max_continuations"] == 2, "默认上限必须是 2（成本可预期）"
        assert limits.save_agent_limits({"goal_max_continuations": 5})
        assert limits.get_effective_limits()["goal_max_continuations"] == 5
        assert limits.save_agent_limits({"goal_max_continuations": 9999})
        assert limits.get_effective_limits()["goal_max_continuations"] == 5, (
            "越界值必须被夹紧到合法区间，不得静默放行无限续跑"
        )

# ══════════════════════════════════════════════════════════════
# 放大视角 · 同一根因的另一处命中点：受限子会话的通道形态
# ══════════════════════════════════════════════════════════════


class TestSubSessionChannelShape:
    """同一个"通道形态未归一"根因的第二处命中点：/review 的生产调用点。

    `run_review` 原实现无条件 `asyncio.to_thread(llm_chat, messages)`，而它的
    **两条生产调用点**注入的都是 Agent 门面的 async `chat`
    （`chat_pipeline` 与 `console` 的 `lambda messages: llm.chat(messages)`）——
    `to_thread` 只会创建协程并立刻返回，从不 await，于是 /review 恒判
    `parse_ok=False`、评审结论永远拿不到。这与验收子会话是同一根因，
    故同批修复、同批钉住。
    """

    @pytest.mark.asyncio
    async def test_asyncFacadeChannelIsAwaited(self):
        from neurova.agent.review import run_review

        class AgentFacade:
            async def chat(self, messages, **kwargs):
                return LLMResponse(
                    content=json.dumps(
                        {"findings": [], "overall_correctness": "correct",
                         "overall_explanation": "ok", "overall_confidence_score": 0.9}
                    )
                )

        facade = AgentFacade()
        result = await run_review(lambda messages: facade.chat(messages), "diff")
        assert result["parse_ok"] is True, (
            "async 门面通道未被 await（/review 生产路径形态），评审结论恒为空"
        )
        assert result["overall_correctness"] == "correct"

    @pytest.mark.asyncio
    async def test_syncClientChannelIsOffloaded(self):
        """同步通道（低层 LLMClient.chat）仍必须能用，且不阻塞事件循环。"""
        from neurova.agent.review import run_review

        def syncChat(messages, **kwargs):
            return SimpleNamespace(
                content=json.dumps({"findings": [], "overall_correctness": "issues_found"}),
                model="sync-model",
            )

        result = await run_review(syncChat, "diff")
        assert result["parse_ok"] is True
        assert result["model"] == "sync-model"

class TestVerificationGoesThroughTheProductionChannel:
    """成本归属：判定调用必须走 `loop.llm_client` 这条生产通道。

    Agent 门面（`AgentLLMClient.chat`）→ 路由（`MultiModelLLMClient.chat`）→
    每次调用经 `usage_accounting.record` 入账，并与正文生成共用同一张路由与账本。
    若判定另起一个客户端，这笔推理就会游离于成本账本之外。
    """

    @pytest.mark.asyncio
    async def test_exitEvaluationCallsTheLoopLlmClient(self):
        loop, llm = _makeLoop(
            replies=[LLMResponse(content=_verdict(achieved=True))],
            streams=[_textChunks("答案。")],
        )
        turn_context.set_turn_goal({"statement": "回答一句话"})
        try:
            [
                event
                async for event in await loop.predict_step(
                    [{"role": "user", "content": "开始"}], stream=True
                )
            ]
        finally:
            turn_context.clear_turn_state()
        assert llm.chatCalls == 1, (
            "判定未经 loop.llm_client 通道（成本账本会漏掉这笔推理）"
        )

    def test_noSecondLlmClientIsConstructed(self):
        """判定链不得自建第二个 LLM 客户端（单源：只有调用方注入的一条通道）。"""
        for rel in ("agent/goal_verifier.py", "agent/sub_session.py", "agent/loop_goal.py"):
            src = _readText(PRODUCTION / rel)
            for banned in ("LLMClient(", "MultiModelLLMClient(", "get_multi_model_client("):
                assert banned not in src, f"{rel} 自建了第二个 LLM 客户端：{banned}"
