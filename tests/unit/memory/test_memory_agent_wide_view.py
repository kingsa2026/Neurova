"""
TDD Red:记忆管理与浏览视口按 agent 级隔离（agent_id 为边界）

背景（2026-09-03 线上）: /agent/default/memory 记忆列表为空,但 persist 库
实际有 67 条。根因: 管理/浏览口径被三元组(agent+neuser+user)拦截 ——
登录用户 scope 代入后, 归属 owner='default' 的历史记忆全部不可见。

契约:
1. 浏览/管理读路径(recall/stats/hot/crystallized/get_memory/forget)新增
   agent_wide 视图: 仅按实例绑定的 agent_id 过滤(页面按 agent 隔离)
2. 聊天检索默认路径保持三层隔离不变(防跨用户泄漏)
3. 快照加载(_load_from_db)按 agent 全量, 视图层再按口径过滤

当前实现: agent_wide 参数不存在 + _load_from_db 仅加载默认三元组 → 全红。
"""
import sqlite3
from datetime import UTC, datetime

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

ISO = lambda v: v.isoformat()  # noqa: E731


def _insert(conn, mid, neuser, user, lifecycle="active", temp=100.0, crystallized=False):
    if crystallized:
        lifecycle = "crystallized"
    conn.execute(
        "INSERT INTO memories (id, content, memory_type, category, lifecycle_stage,"
        " perspective, emotion, temperature, importance, access_count, metadata,"
        " agent_id, neuser_id, user_id, shared, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            mid,
            f"content-{mid}",
            "semantic",
            "general",
            lifecycle,
            "first_person",
            "neutral",
            temp,
            50.0,
            0,
            "{}",
            "default",
            neuser,
            user,
            0,
            ISO(datetime(2026, 9, 1, tzinfo=UTC)),
            ISO(datetime(2026, 9, 1, tzinfo=UTC)),
        ),
    )


@pytest.fixture
def manager(tmp_path):
    db_path = str(tmp_path / "memory.db")
    mgr = MemoryManager(
        db_path=db_path,
        agent_id="default",
        neuser_id="default",
        user_id="default",
    )
    conn = sqlite3.connect(str(tmp_path / "neurova_memories_persist.db"))
    _insert(conn, "mem_default_1", "default", "default")
    _insert(conn, "mem_default_2", "default", "default")
    _insert(conn, "mem_user7", "7", "7", temp=90.0)
    _insert(conn, "mem_user7_forgotten", "7", "7", lifecycle="forgotten")
    _insert(conn, "mem_user7_crystal", "7", "7", crystallized=True)
    conn.commit()
    conn.close()
    mgr._load_from_db()
    # 模拟登录用户 scope（页面带 token 时的注入值）
    mgr.set_request_scope(neuser_id="7", user_id="7")
    return mgr


class TestAgentWideViews:
    def test_snapshot_loads_all_agent_memories(self, manager):
        # 快照口径 = agent 全量, 与视图层过滤分离
        assert len(manager._memories) == 5

    def test_recall_agent_wide_returns_all_non_forgotten(self, manager):
        results = manager.recall(limit=20, agent_wide=True)
        ids = {m["id"] for m in results}
        assert ids == {"mem_default_1", "mem_default_2", "mem_user7", "mem_user7_crystal"}

    def test_recall_default_keeps_three_layer_isolation(self, manager):
        # 聊天检索默认路径: scope=7 只能看到 user 7 域(foegotten 排除)
        results = manager.recall(limit=20)
        ids = {m["id"] for m in results}
        assert ids == {"mem_user7", "mem_user7_crystal"}

    def test_stats_agent_wide_counts_all(self, manager):
        assert manager.get_stats(agent_wide=True)["total_memories"] == 5
        assert manager.get_stats()["total_memories"] == 3

    def test_get_memory_agent_wide_cross_user(self, manager):
        assert manager.get_memory("mem_default_1", agent_wide=True) is not None
        assert manager.get_memory("mem_default_1") is None

    def test_forget_agent_wide_cross_user(self, manager):
        assert manager.forget("mem_default_1", agent_wide=True) is True
        assert manager.forget("mem_default_2") is False

    def test_hot_agent_wide_includes_cross_user(self, manager):
        ids = {m["id"] for m in manager.get_hot_memories(limit=20, min_temperature=0, agent_wide=True)}
        assert "mem_default_1" in ids

    def test_crystallized_agent_wide_includes_cross_user(self, manager):
        ids = {m["id"] for m in manager.get_crystallized(limit=20, agent_wide=True)}
        assert "mem_user7_crystal" in ids
