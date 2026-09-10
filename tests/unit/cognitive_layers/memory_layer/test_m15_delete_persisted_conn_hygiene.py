"""M-15 回归测试：_delete_persisted_memory 连接卫生。

根因：manager.py `_delete_persisted_memory`
- 新建 sqlite 连接未设 `PRAGMA busy_timeout`（同文件 :291/:473/:532 先例）；
- close() 不在 finally：execute/commit 抛错即泄漏连接。

修复后契约：
- 连接带 busy_timeout=4000（与文件内先例同口径）；
- 无论成败（含注入的 DELETE 失败），连接必被 close。
"""

import sqlite3

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


class _ConnProxy:
    """sqlite3.Connection 的薄代理（C 类型无法在实例上覆写方法）。"""

    def __init__(self, conn, record):
        self._conn = conn
        self._record = record

    def execute(self, sql, *args):
        upper = sql.upper()
        if "PRAGMA" in upper:
            self._record["pragmas"].append(sql)
        if self._record["fail_on_delete"] and "DELETE" in upper:
            raise sqlite3.OperationalError("injected delete failure")
        return self._conn.execute(sql, *args)

    def commit(self):
        return self._conn.commit()

    def close(self):
        self._record["closed"] = True
        return self._conn.close()

    def __getattr__(self, item):
        return getattr(self._conn, item)


@pytest.fixture()
def manager(tmp_path):
    mgr = MemoryManager(
        db_path=str(tmp_path / "m15" / "mem.db"),
        agent_id="m15-agent",
        neuser_id="neu",
        user_id="u",
    )
    yield mgr
    try:
        mgr._emotion_module.shutdown()
    except Exception:
        pass


def test_delete_persisted_sets_busy_timeout_and_closes_in_finally(
    manager, tmp_path, monkeypatch
):
    manager.remember(content="to-delete", id="del-me-1")

    record = {"closed": False, "pragmas": [], "fail_on_delete": True}
    real_connect = sqlite3.connect

    def fake_connect(*args, **kwargs):
        return _ConnProxy(real_connect(*args, **kwargs), record)

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    # DELETE 注入失败：close 仍必须执行（finally 收口）
    manager._delete_persisted_memory("del-me-1")

    monkeypatch.undo()

    assert record["closed"], "DELETE 抛错后连接未关闭（close 不在 finally）"
    assert any("busy_timeout" in p for p in record["pragmas"]), (
        "删除路径连接未设置 PRAGMA busy_timeout"
    )

    # 无注入时删除真实生效
    manager.remember(content="to-delete-2", id="del-me-2")
    manager._delete_persisted_memory("del-me-2")
    conn = sqlite3.connect(str(tmp_path / "m15" / "neurova_memories_persist.db"))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE id = ?", ("del-me-2",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0
