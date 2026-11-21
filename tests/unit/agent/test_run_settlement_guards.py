# -*- coding: utf-8 -*-
"""run 自动结算护栏判据（A5 · 追平 T3 Code 计划批二）。

只钉**纯逻辑**面：九重护栏一票否决（按 ``ALL_GUARDS`` 固定顺序取首个命中）、
idle 阈值边界、``readSettleSettings`` 解析回落、``sweep`` 三桶结果与回调异常隔离。
swarm/调度器接线不属本文件域（由主会话统一接线）。

红绿判据出处：docs/04-plans/2026-11-21-reference-ac-catchup-implementation-plan.md A5 节。
"""
from __future__ import annotations

import pytest

from neurova.agent.run_settlement import (
    ALL_GUARDS,
    G_ACTIVE_RUN,
    G_BACKGROUND_WORK,
    G_EXPLICIT_OVERRIDE,
    G_GRACE_PERIOD,
    G_PENDING_APPROVAL,
    G_PINNED,
    G_QUEUED_TURN,
    G_SNOOZED,
    SETTLE_ENV_ENABLED,
    SETTLE_ENV_IDLE_DAYS,
    SETTLE_IDLE_DAYS_DEFAULT,
    SettlementCandidate,
    evaluateSettlement,
    readSettleSettings,
    sweep,
)

DAY = 86400.0


def _candidate(subagent_id="sub-1", *, status="completed", last_activity_at=0.0, guards=None):
    """真实 dataclass 组装候选（禁止 MagicMock 充当业务对象）。"""
    return SettlementCandidate(
        subagent_id=subagent_id,
        status=status,
        last_activity_at=last_activity_at,
        guards=dict(guards or {}),
    )


class TestGuardVetoes:
    """九重护栏逐条命中即拒；护栏键与固定顺序是契约的一部分。"""

    def test_allGuardsCompositionIsNineAndOrderIsFixed(self):
        assert ALL_GUARDS == (
            G_ACTIVE_RUN,
            G_PENDING_APPROVAL,
            G_PINNED,
            G_EXPLICIT_OVERRIDE,
            G_QUEUED_TURN,
            G_SNOOZED,
            G_BACKGROUND_WORK,
            G_GRACE_PERIOD,
            "already_settled",
        )
        assert len(ALL_GUARDS) == 9

    @pytest.mark.parametrize("guard_key", ALL_GUARDS)
    def test_eachGuardHitVetoesSettlement(self, guard_key):
        """九类护栏逐条：命中任一即 (False, 该护栏键)，闲置再久也不结算。"""
        candidate = _candidate(
            status="settled" if guard_key == "already_settled" else "completed",
            guards={guard_key: True},
        )
        should_settle, reason = evaluateSettlement(candidate, now_ts=10 * DAY, idle_days=3.0)
        assert should_settle is False
        assert reason == guard_key

    def test_firstHitWinsInAllGuardsOrder(self):
        guards = {key: True for key in ALL_GUARDS}
        candidate = _candidate(status="completed", guards=guards)
        _, reason = evaluateSettlement(candidate, now_ts=10 * DAY, idle_days=3.0)
        assert reason == G_ACTIVE_RUN  # ALL_GUARDS[0]

    def test_missingGuardKeysDefaultToFalse(self):
        """调用方没收集到的护栏键按 False 处理，不挡结算。"""
        candidate = _candidate(guards=None)
        assert evaluateSettlement(candidate, now_ts=10 * DAY, idle_days=3.0) == (True, "")


class TestAlreadySettled:
    def test_settledStatusShortCircuitsBeforeGuardsAndIdle(self):
        candidate = _candidate(status="settled", guards=None)
        assert evaluateSettlement(candidate, now_ts=10 * DAY, idle_days=3.0) == (
            False,
            "already_settled",
        )

    def test_repeatSweepIsIdempotent(self):
        """重复 sweep 不重复落账：首轮结算后状态翻 settled，次轮只 skip。"""
        calls = []
        candidate = _candidate("sub-1", status="completed", last_activity_at=0.0)

        def settle_fn(subagent_id):
            calls.append(subagent_id)
            candidate.status = "settled"  # 模拟台账落 settled

        first = sweep([candidate], now_ts=10 * DAY, idle_days=3.0, settle_fn=settle_fn)
        second = sweep([candidate], now_ts=11 * DAY, idle_days=3.0, settle_fn=settle_fn)
        assert first["settled"] == ["sub-1"]
        assert second["settled"] == []
        assert second["skipped"] == [["sub-1", "already_settled"]]
        assert calls == ["sub-1"]


class TestIdleThreshold:
    def test_idleExactlyAtThresholdSettles(self):
        candidate = _candidate(last_activity_at=0.0)
        assert evaluateSettlement(candidate, now_ts=3 * DAY, idle_days=3.0) == (True, "")

    def test_idleOneSecondShortDoesNotSettle(self):
        candidate = _candidate(last_activity_at=0.0)
        assert evaluateSettlement(candidate, now_ts=3 * DAY - 1, idle_days=3.0) == (
            False,
            "idle_not_reached",
        )

    def test_fractionalIdleDaysHonoured(self):
        candidate = _candidate(last_activity_at=0.0)
        assert evaluateSettlement(candidate, now_ts=0.5 * DAY, idle_days=0.5) == (True, "")
        assert evaluateSettlement(candidate, now_ts=0.5 * DAY - 1, idle_days=0.5) == (
            False,
            "idle_not_reached",
        )

    def test_negativeIdleNeverSettles(self):
        """last_activity_at 在未来（时钟偏斜）时闲置为负，不得结算。"""
        candidate = _candidate(last_activity_at=100.0)
        assert evaluateSettlement(candidate, now_ts=50.0, idle_days=3.0) == (
            False,
            "idle_not_reached",
        )


class TestReadSettleSettings:
    def test_defaultsToOffWithThreeDays(self):
        assert readSettleSettings({}) == (False, SETTLE_IDLE_DAYS_DEFAULT)
        assert SETTLE_IDLE_DAYS_DEFAULT == 3.0

    def test_readsOsEnvironWhenEnvOmitted(self, monkeypatch):
        monkeypatch.setenv(SETTLE_ENV_ENABLED, "true")
        monkeypatch.setenv(SETTLE_ENV_IDLE_DAYS, "5")
        assert readSettleSettings() == (True, 5.0)
        monkeypatch.delenv(SETTLE_ENV_ENABLED, raising=False)
        monkeypatch.delenv(SETTLE_ENV_IDLE_DAYS, raising=False)
        assert readSettleSettings() == (False, 3.0)

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", "on"])
    def test_enabledTruthyValues(self, raw):
        assert readSettleSettings({SETTLE_ENV_ENABLED: raw})[0] is True

    @pytest.mark.parametrize("raw", ["0", "false", "OFF", "no", "", "maybe"])
    def test_enabledFalsyOrInvalidStaysOff(self, raw):
        assert readSettleSettings({SETTLE_ENV_ENABLED: raw})[0] is False

    @pytest.mark.parametrize(
        "raw,expected", [("7.5", 7.5), ("2", 2.0), ("0.25", 0.25), (" 4 ", 4.0)]
    )
    def test_idleDaysValidParsing(self, raw, expected):
        assert readSettleSettings({SETTLE_ENV_IDLE_DAYS: raw}) == (False, expected)

    @pytest.mark.parametrize("raw", ["abc", "", "-1", "0", "nan", "inf"])
    def test_idleDaysInvalidFallsBackToDefault(self, raw):
        """非法（含非正数/非有限值）一律回落 3.0；本模块不打印，记日志由调用方负责。"""
        assert readSettleSettings({SETTLE_ENV_IDLE_DAYS: raw})[1] == SETTLE_IDLE_DAYS_DEFAULT


class TestSweep:
    def test_mixedCandidatesLandInThreeBuckets(self):
        settleable = _candidate("sub-ok", last_activity_at=0.0)
        guarded = _candidate("sub-guard", guards={G_PENDING_APPROVAL: True})
        fresh = _candidate("sub-fresh", last_activity_at=9 * DAY)  # 仅闲置 1 天
        already = _candidate("sub-done", status="settled")
        boom = _candidate("sub-boom", last_activity_at=0.0)
        after_boom = _candidate("sub-after", last_activity_at=0.0)
        calls = []

        def settle_fn(subagent_id):
            calls.append(subagent_id)
            if subagent_id == "sub-boom":
                raise RuntimeError("terminal close failed")

        result = sweep(
            [settleable, guarded, fresh, already, boom, after_boom],
            now_ts=10 * DAY,
            idle_days=3.0,
            settle_fn=settle_fn,
        )
        assert result["settled"] == ["sub-ok", "sub-after"]  # 回调异常不中断其余
        assert result["skipped"] == [
            ["sub-guard", G_PENDING_APPROVAL],
            ["sub-fresh", "idle_not_reached"],
            ["sub-done", "already_settled"],
        ]
        assert len(result["failed"]) == 1
        assert result["failed"][0][0] == "sub-boom"
        assert "terminal close failed" in result["failed"][0][1]
        assert calls == ["sub-ok", "sub-boom", "sub-after"]  # 只对通过者调用

    def test_emptyCandidatesYieldEmptyBuckets(self):
        calls = []
        result = sweep([], now_ts=10 * DAY, idle_days=3.0, settle_fn=calls.append)
        assert result == {"settled": [], "skipped": [], "failed": []}
        assert calls == []

    def test_resultCarriesExactlyThreeBuckets(self):
        result = sweep([_candidate()], now_ts=10 * DAY, idle_days=3.0, settle_fn=lambda sid: None)
        assert set(result.keys()) == {"settled", "skipped", "failed"}
