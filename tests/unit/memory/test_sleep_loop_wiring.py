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
