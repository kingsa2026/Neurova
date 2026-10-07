# -*- coding: utf-8 -*-
"""P2-8：让位闸必须"接真"——上限生效、不阻塞事件循环、身份与操作标识取真源。

拍板的口径：**最多等 10 次、单次间隔上限 20 秒（总预算 200s），超限直接挂起等人工续跑。**

这批判据的形态：
- 第 1~3 条打在**现有实现**的行为上（不是打在新模块的装配噪声上）：`get_turn_coordinator()`
  今天必然 AttributeError；`glance_yield_check` 在协程里用 `time.sleep` 等待，会把整个事件
  循环一起睡掉；同一装饰器把身份取成 `kwargs.get("agent_id", "unknown")`，真回合里所有 Agent
  会被并进同一个 `"unknown"` 桶，让位判据从此量不到真竞争。
- 第 4~6 条打在新闸的策略上（次数上限、单次上限、超限必须"挂起"而不是谎报放行）。
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.collaboration.glance_yield_rules import (  # noqa: E402
    GlanceYieldChecker,
    get_glance_yield_checker,
    reset_glance_yield_checker,
)


def _isolateChecker(monkeypatch, cooldownSeconds: float) -> GlanceYieldChecker:
    """把进程级单例换成本用例独占的 checker，并给一个可预期的冷却时长。

    为什么要 monkeypatch 常量再走生产入口 `trigger_rate_limit`：直接塞私有字典
    （`_rate_limited_agents[...] = ...`）会让判据只证明"我造的字典"，不证明生产
    触发路径真能让位。
    """
    monkeypatch.setattr(GlanceYieldChecker, "DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS", cooldownSeconds)
    checker = GlanceYieldChecker()
    monkeypatch.setattr(
        "neurova.collaboration.glance_yield_rules._glance_checker_instance", checker, raising=False
    )
    return checker


class TestExistingYieldPathIsNotReal:
    """打在现状上的三条：让位能力今天到底断在哪。"""

    @pytest.mark.asyncio
    async def testGateRunsOnTheRealCheckerAndImaginedEntryIsGone(self, monkeypatch):
        """闸必须跑在真裁决器上；照着不存在的 Agent 接口写的那套入口要一并消失。

        红在现状上的形态：`get_turn_coordinator()` 构造即 `AttributeError:
        'coroutine' object has no attribute 'initialize'`（协程工厂没 await，且
        `GlanceYieldChecker` 全类没有 `initialize()`）。
        """
        import neurova.agent.turn_coordinator as gate

        _isolateChecker(monkeypatch, cooldownSeconds=0.0)
        outcome = await gate.requestYieldGate(
            agentId="agent-real", modelName="gpt-test", sessionId="s1", userInput="你好"
        )
        assert outcome.proceeded is True and outcome.attempts == 1

        checker = await gate.get_glance_yield_checker()
        assert isinstance(checker, GlanceYieldChecker)
        assert checker._agent_pins["agent-real"].model_name == "gpt-test", (
            "pin 没由 Layer 1 建立——闸若自己 register_agent 会把模型漂移判据覆写掉"
        )
        for imagined in ("get_turn_coordinator", "TurnCoordinator", "check_and_execute_turn"):
            assert not hasattr(gate, imagined), (
                f"想象接口 {imagined} 还在——它假定 agent.execute_turn()/agent.id 这些"
                "全仓不存在的契约，留着就是第二份各调各的实现"
            )

    @pytest.mark.asyncio
    async def testWaitingYieldsTheLoopToOtherCoroutines(self, monkeypatch):
        """等让位只能 `await asyncio.sleep`——被摘链的那份装饰器用 `time.sleep`，
        一个 Agent 让位会把整条事件循环睡掉（红灯实测：等待期其它协程走了 0 拍）。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = _isolateChecker(monkeypatch, cooldownSeconds=1.0)
        checker.trigger_rate_limit("agent-loop")

        ticks = {"n": 0}
        seenWhenProceeded = {"n": -1}

        async def ticker():
            for _ in range(40):
                await asyncio.sleep(0.05)
                ticks["n"] += 1

        async def askGate():
            outcome = await requestYieldGate(
                agentId="agent-loop", modelName="gpt-test", sessionId="s-loop", userInput="继续"
            )
            seenWhenProceeded["n"] = ticks["n"]
            return outcome

        _outcome, _ = await asyncio.gather(askGate(), ticker())

        assert seenWhenProceeded["n"] >= 10, (
            f"等了约 1s 让位，期间其它协程只走了 {seenWhenProceeded['n']} 拍——"
            "等待把事件循环整条占住了，全服务其它会话一起卡"
        )

    @pytest.mark.asyncio
    async def testGateKeysStateByRealAgentNotTheUnknownBucket(self, monkeypatch):
        """身份必须取真 Agent。装饰器那份取 `kwargs.get("agent_id", "unknown")`，
        真回合里没有这个关键字参数，所有 Agent 会挤进同一个配额桶（红灯实测
        注册到的是 ['unknown', 'unknown']）。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = _isolateChecker(monkeypatch, cooldownSeconds=0.0)

        for agentId in ("agent-alpha", "agent-beta"):
            outcome = await requestYieldGate(
                agentId=agentId, modelName="gpt-test", sessionId="s-id", userInput="你好"
            )
            assert outcome.proceeded is True

        assert set(checker._agent_pins) == {"agent-alpha", "agent-beta"}, (
            f"pin 桶里是 {sorted(checker._agent_pins)}——身份没落到真 agent_id 上"
        )

    @pytest.mark.asyncio
    async def testDuplicateYieldImplementationIsRetired(self):
        """同一功能只剩一处实现（教义第 7 条）：那份零消费者、time.sleep、unknown 桶的
        装饰器实现必须随本批退役，而不是两份并存各调各的。"""
        import importlib.util

        modulePath = PROJECT_ROOT / "neurova" / "collaboration" / "coordination_decorators.py"
        assert not modulePath.exists(), (
            f"{modulePath} 还在——它与 agent/turn_coordinator 的闸同功能，"
            "两份并行使『到底谁在挡』无从判断"
        )
        assert importlib.util.find_spec("neurova.collaboration.coordination_decorators") is None


class TestYieldWaitPolicy:
    """打在拍板策略上的三条：10 次 / 单次 20s / 超限挂起。"""

    @pytest.mark.asyncio
    async def testGateStopsAtTenAttemptsAndAsksToPark(self, monkeypatch):
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = _isolateChecker(monkeypatch, cooldownSeconds=10 ** 6)
        checker.trigger_rate_limit("agent-cap")
        waited = []

        async def fakeSleep(seconds):
            waited.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fakeSleep)

        outcome = await requestYieldGate(
            agentId="agent-cap", modelName="gpt-test", sessionId="sess-cap", userInput="继续"
        )

        assert outcome.proceeded is False, "冷却还在，闸不该放行"
        assert outcome.attempts == 11, (
            f"判了 {outcome.attempts} 次；口径是首次判定 + 最多 10 次重试后挂起"
        )
        assert outcome.parkReason, "超限必须给出挂起原因，不能静默返回"
        assert len(waited) == 10 and all(w == 20.0 for w in waited), (
            f"实际等待 {waited}——冷却还剩 10^6 秒却必须被削到单次 20s 上限"
        )
        assert checker._stats["total_checks"] == outcome.attempts, (
            "闸自报次数与裁决器计数不一致——说明有一边在空转"
        )

    @pytest.mark.asyncio
    async def testEachWaitIsCappedAndTotalBudgetIsBounded(self, monkeypatch):
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = _isolateChecker(monkeypatch, cooldownSeconds=600.0)
        checker.trigger_rate_limit("agent-capped")
        sleeps = []

        async def fakeSleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fakeSleep)

        outcome = await requestYieldGate(
            agentId="agent-capped", modelName="gpt-test", sessionId="sess-capped", userInput="继续"
        )

        assert sleeps, "一次都没等——上限判据没被走到"
        assert max(sleeps) <= 20.0, f"单次等待 {max(sleeps)}s 越过 20s 上限"
        assert sum(sleeps) <= 200.0, f"累计等待 {sum(sleeps)}s 越过 10×20 的总预算"
        assert outcome.proceeded is False

    @pytest.mark.asyncio
    async def testOperationIdentityIsStableForTheSameTurn(self, monkeypatch):
        """同一回合重试必须落在同一个操作标识上——否则"操作碰撞"永远判不出来。"""
        from neurova.agent.turn_coordinator import turnOperationIdentity

        first = turnOperationIdentity(sessionId="sess-x", userInput="把报告改成中文")
        second = turnOperationIdentity(sessionId="sess-x", userInput="把报告改成中文")
        other = turnOperationIdentity(sessionId="sess-x", userInput="换一份")

        assert first == second, "同回合两次取到的操作标识不一致，碰撞判据恒为假"
        assert first != other, "不同输入却同一个标识，碰撞判据会误伤"

    @pytest.mark.asyncio
    async def testNonSelfHealingReasonParksWithoutBurningTheBudget(self, monkeypatch):
        """模型漂移等多久都不会自愈：一次判定就挂起，不许白等 200 秒。"""
        from neurova.agent.turn_coordinator import requestYieldGate

        checker = _isolateChecker(monkeypatch, cooldownSeconds=0.0)
        checker.register_agent("agent-pin", "gpt-old")
        slept = []

        async def fakeSleep(seconds):
            slept.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fakeSleep)

        outcome = await requestYieldGate(
            agentId="agent-pin", modelName="gpt-new", sessionId="s-pin", userInput="你好"
        )

        assert outcome.proceeded is False and outcome.attempts == 1
        assert outcome.parkReason == "model_pin_violation"
        assert slept == [], f"不可自愈的原因却等了 {slept}——预算白烧，用户白等"

    @pytest.mark.asyncio
    async def testPolicyIsReadPerCallNotBoundAtImport(self, monkeypatch):
        """策略数值必须每次调用读 env——导入期绑死会让换配置变成"改了没生效"。"""
        from neurova.agent.turn_coordinator import yieldWaitPolicy

        monkeypatch.setenv("NEUROVA_YIELD_MAX_ATTEMPTS", "2")
        monkeypatch.setenv("NEUROVA_YIELD_WAIT_CAP_SECONDS", "3")

        policy = yieldWaitPolicy()

        assert (policy.maxAttempts, policy.capSeconds) == (2, 3.0), (
            f"读到 {policy.maxAttempts}/{policy.capSeconds}——env 改了不生效说明它在导入期就被绑住了"
        )
