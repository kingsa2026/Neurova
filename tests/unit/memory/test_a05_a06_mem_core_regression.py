"""A-05 / A-06 回归测试（mem_core.py / agent_shutdown.py）。

红绿说明（修复缺位时为红）：
- A-05: `_PersistDbStore` 常驻 sqlite 连接原无 close()、Agent 关闭链路
  无释放路径 → AttributeError / 句柄残留断言失败（红）。
- A-06: 双队列 split-brain——入队 `memory_manager._write_queue`，
  flush 却打 `buffer_module._write_queue` → 该批记忆永不落盘（红）；
  另 `MemoryWriteQueue.__bool__` 按队列非空取值，空队列 falsy 使
  首轮 enqueue_batch 被整体跳过（红）。
"""

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest


# ═══════════════════════════════════════════════════════════════
# A-05: _PersistDbStore.close() + 关闭链路接入
# ═══════════════════════════════════════════════════════════════


def _make_store(tmp_path):
    from neurova.mem_core import _PersistDbStore

    return _PersistDbStore(str(tmp_path / "persist.db"), "a1", "n1", "u1")


def test_a05_persist_db_store_close_idempotent(tmp_path):
    store = _make_store(tmp_path)
    store._ensure_schema()
    store.upsert_row(
        {
            "id": "m1",
            "content": "hello",
            "agent_id": "a1",
            "neuser_id": "n1",
            "user_id": "u1",
        }
    )
    assert len(store.execute("SELECT id FROM memories").fetchall()) == 1

    raw_conn = store._conn
    store.close()
    store.close()  # 幂等：二次 close 不抛错

    with pytest.raises(sqlite3.ProgrammingError):
        raw_conn.execute("SELECT 1")  # 连接真正关闭

    # 关闭后 execute 安全降级为空行集（MoE 后台索引线程不死循环报错）
    assert store.execute("SELECT id FROM memories").fetchall() == []


def test_a05_shutdown_agent_closes_persist_db_store(tmp_path):
    from neurova.agent_shutdown import shutdown_agent

    store = _make_store(tmp_path)
    agent = SimpleNamespace(
        config=SimpleNamespace(name="t"),
        sleep_consolidation=None,
        voice_memory_bridge=None,
        tts_manager=None,
        asr_manager=None,
        conversation_buffer=None,
        cognitive_engine=None,
        attachment_manager=None,
        memory_manager=None,
        memory_agent=SimpleNamespace(_persist_db_store=store),
    )
    asyncio.run(shutdown_agent(agent))

    assert store._conn is None, (
        "A-05: Agent 关闭链路必须释放 _PersistDbStore 常驻连接（Windows 句柄残留）"
    )


def test_a05_mem_core_holds_store_reference(tmp_path):
    """init_moe_router 把 _build_moe_store 的适配器挂到 memory_agent 上，
    供关闭链路定位（无 persist.db 时为 None，不炸）。"""
    from neurova.mem_core import MemCore

    agent = SimpleNamespace(config=SimpleNamespace(db_path=str(tmp_path / "x.db")))
    core = MemCore(agent)
    assert core._persist_db_store is None  # 初始 None，init_moe_router 后持有实例


# ═══════════════════════════════════════════════════════════════
# A-06: 双队列 split-brain
# ═══════════════════════════════════════════════════════════════


class FakeWriteQueue:
    """记录 enqueue/flush 调用的假队列（区分两条队列的落盘路径）。"""

    def __init__(self):
        self.enqueued = []
        self.flushed = 0

    def enqueue_batch(self, items):
        self.enqueued.extend(items)
        return True

    def flush_to_storage(self):
        self.flushed += 1
        return len(self.enqueued)


def _flush_agent(mgr_queue, bufmod_queue, items):
    return SimpleNamespace(
        memory_manager=SimpleNamespace(_write_queue=mgr_queue),
        conversation_buffer=SimpleNamespace(
            is_full=lambda: True, flush=lambda: items
        ),
        buffer_module=SimpleNamespace(_write_queue=bufmod_queue),
    )


def test_a06_flush_before_retrieve_flushes_same_queue_it_enqueues():
    from neurova.mem_core import MemCore

    mgr_queue, bufmod_queue = FakeWriteQueue(), FakeWriteQueue()
    items = [SimpleNamespace(id="i1", content="用户: hi")]
    core = MemCore(_flush_agent(mgr_queue, bufmod_queue, items))

    core.flush_before_retrieve()

    assert mgr_queue.enqueued == items, "A-06: 入队必须进 memory_manager._write_queue"
    assert mgr_queue.flushed == 1, (
        "A-06: flush 必须打同一条队列（原实现打 buffer_module 队列→该批记忆永不落盘）"
    )
    assert bufmod_queue.flushed == 0, "A-06: 不得再直 flush buffer_module._write_queue"


def test_a06_save_conversation_memory_enqueues_into_empty_real_queue():
    """MemoryWriteQueue 空队列 falsy（__bool__ 按非空取值）不得跳过入队。"""
    from neurova.cognitive_layers.memory_layer.conversation_buffer import (
        MemoryWriteQueue,
    )
    from neurova.mem_core import MemCore

    remembered = []
    real_queue = MemoryWriteQueue(
        storage=None,
        agent_id="a1",
        memory_manager=SimpleNamespace(remember=lambda **kw: remembered.append(kw)),
    )
    fake_mm = SimpleNamespace(
        remember=lambda **kw: remembered.append(kw),
        _write_queue=real_queue,
    )
    flushed_items = [
        SimpleNamespace(
            id="x1",
            content="用户: hi",
            timestamp=None,
            classification="user_message",
            categories=[],
            meta_trace=None,
        )
    ]
    agent = SimpleNamespace(
        memory_manager=fake_mm,
        conversation_buffer=SimpleNamespace(
            add_user_message=lambda m: None,
            add_agent_message=lambda m: None,
            is_full=lambda: True,
            flush=lambda: flushed_items,
        ),
    )
    core = MemCore(agent)

    core.save_conversation_memory("hi", "hello")

    assert real_queue.get_queue_size() == 1, (
        "A-06: 空队列（falsy）不得跳过 enqueue_batch——原 `if queue:` 使首轮入队整体丢失"
    )
