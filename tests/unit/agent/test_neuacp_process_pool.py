# -*- coding: utf-8 -*-
"""B3 红灯：外部代理进程池与生命周期（设计文档 §4.5/§6.4）。

- 池键含租户段 ``(tenant, tool, command, cwd, transport, remote)``，跨租户不共享；
- 全局并发上限读 ``NEUROVA_EXTERNAL_AGENTS_MAX_PROCS``（默认 4），超限排队；
- 空闲回收读 ``NEUROVA_EXTERNAL_AGENTS_IDLE_S``（默认 600s）；
- 崩溃进程踢出池（重启由下次 acquire 惰性完成）；
- ``SwarmManager.cancelRun`` 对外部成员调 ``adapter.cancel()``，传导
  ``executor.cancel()``（ACP 侧 session/cancel）。
"""
import asyncio
import threading
import time

import pytest

from neurova.agent.neuacp.acp_client import NeuacpError
from neurova.agent.neuacp.acp_member import NeuacpMemberAdapter
from neurova.agent.neuacp.process_pool import (
    NeuacpProcessPool,
    envIdleSeconds,
    envMaxProcs,
    getNeuacpProcessPool,
    poolKey,
)
from neurova.agent.swarm import SubAgentRun, get_swarm_manager, reset_swarm_manager


class FakeProcess:
    """进程替身：is_alive 属性 + terminate()（与 NeuacpClient 形状一致）。"""

    def __init__(self, alive=True):
        self._alive = alive
        self.terminated = False

    @property
    def is_alive(self):
        return self._alive and not self.terminated

    def terminate(self):
        self.terminated = True


def makePool(**overrides):
    fields = {"maxProcs": 4, "idleSeconds": 600.0}
    fields.update(overrides)
    return NeuacpProcessPool(**fields)


KEY_A = poolKey("t1", "opencode", ["opencode", "acp"], "/w/a")
KEY_A_SAME = poolKey("t1", "opencode", ["opencode", "acp"], "/w/a")
KEY_A_T2 = poolKey("t2", "opencode", ["opencode", "acp"], "/w/a")
KEY_B = poolKey("t1", "qoder", ["qoder", "--acp"], "/w/b")


# ── 键与默认值 ───────────────────────────────────────────────────────────

def test_poolKeyIncludesTenantSegment():
    key = poolKey("t1", "opencode", ["opencode", "acp"], "/w/a")
    assert key == ("t1", "opencode", ("opencode", "acp"), "/w/a", "stdio", "")
    # transport/remote 缺省 stdio/""；租户空回落 default
    assert poolKey("", "x", ["x"], "")[0] == "default"
    assert poolKey("t1", "x", ["x"], "/w", transport="ssh", remote="host-1")[-2:] == ("ssh", "host-1")


def test_tenantSegmentIsolatesPoolEntries():
    """同 tool/command/cwd、不同租户 → 不共享进程（§6.4 红线）。"""
    pool = makePool()
    made = []
    a = pool.acquire(KEY_A, lambda: made.append("a") or FakeProcess())
    b = pool.acquire(KEY_A_T2, lambda: made.append("b") or FakeProcess())
    assert made == ["a", "b"]
    assert a.process is not b.process
    pool.release(KEY_A, a)
    # t2 的 acquire 不会拿到 t1 的空闲进程
    c = pool.acquire(KEY_A_T2, lambda: made.append("c") or FakeProcess())
    assert made == ["a", "b", "c"]
    pool.release(KEY_A_T2, b)
    pool.release(KEY_A_T2, c)
    pool.shutdown()


def test_envDefaultsAndOverrides(monkeypatch):
    monkeypatch.delenv("NEUROVA_EXTERNAL_AGENTS_MAX_PROCS", raising=False)
    monkeypatch.delenv("NEUROVA_EXTERNAL_AGENTS_IDLE_S", raising=False)
    assert envMaxProcs() == 4
    assert envIdleSeconds() == 600.0
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_MAX_PROCS", "2")
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_IDLE_S", "30")
    assert envMaxProcs() == 2
    assert envIdleSeconds() == 30.0
    # 非法值回落默认
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_MAX_PROCS", "abc")
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_IDLE_S", "-x")
    assert envMaxProcs() == 4
    assert envIdleSeconds() == 600.0


def test_singletonSharedInstance(monkeypatch):
    monkeypatch.delenv("NEUROVA_EXTERNAL_AGENTS_MAX_PROCS", raising=False)
    assert getNeuacpProcessPool() is getNeuacpProcessPool()
    assert isinstance(getNeuacpProcessPool(), NeuacpProcessPool)


# ── 复用 / 排队 / 上限 ───────────────────────────────────────────────────

def test_acquireReusesIdleEntryOfSameKey():
    pool = makePool()
    made = []
    first = pool.acquire(KEY_A, lambda: made.append(1) or FakeProcess())
    pool.release(KEY_A, first)
    second = pool.acquire(KEY_A_SAME, lambda: made.append(2) or FakeProcess())
    assert made == [1]
    assert second.process is first.process
    pool.shutdown()


def test_acquireQueuesWhenAtCapAndWakesOnRelease():
    """达到上限后 acquire 排队；release 腾出名额唤醒队首。"""
    pool = makePool(maxProcs=1)
    made = []
    first = pool.acquire(KEY_A, lambda: made.append("a") or FakeProcess())
    outcome = {}

    def waiter():
        outcome["entry"] = pool.acquire(KEY_B, lambda: made.append("b") or FakeProcess(),
                                         waitTimeout=5.0)

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.15)
    assert "entry" not in outcome  # 仍在排队
    pool.release(KEY_A, first)
    thread.join(timeout=3.0)
    assert not thread.is_alive()
    entry = outcome["entry"]
    assert made == ["a", "b"]  # 不同 key，复用不了 → 新建；旧进程被收走
    assert entry.process is not first.process
    assert first.process.terminated
    pool.release(KEY_B, entry)
    pool.shutdown()


def test_acquireTimeoutAtCapRaises():
    pool = makePool(maxProcs=1)
    held = pool.acquire(KEY_A, FakeProcess)
    with pytest.raises(NeuacpError):
        pool.acquire(KEY_B, FakeProcess, waitTimeout=0.2)
    pool.release(KEY_A, held)
    pool.shutdown()


def test_releaseParksIdleWhenNoWaiters():
    pool = makePool(maxProcs=1)
    made = []
    first = pool.acquire(KEY_A, lambda: made.append(1) or FakeProcess())
    pool.release(KEY_A, first)
    assert not first.process.terminated  # 无人排队 → 驻留空闲池待复用
    assert pool.stats()["idle"] == 1
    pool.shutdown()


# ── 崩溃踢出 / 空闲回收 ──────────────────────────────────────────────────

def test_crashedIdleEntryEvictedOnAcquire():
    pool = makePool()
    made = []
    first = pool.acquire(KEY_A, lambda: made.append(1) or FakeProcess())
    first.process._alive = False  # 空闲期间崩溃
    pool.release(KEY_A, first)
    second = pool.acquire(KEY_A, lambda: made.append(2) or FakeProcess())
    assert made == [1, 2]  # 崩溃件不复活，惰性重建
    assert second.process is not first.process
    assert pool.stats()["crashes"] >= 1
    pool.release(KEY_A, second)
    pool.shutdown()


def test_discardEvictsAndWakesWaiter():
    """使用中崩溃 → discard 踢出，排队者拿到名额。"""
    pool = makePool(maxProcs=1)
    made = []
    first = pool.acquire(KEY_A, lambda: made.append("a") or FakeProcess())
    outcome = {}

    def waiter():
        outcome["entry"] = pool.acquire(KEY_B, lambda: made.append("b") or FakeProcess(),
                                         waitTimeout=5.0)

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.15)
    pool.discard(KEY_A, first, reason="external agent crashed")
    thread.join(timeout=3.0)
    assert not thread.is_alive()
    assert outcome["entry"].process is not first.process
    assert first.process.terminated
    assert made == ["a", "b"]
    assert pool.stats()["crashes"] == 1
    pool.release(KEY_B, outcome["entry"])
    pool.shutdown()


def test_idleSweepReclaimsExpiredEntries():
    pool = makePool(idleSeconds=0.05)
    first = pool.acquire(KEY_A, FakeProcess)
    pool.release(KEY_A, first)
    time.sleep(0.15)
    assert pool.sweepIdle() == 1
    assert first.process.terminated
    assert pool.stats()["idle"] == 0
    # 回收后重新 acquire → 新建
    made = []
    second = pool.acquire(KEY_A, lambda: made.append(1) or FakeProcess())
    assert made == [1]
    pool.release(KEY_A, second)
    pool.shutdown()


def test_idleSweepKeepsFreshEntries():
    pool = makePool(idleSeconds=600.0)
    first = pool.acquire(KEY_A, FakeProcess)
    pool.release(KEY_A, first)
    assert pool.sweepIdle() == 0
    assert not first.process.terminated
    again = pool.acquire(KEY_A, FakeProcess)
    assert again.process is first.process
    pool.release(KEY_A, again)
    pool.shutdown()


def test_shutdownClosesIdleEntriesAndRejectsAcquire():
    pool = makePool()
    first = pool.acquire(KEY_A, FakeProcess)
    pool.release(KEY_A, first)
    pool.shutdown()
    assert first.process.terminated
    assert pool.stats()["closed"] is True
    with pytest.raises(NeuacpError):
        pool.acquire(KEY_B, FakeProcess, waitTimeout=0.1)


# ── cancelRun → adapter.cancel() → executor.cancel() 传导 ───────────────

class TrackingExecutor:
    """记录 cancel 调用的执行体替身。"""

    def __init__(self):
        self.cancelled = 0

    async def start(self, ctx):
        return None

    async def prompt(self, task_text, emitter, on_permission):
        from neurova.agent.neuacp.executor import NeuacpExecResult
        return NeuacpExecResult(text="done")

    async def cancel(self):
        self.cancelled += 1

    async def close(self):
        return None


def test_adapterCancelPropagatesToExecutor():
    executor = TrackingExecutor()
    adapter = NeuacpMemberAdapter(executor, name="外部成员")
    assert adapter.cancel is not None
    asyncio.run(adapter.cancel())
    assert executor.cancelled == 1


def test_cancelRunCancelsExternalAdapter():
    """swarm.cancelRun 对外部成员（适配器）调用 adapter.cancel()。"""
    swarm = get_swarm_manager()
    run = SubAgentRun(
        agent_id="ext-1", agent_name="外部编码代理", task="做个任务",
        session_id="parent-session", origin="chat", member_session_id="swarm_member_b3",
    )
    executor = TrackingExecutor()
    adapter = NeuacpMemberAdapter(executor, name="外部编码代理")
    loop = asyncio.new_event_loop()
    loopThread = threading.Thread(target=loop.run_forever, daemon=True)
    loopThread.start()
    try:
        async def register():
            swarm._runs[run.subagent_id] = run
            with swarm._lock:
                swarm._externalAdapters[run.subagent_id] = (adapter, loop)
            task = asyncio.create_task(asyncio.sleep(30))
            with swarm._lock:
                swarm._tasks[run.subagent_id] = task
            return task

        task = asyncio.run_coroutine_threadsafe(register(), loop).result(timeout=5)
        result = swarm.cancelRun(run.subagent_id, reason="测试取消")
        assert result["success"] is True
        # cancel 协程投递与终态落账都在侧循环异步完成——轮询等到位再断言
        deadline = time.time() + 5
        while time.time() < deadline and (executor.cancelled == 0 or run.status != "failed"):
            time.sleep(0.02)
        assert executor.cancelled == 1
        assert run.status == "failed"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loopThread.join(timeout=2)
        loop.close()
        reset_swarm_manager()


def test_launchRunCarriesExternalAdapterForPromotedBlockedRun(monkeypatch):
    """blocked 放行路径：等待件携带的外部适配器在 _launchRun 续用——
    外部 id 不在 Agent 注册表，走 _resolve_agent 会错拿内置兜底；
    放行后适配器登记不断（cancelRun 传导链完整）。"""
    swarm = get_swarm_manager()
    executed = {}

    async def fakeExecute(run, agent, initiator_agent, stream):
        executed["agent"] = agent
        await asyncio.sleep(30)  # 挂起保持 running，供断言登记态

    monkeypatch.setattr(swarm, "_execute", fakeExecute)
    adapter = NeuacpMemberAdapter(TrackingExecutor(), name="外部编码代理")
    info = {
        "subagent_id": "swarm_blocked_ext", "depth": 1,
        "agent_id": "ext-1", "agent_name": "外部编码代理", "task": "做个任务",
        "origin": "chat", "session_id": None, "stream": True,
        "initiator_agent": None, "node_id": None, "execution_id": None,
        "subagent_type": "general", "task_unit": None,
        "tool_allowlist": frozenset(), "parent_trace_id": "", "data_fence": None,
        "room_id": "", "project_id": "", "team_id": "team-1", "team_role": "",
        "team_member": None, "runtime_budget_sec": 0.0,
        "external_adapter": adapter,
    }

    async def scenario():
        run = swarm._launchRun(info)
        task = swarm._tasks.get(run.subagent_id)
        await asyncio.sleep(0)  # 让派生任务真正开跑（create_task 只登记不执行）
        try:
            assert run.agent_id == "ext-1"
            assert swarm._runs.get(run.subagent_id) is run
            assert swarm._externalAdapters.get(run.subagent_id, (None, None))[0] is adapter
            assert executed.get("agent") is adapter
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    try:
        asyncio.run(scenario())
    finally:
        reset_swarm_manager()

