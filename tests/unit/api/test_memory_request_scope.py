"""记忆三层隔离请求作用域测试

审计修复 (docs/audit/three-tier-isolation-audit.md P0-1 / P1-6 / P1-7 / P2-11):
- 原 deps/base 的 get_memory_manager 直接给共享单例的只读 property
  (neuser_id/user_id) 赋值: base.py 吞 AttributeError 静默失效,
  deps.py 抛 500, 且多请求并发会互相覆盖隔离上下文。
- 根因修复: 隔离作用域通过 ContextVar 按请求上下文注入,
  不修改共享单例状态, 并发请求互不污染。
- DELETE 持久化必须带三层 WHERE, 防止跨用户越权删除。
- 自增 id 计数器必须跨作用域取全局最大值, 防止跨作用域 id 冲突被
  INSERT OR REPLACE 覆盖。
"""

import sqlite3

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


@pytest.fixture
def mgr(tmp_path):
    return MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")


@pytest.fixture(autouse=True)
def _clean_scope():
    """ContextVar 值在同一执行上下文中持久, 每个测试前清空防串扰"""
    from neurova.cognitive_layers.memory_layer import manager as _manager

    _manager._scope_var.set(None)
    yield
    _manager._scope_var.set(None)


def _persist_db(tmp_path) -> str:
    """持久化库与 db_path 同目录, 固定文件名 neurova_memories_persist.db"""
    return str(tmp_path / "neurova_memories_persist.db")


def _row_count(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    finally:
        conn.close()


class TestRequestScope:
    """ContextVar 请求作用域: 注入而非修改共享单例"""

    def test_set_request_scope_stamps_remember(self, mgr):
        mgr.set_request_scope(neuser_id="ne_1", user_id="u_1")
        mid = mgr.remember("hello scoped world")
        mem = mgr._memories[mid]
        assert mem.neuser_id == "ne_1"
        assert mem.user_id == "u_1"
        assert mem.agent_id == "agent_a"

    def test_request_scope_context_manager_restores(self, mgr):
        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            mid1 = mgr.remember("scoped memory")
        mid2 = mgr.remember("unscoped memory")
        assert mgr._memories[mid1].user_id == "u_1"
        assert mgr._memories[mid2].user_id == "default"

    def test_default_scope_unchanged(self, mgr):
        """无作用域时保持构造参数 (向后兼容: 存量数据均在 default 作用域)"""
        mid = mgr.remember("legacy path")
        mem = mgr._memories[mid]
        assert mem.neuser_id == "default"
        assert mem.user_id == "default"


class TestRecallIsolation:
    """recall 所有检索路径都必须按生效三元组过滤"""

    def test_keyword_path_isolated(self, mgr):
        """use_semantic=False 的关键词路径原实现完全不过滤用户 (隔离缺口)"""
        mgr.remember("topsecret alpha document")

        with mgr.request_scope(neuser_id="ne_2", user_id="u_2"):
            results = mgr.recall(query="topsecret", use_semantic=False, limit=10)
        assert results == []

    def test_semantic_path_enforces_neuser_layer(self, mgr):
        """语义路径原实现只过滤 agent+user, 漏掉 neuser 层"""
        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            mgr.remember("shared keyword alpha note")
        with mgr.request_scope(neuser_id="ne_2", user_id="u_1"):
            mgr.remember("shared keyword beta note")

        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            results = mgr.recall(query="shared keyword", limit=10)
        contents = [r["content"] for r in results]
        assert contents == ["shared keyword alpha note"]

    def test_get_crystallized_scoped(self, mgr):
        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            mgr.remember("my crystallized fact", is_crystallized=True)

        with mgr.request_scope(neuser_id="ne_2", user_id="u_2"):
            results = mgr.get_crystallized(limit=10)
        assert results == []

    def test_get_stats_scoped(self, mgr):
        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            mgr.remember("fact one")
        with mgr.request_scope(neuser_id="ne_2", user_id="u_2"):
            mgr.remember("fact two")

        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            assert mgr.get_stats()["total_memories"] == 1


class TestForgetOwnership:
    """forget 必须校验记忆归属, 防止知道 id 即可越权删除"""

    def test_forget_rejects_foreign_scope(self, mgr):
        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            mid = mgr.remember("owned memory")

        with mgr.request_scope(neuser_id="ne_2", user_id="u_2"):
            assert mgr.forget(mid) is False

        # 归属者仍可正常检索与删除
        with mgr.request_scope(neuser_id="ne_1", user_id="u_1"):
            assert mgr.recall(query="owned memory") != []
            assert mgr.forget(mid) is True

    def test_hard_delete_scoped_sql(self, tmp_path):
        """软删路径持久化按 id REPLACE 属于同一行, 无跨作用域问题;
        硬删路径的 DELETE 必须带三层 WHERE"""
        db_path = _persist_db(tmp_path)

        mgr_a = MemoryManager(db_path=str(tmp_path / "a.db"), agent_id="agent_a")
        with mgr_a.request_scope(neuser_id="ne_1", user_id="u_1"):
            mid_a = mgr_a.remember("a owns this", id="mem_900001")

        mgr_b = MemoryManager(db_path=str(tmp_path / "a.db"), agent_id="agent_a")
        with mgr_b.request_scope(neuser_id="ne_2", user_id="u_2"):
            # B 尝试硬删 A 的记忆: DELETE 带三层 WHERE 后应删不掉 A 的行
            mgr_b._delete_persisted_memory(mid_a)

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT neuser_id FROM memories WHERE id = ?", (mid_a,)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == "ne_1"


class TestPersistIdCollision:
    """id 计数器必须跨作用域取全局最大值, 防止跨作用域覆盖"""

    def test_new_scope_instance_does_not_reuse_id(self, tmp_path):
        db_path = _persist_db(tmp_path)

        mgr_a = MemoryManager(db_path=db_path, agent_id="agent_a")
        with mgr_a.request_scope(neuser_id="ne_1", user_id="u_1"):
            mid_a = mgr_a.remember("user one memory")

        # 新实例不同作用域: 不能生成与 A 相同的 id (否则 INSERT OR REPLACE 覆盖)
        mgr_b = MemoryManager(db_path=db_path, agent_id="agent_a")
        with mgr_b.request_scope(neuser_id="ne_2", user_id="u_2"):
            mid_b = mgr_b.remember("user two memory")

        assert mid_a != mid_b
        assert _row_count(db_path) == 2


class TestCompositeIndex:
    """三层复合索引 (P2-11): 隔离查询不再全表扫"""

    def test_idx_mem_3tier_exists(self, tmp_path):
        MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")
        db_path = _persist_db(tmp_path)

        conn = sqlite3.connect(db_path)
        try:
            indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(memories)").fetchall()
            }
        finally:
            conn.close()
        assert "idx_mem_3tier" in indexes
