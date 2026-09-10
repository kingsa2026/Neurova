"""M-25 回归测试：自定义 id 跨作用域持久化互踩。

根因：memories 表 id 为全表主键，_PERSIST_UPSERT_SQL 用
`INSERT OR REPLACE` 按 id 覆盖 —— A 作用域自定义 id 的记忆会被
B 作用域同 id 的 INSERT OR REPLACE 直接覆盖（重启后丢数据）。

修复后契约（作用域限定持久化键，向后兼容）：
- upsert 改为 ON CONFLICT(id) DO UPDATE ... WHERE 作用域三元组匹配；
  跨作用域冲突不覆盖，落为带作用域前缀（\\x1f 分隔）的行 id；
- 读路径（_load_from_db / get_top_memories_by_temperature）剥前缀还原
  业务 id，无前缀旧行原样可读；
- 删除同时命中普通行与作用域限定行。
"""

import sqlite3

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager

CUSTOM_ID = "shared-custom-1"
SEP = "\x1f"


@pytest.fixture()
def db_dir(tmp_path):
    d = tmp_path / "m25"
    d.mkdir()
    return d


def _make_manager(db_dir, user_id):
    return MemoryManager(
        db_path=str(db_dir / "mem.db"),
        agent_id="m25-agent",
        neuser_id="neu",
        user_id=user_id,
    )


def _persist_path(db_dir):
    return str(db_dir / "neurova_memories_persist.db")


def _count_rows(db_dir):
    conn = sqlite3.connect(_persist_path(db_dir))
    try:
        return {
            row[0]: row[1]
            for row in conn.execute("SELECT id, content FROM memories").fetchall()
        }
    finally:
        conn.close()


class TestM25ScopeQualifiedPersistKey:
    def test_cross_scope_same_custom_id_no_data_loss(self, db_dir):
        mgr_a = _make_manager(db_dir, user_id="userA")
        mgr_b = _make_manager(db_dir, user_id="userB")

        mgr_a.remember(content="A-document", id=CUSTOM_ID)
        mgr_b.remember(content="B-document", id=CUSTOM_ID)

        rows = _count_rows(db_dir)
        contents = set(rows.values())
        assert contents == {"A-document", "B-document"}, (
            f"跨作用域同 id 覆盖丢数据，持久层内容: {rows}"
        )
        # B 的行应带作用域限定前缀，A 的行保持业务原 id
        plain_keys = [k for k in rows if SEP not in k]
        assert plain_keys == [CUSTOM_ID]

    def test_reload_both_scopes_restore_plain_ids(self, db_dir):
        mgr_a = _make_manager(db_dir, user_id="userA")
        mgr_b = _make_manager(db_dir, user_id="userB")
        mgr_a.remember(content="A-document", id=CUSTOM_ID)
        mgr_b.remember(content="B-document", id=CUSTOM_ID)

        a2 = _make_manager(db_dir, user_id="userA")
        b2 = _make_manager(db_dir, user_id="userB")

        got_a = a2.get_memory(CUSTOM_ID)
        got_b = b2.get_memory(CUSTOM_ID)
        assert got_a is not None and got_a["content"] == "A-document"
        assert got_b is not None and got_b["content"] == "B-document"
        # 载入内存的业务 id 不带前缀
        assert CUSTOM_ID in a2._memories and CUSTOM_ID in b2._memories

    def test_hard_delete_cleans_scoped_row(self, db_dir):
        mgr_a = _make_manager(db_dir, user_id="userA")
        mgr_b = _make_manager(db_dir, user_id="userB")
        mgr_a.remember(content="A-document", id=CUSTOM_ID)
        mgr_b.remember(content="B-document", id=CUSTOM_ID)

        assert mgr_b.forget(CUSTOM_ID, soft=False) is True
        rows = _count_rows(db_dir)
        assert "B-document" not in rows.values(), "作用域限定行删除失败"
        assert rows[CUSTOM_ID] == "A-document", "A 作用域数据不应被波及"

    def test_top_memories_strips_scoped_prefix(self, db_dir):
        mgr_a = _make_manager(db_dir, user_id="userA")
        mgr_b = _make_manager(db_dir, user_id="userB")
        mgr_a.remember(content="A-document", id=CUSTOM_ID, temperature=60.0)
        mgr_b.remember(content="B-document", id=CUSTOM_ID, temperature=70.0)

        for mgr in (mgr_a, mgr_b):
            top = mgr.get_top_memories_by_temperature(limit=10)
            ids = [r["id"] for r in top if r["content"] in ("A-document", "B-document")]
            # 裸表读取按行返回（两作用域各一行是预期），但 id 必须已剥前缀
            assert set(ids) == {CUSTOM_ID} and all(SEP not in i for i in ids), (
                f"Top-N 读路径泄漏作用域前缀 id: {ids}"
            )

    def test_same_scope_updates_still_land_in_place(self, db_dir):
        mgr_a = _make_manager(db_dir, user_id="userA")
        mgr_a.remember(content="v1", id="scope-a-only")
        mgr_a.remember(content="v2", id="scope-a-only")
        rows = _count_rows(db_dir)
        assert rows["scope-a-only"] == "v2", "同作用域重复 upsert 未原位更新"
        assert len(rows) == 1, f"同作用域更新产生重复行: {rows}"
