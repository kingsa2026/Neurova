# -*- coding: utf-8 -*-
"""模型归因缺失时不许建 pin——否则"接了闸"的第一条生产回合就把自己挂死。

现场形态（前端 `ChatPage.vue:1340` 就是这样的）：用户没选手动模型时
`model` 字段是 `undefined`，回合入口拿到的 `modelName` 是空串。而 Layer 1
`_check_model_pin` 对"首次见到这个 agent"无条件 `register_agent(agent, model)`，
于是 pin 被钉成空串。之后用户选了一个真模型再来——`model_name != pinned_model`
成立 → `MODEL_PIN_VIOLATION`，而这恰是闸里唯一"等也不会自愈"的那类原因，
**第一次判定就挂起**。

结论：默认路径（先自动模型、后手动选一个）会稳定复现"聊两句就被挂起"。
归因不到模型时应**跳过 pin 判据并保持未归因**，等一次真归因到来再钉——
这与上一批"归因不到模型就不占并发槽"（§6-45）是同一条纪律的另一半。
"""
from __future__ import annotations

import pytest

from neurova.collaboration.glance_yield_rules import (
    GlanceYieldChecker,
    YieldReason,
)


@pytest.fixture()
def checker(monkeypatch):
    monkeypatch.setattr(
        "neurova.collaboration.glance_yield_rules._glance_checker_instance",
        GlanceYieldChecker(),
        raising=False,
    )
    from neurova.collaboration import glance_yield_rules as gyr

    return gyr._glance_checker_instance


def testUnattributedTurnRegistersNoPin(checker):
    """空模型名的回合不建立 pin（用公开读面 stats 判，不伸手进私有字典自证）。"""
    decision = checker.check_yield_rules(
        agent_id="agent-auto", model_name="", proposed_operations=["op-1"]
    )
    assert decision.should_yield is False
    assert checker.get_stats()["registered_agents"] == 0, (
        "空模型名把 pin 钉死了——后续任何真模型都会被判成模型漂移"
    )


def testFirstAttributedTurnStillEstablishesThePin(checker):
    """跳过空归因不等于取消归因：第一次带真模型的回合必须钉上，漂移判据才仍然有效。"""
    checker.check_yield_rules(agent_id="agent-x", model_name="", proposed_operations=["op-0"])
    checker.check_yield_rules(agent_id="agent-x", model_name="gpt-real", proposed_operations=["op-1"])
    assert checker.get_stats()["registered_agents"] == 1

    drift = checker.check_yield_rules(
        agent_id="agent-x", model_name="gpt-other", proposed_operations=["op-2"]
    )
    assert drift.should_yield is True and drift.reason == YieldReason.MODEL_PIN_VIOLATION


@pytest.mark.asyncio
async def testAutoThenManualModelDoesNotParkTheTurn(checker, monkeypatch):
    """生产默认序列（先自动、后手动）在闸上必须放行，而不是第一次判定就挂起。"""
    from neurova.agent.turn_coordinator import requestYieldGate

    first = await requestYieldGate(
        agentId="agent-flow", modelName="", sessionId="s-flow", userInput="第一轮"
    )
    assert first.proceeded is True, f"未归因回合被挂起：{first.parkReason}"

    monkeypatch.setenv("NEUROVA_YIELD_MAX_ATTEMPTS", "10")
    second = await requestYieldGate(
        agentId="agent-flow", modelName="gpt-real", sessionId="s-flow", userInput="第二轮"
    )
    assert second.proceeded is True, (
        f"选了真模型的第二轮被判成不可重试原因而挂起：{second.parkReason}"
    )
