"""S2 安全批：温度通道三层隔离（审计 2026-11-16 P1-14）。

`get_top_memories_by_temperature` 的 SQL 此前无 agent/neuser/user 三元组条件、
无 lifecycle_stage 条件——同 agent 库内任意登录用户可检索他人高温记忆原文，
已遗忘记忆也进 Top-N。修复在 SQL 生产侧补三元组 + 排除 forgotten，取出后仍经
`isOwnedByRequestScope` 唯一仲裁器仲裁（根因处修，不在端点补丁）。
"""

import sqlite3

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import (
    EmotionType,
    LifecycleStage,
    Memory,
    MemoryCategory,
    MemoryType,
)

AGENT = "agentA"


def _make_manager(tmp_path) -> MemoryManager:
    db_dir = tmp_path / "mem"
    db_dir.mkdir(exist_ok=True)
    mgr = MemoryManager.__new__(MemoryManager)
    mgr._db_path = str(db_dir / "memory.db")
    mgr._agent_id = AGENT
    mgr._neuser_id = "n1"
    mgr._user_id = "u1"
    mgr._init_persistence_db()
    return mgr


def _mem(mid, content, *, neuser, user, temperature, stage=LifecycleStage.ACTIVE, agent=AGENT):
    return Memory(
        id=mid,
        content=content,
        memory_type=MemoryType.SEMANTIC,
        category=MemoryCategory.GENERAL,
        lifecycle_stage=stage,
        emotion=EmotionType.NEUTRAL,
        temperature=temperature,
        agent_id=agent,
        neuser_id=neuser,
        user_id=user,
    )


class TestTemperatureChannelScope:
    def test_sql_filters_by_scope_triple_and_excludes_forgotten(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mine = _mem("m-mine", "mine-secret", neuser="n1", user="u1", temperature=80)
        other_high = _mem("m-other", "other-user-secret", neuser="n2", user="u2", temperature=99)
        forgotten = _mem(
            "m-forgotten", "forgotten-secret", neuser="n1", user="u1",
            temperature=98, stage=LifecycleStage.FORGOTTEN,
        )
        other_agent = _mem("m-cross", "cross-agent-secret", neuser="n1", user="u1",
                           temperature=97, agent="agentB")
        assert mgr.persist_memory_batch([mine, other_high, forgotten, other_agent])

        top = mgr.get_top_memories_by_temperature(10)
        ids = {r["id"] for r in top}
        assert ids == {"m-mine"}, (
            f"温度通道越界：{ids}——应只含本作用域 (agentA,n1,u1) 的未遗忘行"
        )
        contents = {r["content"] for r in top}
        assert "other-user-secret" not in contents, "他人记忆原文经温度通道泄漏"
        assert "forgotten-secret" not in contents, "已遗忘记忆经温度通道返回"
        assert "cross-agent-secret" not in contents, "跨 agent 记忆经温度通道返回"

    def test_limit_still_applies_within_scope(self, tmp_path):
        mgr = _make_manager(tmp_path)
        rows = [
            _mem(f"m{i}", f"c{i}", neuser="n1", user="u1", temperature=50 + i)
            for i in range(5)
        ]
        assert mgr.persist_memory_batch(rows)
        top = mgr.get_top_memories_by_temperature(2)
        assert len(top) == 2, f"limit 未生效：{len(top)}"
        temps = [r["temperature"] for r in top]
        assert temps == sorted(temps, reverse=True), f"未按温度降序：{temps}"

    def test_output_shape_unchanged_for_consumer(self, tmp_path):
        """消费方（neurova_recall._channel_temperature）只吃 id/content/temperature——
        修复不得改变输出键形状，也不得把作用域限定行的 \\x1f 前缀泄出去。"""
        mgr = _make_manager(tmp_path)
        assert mgr.persist_memory_batch([_mem("m1", "c1", neuser="n1", user="u1", temperature=70)])
        top = mgr.get_top_memories_by_temperature(5)
        assert top, "本作用域行应可取回"
        row = top[0]
        assert set(row.keys()) == {"id", "content", "temperature", "category", "lifecycle_stage", "metadata"}
        assert row["id"] == "m1", f"业务 id 不得带作用域前缀：{row['id']!r}"
