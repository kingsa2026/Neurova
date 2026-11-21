# -*- coding: utf-8 -*-
"""A5 结算多驱动触发判据（深度批）：时钟 / 显式（admin 端点）/ 终态助推。

红绿判据出处：IDE 接入计划体系深度批 A5 卡（结算多驱动触发）。
只钉驱动接线与九护栏咬合；纯判定逻辑见 test_run_settlement_guards.py。

三个驱动的契约：
1. 时钟驱动——TaskScheduler 每小时 job（开关开才挂，默认关不挂；既有行为）；
2. 显式驱动——admin 经 POST /v1/swarm-queue/settle 显式触发一次结算，
   不受 NEUROVA_SWARM_AUTO_SETTLE 默认关限制；非 admin 403；九护栏照常生效；
3. 终态助推——run 落终态且开关开时，把下次扫掠提前 60s。TaskScheduler 只
   支持固定周期 job（addSystemJob=IntervalTrigger），故用「到期时间戳」模式：
   终态事件更新 _nextSweepDue，60s 轻量 job 到点查 due 即跑；开关关不调度。

默认关语义不变：无 env、无 admin 调用 → 无任何扫掠、无任何 job 注册。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import neurova.agent.scheduler as schedulerModule
import neurova.agent.swarm as swarmModule
import neurova.agent.swarm_event_log as eventLogModule
from neurova.agent.run_settlement import (
    SETTLE_BOOST_DELAY_SECONDS,
    SETTLE_BOOST_JOB_ID,
    SETTLE_ENV_ENABLED,
    SETTLE_ENV_IDLE_DAYS,
)
from neurova.agent.swarm import SwarmManager, reset_swarm_manager
from neurova.agent.swarm_support import (
    SUBAGENT_COMPLETED,
    SUBAGENT_RUNNING,
    SubAgentRun,
    transitionRun,
)
from neurova.api.auth import get_current_user
from neurova.api.endpoints import swarm_queue_api

DAY = 86400.0
QUEUE_PREFIX = "/v1/swarm-queue"
HOURLY_SWEEP_JOB_ID = "swarm_run_settlement_sweep"


class FakeScheduler:
    """替身调度器：只记录 addSystemJob 呼叫，不拉起真 APScheduler。"""

    def __init__(self):
        self.jobs = []  # (func, jobId, seconds)

    def addSystemJob(self, func, jobId, seconds):
        self.jobs.append((func, jobId, seconds))

    def removeSystemJob(self, jobId):
        self.jobs = [job for job in self.jobs if job[1] != jobId]


@pytest.fixture(autouse=True)
def freshGlobalManager():
    """全局单例隔离：transitionRun 谱系取数会惰性创建全局管理器，逐测重置。"""
    reset_swarm_manager()
    yield
    reset_swarm_manager()


@pytest.fixture()
def fakeScheduler(monkeypatch):
    fake = FakeScheduler()
    monkeypatch.setattr(schedulerModule, "get_scheduler", lambda: fake)
    return fake


@pytest.fixture()
def quietEventLog(monkeypatch):
    """事件归档替身：transitionRun/_logRunEvent 不触盘（本文件不测归档本身）。"""
    monkeypatch.setattr(eventLogModule, "appendRunEvent", lambda *a, **k: "evt_test")
    monkeypatch.setattr(
        swarmModule, "_eventStore",
        lambda: SimpleNamespace(append=lambda *a, **k: None),
    )


def _terminalRun(subagentId, *, finishedAt, status=SUBAGENT_COMPLETED, approvals=None):
    """经生产状态机（transitionRun）落终态的 run；finished_at 由调用方给定。"""
    run = SubAgentRun(subagent_id=subagentId, status=SUBAGENT_RUNNING)
    transitionRun(run, status, cause="test_arrange")
    run.finished_at = finishedAt
    if approvals is not None:
        run.approvals = approvals
    return run


def _overrideRole(app, role):
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "role": role, "username": "u1",
    }


# ── 驱动一：时钟（每小时 job，既有行为钉住） ──────────────────────


class TestClockDriver:
    def test_enabledRegistersHourlySweepJob(self, monkeypatch, fakeScheduler, quietEventLog):
        monkeypatch.setenv(SETTLE_ENV_ENABLED, "1")
        SwarmManager()
        assert any(jobId == HOURLY_SWEEP_JOB_ID and seconds == 3600
                   for _, jobId, seconds in fakeScheduler.jobs)

    def test_disabledDoesNotRegisterHourlyJob(self, monkeypatch, fakeScheduler, quietEventLog):
        monkeypatch.delenv(SETTLE_ENV_ENABLED, raising=False)
        SwarmManager()
        assert not any(jobId == HOURLY_SWEEP_JOB_ID for _, jobId, _ in fakeScheduler.jobs)

    def test_hourlySweepSettlesIdleTerminalRun(self, monkeypatch, fakeScheduler, quietEventLog):
        monkeypatch.setenv(SETTLE_ENV_ENABLED, "1")
        manager = SwarmManager()
        manager._runs["sub-old"] = _terminalRun("sub-old", finishedAt=time.time() - 4 * DAY)
        result = manager.settleIdleRuns()
        assert result["settled"] == ["sub-old"]
        assert "sub-old" not in manager._runs


# ── 驱动二：admin 显式触发（POST /v1/swarm-queue/settle） ─────────


class TestAdminExplicitDriver:
    def test_adminExplicitSettleRunsEvenWhenSwitchOff(self, monkeypatch, fakeScheduler,
                                                      quietEventLog):
        """显式驱动不受默认关限制：开关关 + admin 调用 → 照常结算，返回三桶。"""
        monkeypatch.delenv(SETTLE_ENV_ENABLED, raising=False)
        manager = SwarmManager()
        manager._runs["sub-idle"] = _terminalRun("sub-idle", finishedAt=time.time() - 10 * DAY)
        result = manager.settleIdleRunsNow()
        assert set(result.keys()) == {"settled", "skipped", "failed"}
        assert result["settled"] == ["sub-idle"]
        assert "sub-idle" not in manager._runs

    def test_endpointAdmin200WithThreeBuckets(self, monkeypatch, fakeScheduler, quietEventLog):
        monkeypatch.delenv(SETTLE_ENV_ENABLED, raising=False)
        manager = SwarmManager()
        manager._runs["sub-idle"] = _terminalRun("sub-idle", finishedAt=time.time() - 10 * DAY)
        monkeypatch.setattr(swarm_queue_api, "_manager", lambda: manager)
        app = FastAPI()
        app.include_router(swarm_queue_api.router, prefix=QUEUE_PREFIX)
        _overrideRole(app, "admin")
        resp = TestClient(app).post(f"{QUEUE_PREFIX}/settle")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"settled", "skipped", "failed"}
        assert body["settled"] == ["sub-idle"]
        assert "sub-idle" not in manager._runs

    def test_endpointNonAdmin403(self, monkeypatch, fakeScheduler, quietEventLog):
        monkeypatch.delenv(SETTLE_ENV_ENABLED, raising=False)
        manager = SwarmManager()
        manager._runs["sub-idle"] = _terminalRun("sub-idle", finishedAt=time.time() - 10 * DAY)
        monkeypatch.setattr(swarm_queue_api, "_manager", lambda: manager)
        app = FastAPI()
        app.include_router(swarm_queue_api.router, prefix=QUEUE_PREFIX)
        _overrideRole(app, "user")
        resp = TestClient(app).post(f"{QUEUE_PREFIX}/settle")
        assert resp.status_code == 403
        assert "sub-idle" in manager._runs  # 未执行结算

    def test_explicitTriggerHonoursPendingApprovalGuard(self, monkeypatch, fakeScheduler,
                                                        quietEventLog):
        """显式触发不豁免九护栏：pending 审批一票否决，run 留在台账。"""
        monkeypatch.delenv(SETTLE_ENV_ENABLED, raising=False)
        manager = SwarmManager()
        manager._runs["sub-guard"] = _terminalRun(
            "sub-guard", finishedAt=time.time() - 10 * DAY,
            approvals=[{"status": "pending", "reason": "待审批"}])
        result = manager.settleIdleRunsNow()
        assert result["settled"] == []
        assert result["skipped"] == [["sub-guard", "pending_approval"]]
        assert "sub-guard" in manager._runs

    def test_explicitTriggerHonoursGracePeriodGuard(self, monkeypatch, fakeScheduler,
                                                    quietEventLog):
        """显式触发不豁免宽限期护栏（120s 内的终态 run 不结算）。"""
        monkeypatch.delenv(SETTLE_ENV_ENABLED, raising=False)
        manager = SwarmManager()
        manager._runs["sub-fresh"] = _terminalRun("sub-fresh", finishedAt=time.time() - 30)
        result = manager.settleIdleRunsNow()
        assert result["skipped"] == [["sub-fresh", "grace_period"]]
        assert "sub-fresh" in manager._runs


# ── 驱动三：终态助推（到期时间戳 + 60s 轻量 job） ─────────────────


class TestTerminalBoost:
    def test_boostConstantsAreSingleSourced(self):
        """助推延时 60s、job id 固定——助推与轻量 job 周期同源本常量。"""
        assert SETTLE_BOOST_DELAY_SECONDS == 60.0
        assert SETTLE_BOOST_JOB_ID == "swarm_run_settlement_boost"

    def test_terminalEventWhenEnabledSchedulesBoost(self, monkeypatch, fakeScheduler,
                                                    quietEventLog):
        monkeypatch.setenv(SETTLE_ENV_ENABLED, "1")
        manager = SwarmManager()
        run = _terminalRun("sub-1", finishedAt=time.time())
        manager._runs["sub-1"] = run
        before = time.time()
        manager._logRunEvent(run, "terminal", {"status": run.status})
        boostJobs = [job for job in fakeScheduler.jobs if job[1] == SETTLE_BOOST_JOB_ID]
        assert len(boostJobs) == 1
        assert boostJobs[0][2] == int(SETTLE_BOOST_DELAY_SECONDS)
        assert boostJobs[0][0] == manager._settleBoostTick
        due = manager._nextSweepDue
        assert before + SETTLE_BOOST_DELAY_SECONDS - 5 <= due <= time.time() + SETTLE_BOOST_DELAY_SECONDS + 5

    def test_terminalEventWhenDisabledSchedulesNothing(self, monkeypatch, fakeScheduler,
                                                       quietEventLog):
        """开关关：终态事件不注册助推 job、不设 due（默认关语义不变）。"""
        monkeypatch.delenv(SETTLE_ENV_ENABLED, raising=False)
        manager = SwarmManager()
        run = _terminalRun("sub-1", finishedAt=time.time())
        manager._runs["sub-1"] = run
        manager._logRunEvent(run, "terminal", {"status": run.status})
        assert fakeScheduler.jobs == []
        assert manager._nextSweepDue == 0.0

    def test_boostRegistrationIsIdempotent(self, monkeypatch, fakeScheduler, quietEventLog):
        """多次终态事件只注册一个助推 job；due 取最早的到期时刻。"""
        monkeypatch.setenv(SETTLE_ENV_ENABLED, "1")
        manager = SwarmManager()
        first = _terminalRun("sub-1", finishedAt=time.time())
        second = _terminalRun("sub-2", finishedAt=time.time())
        manager._runs["sub-1"] = first
        manager._runs["sub-2"] = second
        manager._logRunEvent(first, "terminal", {})
        firstDue = manager._nextSweepDue
        manager._logRunEvent(second, "terminal", {})
        assert len([job for job in fakeScheduler.jobs if job[1] == SETTLE_BOOST_JOB_ID]) == 1
        assert manager._nextSweepDue == firstDue  # 第二次不推迟已排定的助推

    def test_boostTickBeforeDueIsNoop(self, monkeypatch, fakeScheduler, quietEventLog):
        monkeypatch.setenv(SETTLE_ENV_ENABLED, "1")
        manager = SwarmManager()
        manager._runs["sub-old"] = _terminalRun("sub-old", finishedAt=time.time() - 10 * DAY)
        manager._nextSweepDue = time.time() + 3600  # 尚未到期
        manager._settleBoostTick()
        assert "sub-old" in manager._runs

    def test_boostTickFiresSweepWhenDue(self, monkeypatch, fakeScheduler, quietEventLog):
        """到期即跑：助推扫掠结算闲置超阈值 run（等价于把小时扫掠提前）。"""
        monkeypatch.setenv(SETTLE_ENV_ENABLED, "1")
        manager = SwarmManager()
        manager._runs["sub-old"] = _terminalRun("sub-old", finishedAt=time.time() - 10 * DAY)
        manager._nextSweepDue = time.time() - 1  # 已到期
        manager._settleBoostTick()
        assert "sub-old" not in manager._runs
        assert manager._nextSweepDue == 0.0  # 跑完清 due，不重复助推

    def test_boostRespectsGuardsOnFreshRun(self, monkeypatch, fakeScheduler, quietEventLog):
        """助推扫掠同样过九护栏：刚终态的 run 落宽限期跳过，老闲置 run 正常结算。"""
        monkeypatch.setenv(SETTLE_ENV_ENABLED, "1")
        manager = SwarmManager()
        manager._runs["sub-old"] = _terminalRun("sub-old", finishedAt=time.time() - 10 * DAY)
        manager._runs["sub-fresh"] = _terminalRun("sub-fresh", finishedAt=time.time())
        manager._nextSweepDue = time.time() - 1
        manager._settleBoostTick()
        assert "sub-old" not in manager._runs
        assert "sub-fresh" in manager._runs  # 宽限期内，跳过


# ── 默认关语义不变 ────────────────────────────────────────────────


class TestDefaultOffSemantics:
    def test_noEnvNoAdminCall_noSweepNoJobs(self, monkeypatch, fakeScheduler, quietEventLog):
        """无 env、无 admin 调用 → 不结算、不挂任何 job（时钟/助推都不挂）。"""
        monkeypatch.delenv(SETTLE_ENV_ENABLED, raising=False)
        monkeypatch.delenv(SETTLE_ENV_IDLE_DAYS, raising=False)
        manager = SwarmManager()
        manager._runs["sub-idle"] = _terminalRun("sub-idle", finishedAt=time.time() - 10 * DAY)
        result = manager.settleIdleRuns()
        assert result == {"enabled": False, "settled": [], "skipped": [], "failed": []}
        assert "sub-idle" in manager._runs
        assert fakeScheduler.jobs == []
