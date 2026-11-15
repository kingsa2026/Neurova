# -*- coding: utf-8 -*-
"""P1（ZCode agent-loop 对照 #1/#2）：轮次相位状态机＋提醒先落盘后进历史。

- 相位机：静态迁移表、非法迁移当场抛 `TurnPhaseError`、同相位幂等推进、
  错误路径收口不顶掉真因；
- 接线：真实 `OpenAILoop.predict_normal` 驱动一轮（模型替身），相位沿
  PROCESSING_INPUT → AWAITING → STREAMING → COMPLETING 推进；
- 落盘纪律：steer 插话/邮箱回灌在并入请求历史**之前**经
  `persistModelVisibleAnnouncement` 落会话盘。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.agent.loops.turn_phase import (
    TurnPhase,
    TurnPhaseError,
    TurnPhaseMachine,
    canTransitionTo,
    phaseAdvance,
    phaseAdvanceIfChanged,
    phaseMarkError,
    isTerminalPhase,
)
from neurova.llm_client import LLMResponse


class TestTurnPhaseMachine:
    def test_happy_path_transitions(self):
        machine = TurnPhaseMachine()
        machine.transition(TurnPhase.PROCESSING_INPUT)
        machine.transition(TurnPhase.AWAITING_MODEL_RESPONSE)
        machine.transition(TurnPhase.STREAMING)
        machine.transition(TurnPhase.SCHEDULING_TOOLS)
        machine.transition(TurnPhase.EXECUTING_TOOLS)
        machine.transition(TurnPhase.AGGREGATING_RESULTS)
        machine.transition(TurnPhase.AWAITING_MODEL_RESPONSE)
        machine.transition(TurnPhase.COMPLETING)
        assert machine.phase == TurnPhase.COMPLETING
        assert machine.isComplete()
        assert machine.snapshot()["transitions"] == 8

    def test_illegal_transition_raises(self):
        machine = TurnPhaseMachine()
        machine.transition(TurnPhase.PROCESSING_INPUT)
        with pytest.raises(TurnPhaseError) as err:
            machine.transition(TurnPhase.EXECUTING_TOOLS)
        assert "processing_input" in str(err.value) and "executing_tools" in str(err.value)

    def test_aggregating_loops_back_to_awaiting(self):
        """工具轮回路：AGGREGATING → AWAITING 是 agent loop 的本体迁移。"""
        machine = TurnPhaseMachine()
        for step in (
            TurnPhase.PROCESSING_INPUT,
            TurnPhase.AWAITING_MODEL_RESPONSE,
            TurnPhase.STREAMING,
            TurnPhase.SCHEDULING_TOOLS,
            TurnPhase.EXECUTING_TOOLS,
            TurnPhase.AGGREGATING_RESULTS,
        ):
            machine.transition(step)
        machine.transition(TurnPhase.AWAITING_MODEL_RESPONSE)
        assert machine.phase == TurnPhase.AWAITING_MODEL_RESPONSE

    def test_transition_if_changed_is_idempotent(self):
        machine = TurnPhaseMachine()
        machine.transition(TurnPhase.PROCESSING_INPUT)
        machine.transition(TurnPhase.AWAITING_MODEL_RESPONSE)
        # 恢复路径就地重入：同相位不构成迁移、也不抛错
        machine.transitionIfChanged(TurnPhase.AWAITING_MODEL_RESPONSE)
        assert machine.snapshot()["transitions"] == 2

    def test_terminal_phases_accept_nothing(self):
        assert isTerminalPhase(TurnPhase.COMPLETING)
        assert isTerminalPhase(TurnPhase.ERROR)
        machine = TurnPhaseMachine()
        machine.transition(TurnPhase.PROCESSING_INPUT)
        machine.transition(TurnPhase.COMPLETING)
        with pytest.raises(TurnPhaseError):
            machine.transition(TurnPhase.AWAITING_MODEL_RESPONSE)

    def test_can_transition_to_static(self):
        assert canTransitionTo(TurnPhase.IDLE, TurnPhase.PROCESSING_INPUT)
        assert not canTransitionTo(TurnPhase.IDLE, TurnPhase.EXECUTING_TOOLS)

    def test_error_mark_is_best_effort(self):
        """错误路径收口：正常推进到 ERROR；终端相位拒绝时不顶掉真因。"""
        state = SimpleNamespace(phaseMachine=TurnPhaseMachine())
        phaseAdvance(state, TurnPhase.PROCESSING_INPUT)
        phaseMarkError(state)
        assert state.phaseMachine.phase == TurnPhase.ERROR

        done = SimpleNamespace(phaseMachine=TurnPhaseMachine())
        phaseAdvance(done, TurnPhase.PROCESSING_INPUT)
        phaseAdvance(done, TurnPhase.COMPLETING)
        phaseMarkError(done)  # 不抛——终端相位拒绝留痕即可
        assert done.phaseMachine.phase == TurnPhase.COMPLETING

    def test_phase_advance_without_machine_is_noop(self):
        state = SimpleNamespace()  # 手工构造、无相位机
        phaseAdvance(state, TurnPhase.PROCESSING_INPUT)  # 不抛即过


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
    )


class TestLoopPhaseWiring:
    @staticmethod
    def _captureState(monkeypatch):
        """截获 predict_step 内部构造的轮次态（相位断言的读取面）。"""
        import neurova.agent.loops.turn_run_state as trs

        created: list = []
        original = trs.TurnRunState.forTurn.__func__

        def spy(cls, **kw):
            state = original(cls, **kw)
            created.append(state)
            return state

        monkeypatch.setattr(trs.TurnRunState, "forTurn", classmethod(spy))
        return created

    def test_normal_turn_reaches_completing(self, monkeypatch):
        """真实 predict_normal 驱动：相位走完 入口→请求→流式→收口 全程。"""
        created = self._captureState(monkeypatch)
        reply = LLMResponse(content="普通回复", finish_reason="stop")

        class OneShotChat:
            config = SimpleNamespace(
                temperature=None, max_tokens=None, top_p=None, frequency_penalty=None,
                model="gpt-4o",
            )

            async def chat(self, messages, **kwargs):
                return reply

        agent = _make_agent()
        agent.llm_client = OneShotChat()
        loop = OpenAILoop(agent)

        async def scenario():
            await loop.predict_step([{"role": "user", "content": "问"}])

        asyncio.run(scenario())

        machine = created[0].phaseMachine
        assert machine.phase == TurnPhase.COMPLETING
        steps = [target for _src, target in machine.history]
        assert steps[0] == TurnPhase.PROCESSING_INPUT
        assert TurnPhase.AWAITING_MODEL_RESPONSE in steps
        assert TurnPhase.STREAMING in steps

    def test_tool_round_loops_through_aggregating(self, monkeypatch):
        """带工具的一轮：相位必须经过 SCHEDULING/EXECUTING/AGGREGATING 回到 AWAITING 再收口。"""
        created = self._captureState(monkeypatch)
        rounds = [
            LLMResponse(
                content="",
                tool_calls=[{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{}"},
                }],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="工具后的回复", finish_reason="stop"),
        ]

        class ScriptedChat:
            config = SimpleNamespace(
                temperature=None, max_tokens=None, top_p=None, frequency_penalty=None,
                model="gpt-4o",
            )

            def __init__(self):
                self.n = 0

            async def chat(self, messages, **kwargs):
                resp = rounds[min(self.n, len(rounds) - 1)]
                self.n += 1
                return resp

        agent = _make_agent()
        agent.llm_client = ScriptedChat()
        loop = OpenAILoop(agent)

        executingPhases: list = []

        async def handle_tool_calls(calls, messages):
            executingPhases.append(created[0].phaseMachine.phase)
            return [
                {"role": "tool", "tool_call_id": c["id"], "content": "结果"}
                for c in calls
            ]

        loop.handle_tool_calls = handle_tool_calls

        async def scenario():
            await loop.predict_step([{"role": "user", "content": "问"}])

        asyncio.run(scenario())

        machine = created[0].phaseMachine
        assert executingPhases == [TurnPhase.EXECUTING_TOOLS]
        steps = [target for _src, target in machine.history]
        assert steps.count(TurnPhase.AGGREGATING_RESULTS) == 1
        assert steps.count(TurnPhase.AWAITING_MODEL_RESPONSE) == 2  # 首轮 + 工具轮后续
        assert machine.phase == TurnPhase.COMPLETING


class TestPersistModelVisibleAnnouncement:
    def test_persists_before_history_with_source(self):
        """插话/邮箱回灌在进请求历史前先落会话盘（metadata.source 标来源）。"""
        from neurova.agent.loops.base import persistModelVisibleAnnouncement

        saved = []

        class FakeMemory:
            def saveUserMessage(self, text, session_id=None, metadata=None, **kw):
                saved.append({"text": text, "session_id": session_id, "metadata": metadata})
                return session_id or "s1"

        agent = SimpleNamespace(memory_agent=FakeMemory(), current_session_id="sess-9")
        ok = persistModelVisibleAnnouncement(agent, "先做 A 再做 B", source="steer_interjection")

        assert ok is True
        assert saved[0]["text"] == "先做 A 再做 B"
        assert saved[0]["session_id"] == "sess-9"
        assert saved[0]["metadata"]["source"] == "steer_interjection"

    def test_persistence_failure_does_not_raise(self):
        from neurova.agent.loops.base import persistModelVisibleAnnouncement

        class BadMemory:
            def saveUserMessage(self, *a, **kw):
                raise RuntimeError("盘坏了")

        agent = SimpleNamespace(memory_agent=BadMemory(), current_session_id="sess-9")
        assert persistModelVisibleAnnouncement(agent, "x", source="steer_interjection") is False

    def test_no_memory_or_session_is_noop(self):
        from neurova.agent.loops.base import persistModelVisibleAnnouncement

        assert persistModelVisibleAnnouncement(SimpleNamespace(), "x", source="s") is False
        agent = SimpleNamespace(memory_agent=None, current_session_id="sess")
        assert persistModelVisibleAnnouncement(agent, "x", source="s") is False
        agent = SimpleNamespace(memory_agent=object(), current_session_id="")
        assert persistModelVisibleAnnouncement(agent, "x", source="s") is False
