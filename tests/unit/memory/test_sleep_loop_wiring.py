"""睡眠整理触发链修复回归测试（TDD）

断点：
1. IdleTimeTracker 监控线程从未 start → 空闲阶段永不切换，睡眠整理死路
   （agent_core.py 只构造不启动）
2. agent_shutdown 跑完 run_sleep_cycle 后结果只写日志——合并记忆丢弃、
   源记忆保留、归档状态不更新 → 关机整理是无效计算
3. idle_tracker._write_back_consolidated_memories 收集了 source_ids 却从未
   删除被合并的源记忆 → 整理后记忆数量翻倍

统一方案：抽出共享写回函数 write_back_consolidation_result()
（sleep_writeback.py），idle_tracker 与关机路径共用；补齐源记忆删除。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ----------------------------- 写回函数 -----------------------------


def _make_manager():
    manager = MagicMock()
    manager.remember.return_value = "mem_new"
    manager.forget.return_value = True
    return manager


def _result():
    merged = SimpleNamespace(
        merged_from=["m1", "m2"],
        content="合并后的记忆",
        categories=["conversation"],
        importance=80.0,
        temperature=60.0,
        is_archived=False,
        id="merged_1",
    )
    archived = SimpleNamespace(
        merged_from=None,
        content="旧事",
        categories=[],
        importance=10.0,
        temperature=5.0,
        is_archived=True,
        id="m3",
    )
    return {
        "merged_memories": [merged, archived],
        "merge_results": [SimpleNamespace(source_ids=["m1", "m2"])],
    }


def test_write_back_adds_merged_and_deletes_sources():
    from neurova.cognitive_layers.memory_layer.sleep_writeback import write_back_consolidation_result

    manager = _make_manager()
    stats = write_back_consolidation_result(manager, _result())

    # 合并记忆写入
    assert manager.remember.call_count == 1
    assert manager.remember.call_args.kwargs["content"] == "合并后的记忆"
    # 被合并的源记忆必须删除（此前只收集不删除 → 记忆翻倍）
    forgotten = {c.args[0] for c in manager.forget.call_args_list}
    assert {"m1", "m2"} <= forgotten
    assert stats["added"] == 1


def test_write_back_updates_archived_lifecycle():
    from neurova.cognitive_layers.memory_layer.sleep_writeback import write_back_consolidation_result

    manager = _make_manager()
    write_back_consolidation_result(manager, _result())
    manager.update_memory.assert_called_once()
    kwargs = manager.update_memory.call_args.kwargs
    assert kwargs["memory_id"] == "m3"
    assert kwargs["lifecycle_stage"] == "archived"


def test_write_back_never_raises():
    """写回失败不得阻断关闭流程"""
    from neurova.cognitive_layers.memory_layer.sleep_writeback import write_back_consolidation_result

    manager = _make_manager()
    manager.remember.side_effect = RuntimeError("boom")
    stats = write_back_consolidation_result(manager, _result())
    assert isinstance(stats, dict)


# ----------------------------- 触发链接通 -----------------------------


def test_bind_and_start_sleep_loop_starts_monitor_thread():
    """agent_core 必须真正启动 IdleTimeTracker 监控线程"""
    from neurova.core.idle_tracker import IdleTimeTracker
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
    from neurova.agent_shutdown import bind_and_start_sleep_loop

    agent = SimpleNamespace(
        config=SimpleNamespace(name="t"),
        idle_tracker=IdleTimeTracker(),
        sleep_consolidation=SleepConsolidation(),
        memory_manager=MagicMock(),
    )
    bind_and_start_sleep_loop(agent)

    try:
        assert agent.idle_tracker._monitor_running is True, "监控线程应已启动"
        assert agent.idle_tracker.get_state_value("running") is True
    finally:
        agent.idle_tracker.on_stop()


def test_shutdown_agent_writes_back_consolidation(monkeypatch):
    """关机整理：合并记忆要写回，不能只打日志"""
    import asyncio

    from neurova.agent_shutdown import shutdown_agent
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    written = []
    manager = MagicMock()
    manager.get_all_memories.return_value = [
        {"id": "m1", "content": "a", "category": "conversation", "temperature": 50, "importance": 50},
        {"id": "m2", "content": "b", "category": "conversation", "temperature": 40, "importance": 50},
    ]
    manager.remember.side_effect = lambda **kw: written.append(kw) or "mem_new"

    class StubConsolidation(SleepConsolidation):
        def run_sleep_cycle(self, memories=None):
            return _result()

    agent = SimpleNamespace(
        config=SimpleNamespace(name="t"),
        memory_manager=manager,
        sleep_consolidation=StubConsolidation(),
        voice_memory_bridge=None,
        tts_manager=None,
        asr_manager=None,
        conversation_buffer=None,
    )

    asyncio.run(shutdown_agent(agent))
    assert any(kw.get("content") == "合并后的记忆" for kw in written), "合并记忆应在关机时写回"


def test_shutdownAgentStopsTheMonitorItStarted():
    """start/stop 必须成对：`bind_and_start_sleep_loop` 起的监控线程，关闭路径要停掉。

    实况（本批现查）：`agent_core.py:1406` 逐 Agent 调 `bind_and_start_sleep_loop`
    （`agent_shutdown.py:16`）起一条名为 `idle-tracker-monitor` 的线程，而**同一模块里的**
    `shutdown_agent` 关掉了语音桥／TTS／ASR／对话缓冲，唯独没停这条线程——
    `IdleTimeTracker.on_stop → _stop_monitoring`（含 `join(timeout=5)`）一直存在且可用，
    只是无人调用。⇒ 长会话里每建一个 Agent 就永久多一条监控线程：2026-10-23 整场
    `pytest tests/unit` 在 92% 处 `STATUS_STACK_OVERFLOW` 崩机，faulthandler dump 里数十条
    线程都停在这个名字上（台账 §6-402 登记该读数）。累积**不在测试侧**——本批复算过：
    测试里起监控线程的落点共 10 处（`test_idle_tracker.py:294/300/302/307/370`、
    `test_sleep_loop.py:40/53/233`、`test_idle_tracker_phase_loop.py:134`），逐处都配了
    `_stop_monitoring()`／`on_stop()`（有的在夹具 `yield` 之后 `:93/:290`，有的在 `finally`
    `test_idle_tracker_phase_loop.py:143-144`）；漏的是生产这一对 start/stop。

    断言钉的是**那条线程对象**不再存活，不是全局线程计数——后者会被别的档的残留污染，
    红或绿都不说明问题；另加一条状态断言，要求走 `BaseModule.stop()` 那台状态机，
    而不是把 `_monitor_running` 拨成 False 装作关过。
    """
    import asyncio

    from neurova.agent_shutdown import bind_and_start_sleep_loop, shutdown_agent
    from neurova.core.idle_tracker import IdleTimeTracker
    from neurova.core.base_module import ModuleState

    tracker = IdleTimeTracker()
    agent = SimpleNamespace(
        config=SimpleNamespace(name="t"),
        idle_tracker=tracker,
        post_chat_pipeline=None,
        memory_manager=None,
        sleep_consolidation=None,
        voice_memory_bridge=None,
        tts_manager=None,
        asr_manager=None,
        conversation_buffer=None,
    )
    bind_and_start_sleep_loop(agent)
    monitorThread = tracker._monitor_thread
    assert tracker._monitor_running and monitorThread is not None, (
        "前置不成立：启动没起线程，本格会因『没有东西要关』而假绿"
    )

    try:
        asyncio.run(shutdown_agent(agent))

        assert tracker._monitor_running is False, (
            "关闭路径没停监控线程——start/stop 不成对，每建一个 Agent 就永久多一条线程"
        )
        monitorThread.join(timeout=6.0)
        assert not monitorThread.is_alive(), (
            "标志位是 False 但线程还活着：没走 `_stop_monitoring` 的 join，或只拨了标志"
        )
        assert tracker._state == ModuleState.STOPPED, (
            "没经 `BaseModule.stop()` 收尾（状态 %s）——绕开状态机的关闭不会通知 on_stop 的另一半"
            % tracker._state
        )
    finally:
        tracker.on_stop()


def test_stopAllIdleMonitorsReclaimsWhatIsStillRunning():
    """统一回收口的契约：起两条收得掉两条，且收完登记表为空。

    没有这一格，conftest 里那句 `stopAllIdleMonitors()` 可以是个空函数——它跑在每格之后、
    没有任何判据读它，坏掉也不会有人红（“只写不读”的断点形态）。
    """
    from neurova.core.idle_tracker import IdleTimeTracker, stopAllIdleMonitors

    assert stopAllIdleMonitors() == 0, (
        "起点不干净：上一格留下的监控线程没被按格回收，本格的读数就不可信"
    )
    first, second = IdleTimeTracker(), IdleTimeTracker()
    threads = []
    try:
        for tracker in (first, second):
            tracker._start_monitoring()
            threads.append(tracker._monitor_thread)
        assert threads and all(t is not None and t.is_alive() for t in threads), (
            "前置不成立：两条监控线程没真跑起来，本格会因『没东西要收』而假绿"
        )
        assert stopAllIdleMonitors() == 2, (
            "回收口没数到两条活跃线程——登记表或 _monitor_running 有一边没维护"
        )
    finally:
        first._stop_monitoring()
        second._stop_monitoring()
    for thread in threads:
        thread.join(timeout=6.0)
        assert not thread.is_alive(), "回收只改了标志位，线程还活着"
    assert stopAllIdleMonitors() == 0, "回收后登记表没清空"
