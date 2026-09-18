"""M-15 回归测试：_delete_persisted_memory 连接卫生。

根因：manager.py `_delete_persisted_memory`
- 新建 sqlite 连接未设 `PRAGMA busy_timeout`（同文件 :291/:473/:532 先例）；
- close() 不在 finally：execute/commit 抛错即泄漏连接。

修复后契约（M-15 原样保留）：
- 连接必须带 busy_timeout（写竞争有等待上限）；
- 无论成败（含注入的 DELETE 失败），连接必被释放。

**2026-09-18 契约表达更新（Issue #57 / ADR 0014）**：该路径是"单次操作借出
即归还"的短连接，已迁入连接池。于是"释放"的形态从"close()"变为"归还池"——
`close()` 不再是正确断言（池连接归还后仍存活复用，本就不该关）。故断言改为
**机制无关的可观测结果**，且比原断言更强：

1. 抛错后池的 `active_count` 必须归零（借出数没归零 = 真泄漏）；
2. busy_timeout 必须在**生效状态**（读 PRAGMA 实际值），而不是"PRAGMA 语句
   被执行过"——后者在"执行了但随后被改掉"时仍会通过；
3. 无注入时删除必须真实生效。

原测试的 `_ConnProxy` 形状依赖"每次都新建连接"，池化后连接被复用故不再适用；
新断言直接查池状态，覆盖面更大。
"""

import sqlite3

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


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
    """DELETE 注入失败后：连接不得泄漏（归还池）+ busy_timeout 必须生效。"""
    from neurova.core import connection_pool as cp

    manager.remember(content="to-delete", id="del-me-1")

    persist_db = str(tmp_path / "m15" / "neurova_memories_persist.db")
    pool = cp.get_connection_pool(persist_db, max_connections=2)

    # DELETE 注入失败：连接仍必须被释放（池的借出计数归零）。
    # sqlite3.Connection 是 C 类型（不可覆写方法），故在 MemoryManager 侧的
    # upsert/执行入口打桩——注入的是"该路径内部抛错"，与原来的效果等价。
    # 池已持有连接，无法替换 factory；在"短事务包装"上打桩等价于让该路径
    # 内部的 DELETE 抛错
    import neurova.core.database as _db

    real_short = _db.short_transaction

    class _BoomConn:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            if "DELETE" in sql.upper():
                raise sqlite3.OperationalError("injected delete failure")
            return self._inner.execute(sql, *args)

        def __getattr__(self, item):
            return getattr(self._inner, item)

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

    import contextlib

    @contextlib.contextmanager
    def patched_short_transaction(db_path=None):
        with real_short(db_path) as conn:
            yield _BoomConn(conn)

    monkeypatch.setattr(_db, "short_transaction", patched_short_transaction)
    manager._delete_persisted_memory("del-me-1")
    monkeypatch.undo()

    assert pool.active_count == 0, (
        f"DELETE 抛错后有连接未释放（active={pool.active_count}）——泄漏"
    )

    # busy_timeout 必须**生效**（读实际值），不是"PRAGMA 语句执行过"
    borrowed = pool.get_connection()
    try:
        actual = borrowed.execute("PRAGMA busy_timeout").fetchone()[0]
        assert int(actual) > 0, f"删除路径连接无有效 busy_timeout（实际 {actual}）"
    finally:
        pool.return_connection(borrowed)

    # 无注入时删除真实生效
    manager.remember(content="to-delete-2", id="del-me-2")
    manager._delete_persisted_memory("del-me-2")
    conn = sqlite3.connect(persist_db)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE id = ?", ("del-me-2",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0
