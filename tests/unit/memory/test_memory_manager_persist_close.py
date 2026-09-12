"""B-1 轮实证回归：MemoryManager.close() 必须关闭 _persist_conn 常驻 WAL 连接。

3820cdd9 引入常驻连接时漏修本生命周期——不关则 agent 工作区删除/包导入
回滚 rmtree 撞 neurova_memories_persist.db 句柄（WinError 32）。
"""

import sqlite3

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


@pytest.fixture
def manager(tmp_path):
    mgr = MemoryManager(
        agent_id="persist-close-agent",
        user_id="u1",
        db_path=str(tmp_path / "memory.db"),
    )
    yield mgr
    mgr.close()


def test_persist_conn_initialized(manager):
    assert getattr(manager, "_persist_conn", None) is not None


def test_close_closes_persist_conn(manager):
    conn = manager._persist_conn
    manager.close()
    assert manager._persist_conn is None
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_close_idempotent(manager):
    manager.close()
    manager.close()  # 二次关闭不抛错
    assert manager._persist_conn is None
