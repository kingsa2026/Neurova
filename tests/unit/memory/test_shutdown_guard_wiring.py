# -*- coding: utf-8 -*-
"""K2 启动接线：app 启动链装配 ShutdownGuard + swarm 事件账本收敛。

钉住 neurova/api/app.py::_on_startup 的装配契约：
- 启动后 app_state.shutdown_guard 非 None（真装配 neurova.recovery 的单例），
  且 ShutdownGuard.prepare_startup 在启动路径被调用（喂的是活 agents 表）；
- swarm 事件账本收敛入口（reconcileSwarmRunsAtStartup）在启动路径被调用。

生产代码必须真装配；本测试只下轻量桩（重型组件初始化换 no-op、
prepare_startup/收敛入口换观察哨）验证调用序，不断言桩返回值。
"""

import pytest

import neurova.agent.swarm as swarmModule
from neurova.api import app as appModule
from neurova.recovery.shutdown_guard import ShutdownGuard, reset_shutdown_guard


@pytest.fixture
def quietStartup(tmp_path, monkeypatch):
    """关掉启动链的后台循环/下载面（env 开关），重型初始化与子进程面换轻桩。

    只为让 _on_startup 在单测环境快速走完；装配/收敛两处目标代码不打桩。
    """
    from neurova.core import agent_run_store as ars

    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "agent_runs.db"))
    monkeypatch.setenv("NEUROVA_KNOWLEDGE_ASYNC", "off")
    monkeypatch.setenv("NEUROVA_KB_INDEX_MAINTENANCE", "off")
    monkeypatch.setenv("NEUROVA_KB_INGEST_WORKER", "off")
    monkeypatch.setenv("NEUROVA_KB_SYNC", "off")
    monkeypatch.setenv("NEUROVA_OUTBOX_DRAIN", "off")
    monkeypatch.setenv("NEUROVA_COST_TRACKING", "off")
    monkeypatch.setenv("NEUROVA_FFMPEG_AUTODOWNLOAD", "0")
    monkeypatch.setattr(appModule, "_initialize_components", lambda state: None)
    monkeypatch.setattr(appModule, "_schedule_mcp_bootstrap", lambda state: None)
    monkeypatch.setattr(appModule, "_schedule_channel_bootstrap", lambda state: None)
    yield
    ars.reset_agent_run_store()


@pytest.fixture(autouse=True)
def _resetGuardSingleton():
    reset_shutdown_guard()
    yield
    reset_shutdown_guard()


async def _stopStartupBackgroundLoops():
    """收敛 _on_startup 拉起的常驻扫描任务，测试不留悬空 task。"""
    from neurova.aigc_studio.video_reconcile import stopReconcileSweep
    from neurova.core.agent_run_store import stopStaleSweep
    from neurova.llm.generators.recovery import stop_generation_recovery

    for stop in (stop_generation_recovery(), stopStaleSweep()):
        try:
            await stop
        except Exception:  # noqa: BLE001 - 测试收尾不互相牵连
            pass
    try:
        stopReconcileSweep()
    except Exception:  # noqa: BLE001
        pass


@pytest.mark.asyncio
async def test_on_startup_assembles_shutdown_guard_and_swarm_reconcile(quietStartup, monkeypatch):
    """启动路径真装配：shutdown_guard 非 None、prepare_startup 被调用、swarm 收敛被调用。"""
    guardCalls = []

    def spyPrepareStartup(self, agents):
        guardCalls.append({"agents": agents})
        return {"abnormal": False, "recovered_memories": 0, "sentinel_written": True}

    monkeypatch.setattr(ShutdownGuard, "prepare_startup", spyPrepareStartup)

    swarmCalls = []

    def spySwarmReconcile():
        swarmCalls.append(True)
        return {"checked": 0, "corrected": 0, "results": []}

    monkeypatch.setattr(swarmModule, "reconcileSwarmRunsAtStartup", spySwarmReconcile)

    state = appModule.AppState()
    try:
        await appModule._on_startup(state)
    finally:
        await _stopStartupBackgroundLoops()

    assert state.shutdown_guard is not None, "启动后 shutdown_guard 必须已装配"
    assert isinstance(state.shutdown_guard, ShutdownGuard)
    assert len(guardCalls) == 1, "prepare_startup 应在启动路径被恰好调用一次"
    assert guardCalls[0]["agents"] is state.agents, "prepare_startup 应喂活 agents 表"
    assert len(swarmCalls) == 1, "swarm 启动收敛应在启动路径被恰好调用一次"


class _FakeMemoryManager:
    def __init__(self):
        self.flushCalls = 0

    def flush_buffer(self):
        self.flushCalls += 1
        return self.flushCalls


class _FakeAgent:
    """最小 Agent 形状：memory_manager.flush_buffer + async shutdown。"""

    def __init__(self):
        self.memory_manager = _FakeMemoryManager()

    async def shutdown(self):
        return None


@pytest.mark.asyncio
async def test_on_shutdown_runs_guard_graceful_shutdown(quietStartup, tmp_path):
    """关停路径真装配成对：_on_startup 真 prepare_startup 写 sentinel，
    _on_shutdown 真 graceful_shutdown 刷缓冲并摘除 sentinel。"""
    from neurova.core.data_root import dataLanding

    state = appModule.AppState()
    state.agents = {"default": _FakeAgent()}
    try:
        await appModule._on_startup(state)
    finally:
        await _stopStartupBackgroundLoops()

    sentinel = dataLanding("shutdown") / ".neurova_shutdown_sentinel"
    assert state.shutdown_guard is not None
    assert sentinel.exists(), "启动后 sentinel 应已写入（真 prepare_startup）"

    agent = state.agents["default"]
    await appModule._on_shutdown(state)

    assert agent.memory_manager.flushCalls >= 1, "关停应刷新 agent 对话缓冲"
    assert not sentinel.exists(), "优雅关停后 sentinel 应被摘除（下次启动视为干净）"
