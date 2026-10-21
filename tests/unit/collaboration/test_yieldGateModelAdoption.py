# -*- coding: utf-8 -*-
"""A：客户端选型入口换模型是「采纳」，不是漂移；非客户端入口仍判漂移。

事故形态（2026-10-21 `run_18b59bcd7f944345`）：第一轮 429 失败时闸已把 kai 钉在
`DeepSeek-V4-Flash-Vision-Exp`；用户切到 `GLM-5.3-Flash` 重发，被
`model_pin_violation` 一次判挂起；续跑复用原载荷，7 次全撞同一 pin。

边界：
- 控制台 / `v1chat` / `v1chat_stream` 是客户端显式选型 → 模型变化即重设 pin；
- 渠道入口（今天传 `modelName=""`）不参与 pin；将来若传显式模型，仍按漂移判；
- pin 同时是并发槽的归因键：换 pin 后，完成时必须按**本回合实际模型**释放，
  不能按「当前 pin」——否则旧模型的槽要等 600s 租约才回收。
"""

import asyncio

import pytest

from neurova.collaboration.glance_yield_rules import GlanceYieldChecker


def _isolateChecker(monkeypatch) -> GlanceYieldChecker:
    checker = GlanceYieldChecker()
    monkeypatch.setattr(
        "neurova.collaboration.glance_yield_rules._glance_checker_instance",
        checker,
        raising=False,
    )
    return checker


class TestClientSelectedModelSwitch:
    @pytest.mark.asyncio
    async def testAdoptSwitchProceedsAndRepins(self, monkeypatch):
        """pin=old，客户端请求 new 且声明 adopt → 放行，pin 改为 new。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = _isolateChecker(monkeypatch)
        checker.register_agent("agent-switch", "gpt-old")

        outcome = await requestYieldGate(
            agentId="agent-switch",
            modelName="gpt-new",
            sessionId="s-switch",
            userInput="帮我找新闻",
            adoptModelSwitch=True,
        )

        assert outcome.proceeded is True, "客户端换模型被当成漂移拦下"
        assert checker._agent_pins["agent-switch"].model_name == "gpt-new", (
            "放行了却没重设 pin — 下一次同模型回合仍会被旧 pin 拦"
        )

        again = await requestYieldGate(
            agentId="agent-switch",
            modelName="gpt-new",
            sessionId="s-switch",
            userInput="继续",
        )
        assert again.proceeded is True

    @pytest.mark.asyncio
    async def testNonClientEntryStillParksAndCarriesDetails(self, monkeypatch):
        """未声明 adopt（渠道/自动入口的严格形态）仍一次判定即挂起，并带出冲突双方。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = _isolateChecker(monkeypatch)
        checker.register_agent("agent-strict", "gpt-old")

        outcome = await requestYieldGate(
            agentId="agent-strict",
            modelName="gpt-new",
            sessionId="s-strict",
            userInput="你好",
        )

        assert outcome.proceeded is False
        assert outcome.attempts == 1, "不可自愈原因不许白等预算"
        assert outcome.parkReason == "model_pin_violation"
        assert outcome.details == {
            "pinned_model": "gpt-old",
            "requested_model": "gpt-new",
        }, "挂起原因只给一个词，用户不知道钉住的是哪个模型"


class TestEntryPolicySingleSource:
    def testClientEntriesAdoptAndChannelDoesNot(self):
        """入口 → 策略的映射只有一处；空 entry 保守按严格判。"""
        from neurova.core.agent_run_ledger import (
            ENTRY_CHANNEL,
            ENTRY_CONSOLE,
            ENTRY_V1CHAT,
            ENTRY_V1CHAT_STREAM,
            adoptsModelSwitchForEntry,
        )

        for entry in (ENTRY_CONSOLE, ENTRY_V1CHAT, ENTRY_V1CHAT_STREAM):
            assert adoptsModelSwitchForEntry(entry) is True, f"{entry} 是客户端选型入口"
        assert adoptsModelSwitchForEntry(ENTRY_CHANNEL) is False
        assert adoptsModelSwitchForEntry("") is False


class TestParkedPayloadCarriesDrift:
    @pytest.mark.asyncio
    async def testAdmissionDerivesPolicyFromEntryAndStoresDetails(self, monkeypatch):
        """准入实现按 payload.entry 派生策略；挂起时把冲突双方写进续跑载荷。"""
        from neurova.agent.turn_coordinator import YieldGateOutcome
        from neurova.core import agent_run_ledger as ledgerMod

        seen = {}
        captured = {}

        async def fakeGate(**kwargs):
            seen.update(kwargs)
            return YieldGateOutcome(
                proceeded=False,
                attempts=1,
                waitedSeconds=0.0,
                operation="op",
                parkReason="model_pin_violation",
                details={"pinned_model": "gpt-old", "requested_model": "gpt-new"},
            )

        class FakeLedger:
            run_id = "run-fake"

            async def parkTurn(self, reason, payload):
                captured["reason"] = reason
                captured["payload"] = payload
                return True

        monkeypatch.setattr(ledgerMod, "requestYieldGate", fakeGate)

        admission = await ledgerMod.requestTurnAdmission(
            ledger=FakeLedger(),
            agentId="agent-fake",
            modelName="gpt-new",
            sessionId="s-fake",
            userInput="你好",
            payload={"entry": ledgerMod.ENTRY_CHANNEL, "message": "你好"},
        )

        assert admission.allowed is False
        assert seen["adoptModelSwitch"] is False, "渠道入口不应采纳客户端选型"
        assert captured["reason"] == "model_pin_violation"
        assert captured["payload"]["park_details"] == {
            "pinned_model": "gpt-old",
            "requested_model": "gpt-new",
        }
        assert captured["payload"]["message"] == "你好", "写挂起载荷时不能丢原文"

    @pytest.mark.asyncio
    async def testConsoleEntryAsksTheGateToAdopt(self, monkeypatch):
        from neurova.agent.turn_coordinator import YieldGateOutcome
        from neurova.core import agent_run_ledger as ledgerMod

        seen = {}

        async def fakeGate(**kwargs):
            seen.update(kwargs)
            return YieldGateOutcome(
                proceeded=True,
                attempts=1,
                waitedSeconds=0.0,
                operation="op",
                modelName=kwargs["modelName"],
            )

        class FakeLedger:
            run_id = "run-fake"

        monkeypatch.setattr(ledgerMod, "requestYieldGate", fakeGate)

        admission = await ledgerMod.requestTurnAdmission(
            ledger=FakeLedger(),
            agentId="agent-fake",
            modelName="gpt-new",
            sessionId="s-fake",
            userInput="你好",
            payload={"entry": ledgerMod.ENTRY_CONSOLE, "message": "你好"},
        )

        assert admission.allowed is True
        assert seen["adoptModelSwitch"] is True
        assert admission.outcome.modelName == "gpt-new"


class TestOccupancyAttribution:
    def testCompletionReleasesTheModelTheTurnStartedWith(self):
        """换 pin 后完成：按本回合模型释放，不按当前 pin（否则旧槽占满 600s）。"""
        checker = GlanceYieldChecker()
        checker.register_agent("agent-occ", "gpt-old")
        checker.record_operation_start("agent-occ", "op-1")
        assert "agent-occ" in checker._activeOps["gpt-old"]

        checker.register_agent("agent-occ", "gpt-new")
        checker.record_operation_complete(
            "agent-occ", "op-1", True, modelName="gpt-old"
        )

        assert "gpt-old" not in checker._activeOps, (
            "完成时按当前 pin 释放了 gpt-new，gpt-old 的槽会一直占着"
        )
        assert checker._pacing_stats["gpt-old"]["total_ops"] == 1

    def testGateOutcomeKeepsTheRequestedModelForAccounting(self, monkeypatch):
        """闸的结论必须带本回合模型，供完成回调归因。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = GlanceYieldChecker()
        monkeypatch.setattr(
            "neurova.collaboration.glance_yield_rules._glance_checker_instance",
            checker,
            raising=False,
        )

        outcome = asyncio.run(
            requestYieldGate(
                agentId="agent-occ2",
                modelName="gpt-model",
                sessionId="s",
                userInput="hi",
            )
        )
        assert outcome.modelName == "gpt-model"
