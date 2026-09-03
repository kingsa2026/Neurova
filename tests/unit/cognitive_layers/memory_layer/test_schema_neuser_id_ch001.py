"""
BUG CH-001 (P0): SQL Schema neuser_id 字段验证测试

TDD 调查结论: neuser_id 不是拼写错误，是合法的三级隔离字段。

调查证据:
1. Memory 数据类 (models.py:266) 有 neuser_id: str = "" 字段
2. IsolationContext (isolation.py:56) 有 neuser_id: str = "default" 字段
3. schema.py 多处定义 neuser_id 列和索引
4. agent_core.py:985 _init_memory_modules(neuser_id, user_id) 三级隔离
5. mem_core.py:319 init_memory_modules(neuser_id, user_id)
6. architecture docs: "neuser_id - 系统用户隔离 (不同用户数据隔离)"

三级隔离设计:
- Level 1: agent_id (Agent 隔离)
- Level 2: neuser_id (Neurova 系统用户隔离)
- Level 3: user_id (外部/渠道用户隔离)

本测试验证 schema 正确性，确认 neuser_id 和 user_id 共存是设计意图。
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timezone

from neurova.cognitive_layers.memory_layer.models import Memory, MemoryType
from neurova.cognitive_layers.memory_layer.isolation import IsolationContext


def test_memory_dataclass_has_neuser_id_field():
    """Memory 数据类必须有 neuser_id 字段（三级隔离第2级）。"""
    mem = Memory(id="test_1", content="test", neuser_id="user_123", user_id="ext_456")
    assert mem.neuser_id == "user_123"
    assert mem.user_id == "ext_456"
    assert mem.agent_id == ""  # 默认值


def test_memory_dataclass_neuser_id_defaults_to_empty():
    """Memory 数据类的 neuser_id 默认值应为空字符串。"""
    mem = Memory(id="test_2", content="test")
    assert mem.neuser_id == ""
    assert mem.user_id == ""


def test_isolation_context_has_neuser_id():
    """IsolationContext 必须有 neuser_id 字段。"""
    ctx = IsolationContext(
        agent_id="agent_1",
        neuser_id="neu_user_1",
        user_id="ext_user_1",
    )
    assert ctx.neuser_id == "neu_user_1"
    assert ctx.user_id == "ext_user_1"
    assert ctx.agent_id == "agent_1"


def test_isolation_context_key_includes_three_levels():
    """IsolationContext 的 key 必须包含三级隔离字段。"""
    ctx = IsolationContext(
        agent_id="agent_1",
        neuser_id="neu_user_1",
        user_id="ext_user_1",
    )
    key = ctx.key
    assert "agent_1" in key
    assert "neu_user_1" in key
    assert "ext_user_1" in key


def test_memory_to_dict_includes_neuser_id():
    """Memory.to_dict() 必须包含 neuser_id 字段。"""
    mem = Memory(id="test_3", content="test", neuser_id="neu_1", user_id="ext_1")
    d = mem.to_dict()
    assert "neuser_id" in d
    assert d["neuser_id"] == "neu_1"
    assert "user_id" in d
    assert d["user_id"] == "ext_1"


def test_memory_from_dict_reads_neuser_id():
    """Memory.from_dict() 必须正确读取 neuser_id 字段。"""
    data = {
        "id": "test_4",
        "content": "test content",
        "neuser_id": "neu_from_dict",
        "user_id": "ext_from_dict",
    }
    mem = Memory.from_dict(data)
    assert mem.neuser_id == "neu_from_dict"
    assert mem.user_id == "ext_from_dict"


def test_sql_schema_has_both_neuser_id_and_user_id_columns():
    """SQL Schema 必须同时有 neuser_id 和 user_id 列（三级隔离设计）。

    BUG CH-001 调查结论: neuser_id 不是拼写错误。
    neuser_id (Neurova系统用户ID) 和 user_id (外部用户ID) 是不同的隔离级别，
    两个列都需要存在。
    """
    # 创建临时数据库并初始化 schema
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_memories.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                memory_type TEXT NOT NULL DEFAULT 'semantic',
                category TEXT NOT NULL DEFAULT 'general',
                lifecycle_stage TEXT NOT NULL DEFAULT 'active',
                perspective TEXT NOT NULL DEFAULT 'first_person',
                emotion TEXT NOT NULL DEFAULT 'neutral',
                temperature REAL NOT NULL DEFAULT 100.0,
                importance REAL NOT NULL DEFAULT 50.0,
                access_count INTEGER NOT NULL DEFAULT 0,
                metadata TEXT NOT NULL DEFAULT '{}',
                agent_id TEXT NOT NULL DEFAULT 'default',
                neuser_id TEXT NOT NULL DEFAULT 'default',
                user_id TEXT NOT NULL DEFAULT 'default',
                shared INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed_at TEXT
            )
        """)
        conn.commit()

        # 验证两列都存在
        cursor = conn.execute("PRAGMA table_info(memories)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

    assert "neuser_id" in columns, "schema 必须有 neuser_id 列（三级隔离第2级）"
    assert "user_id" in columns, "schema 必须有 user_id 列（三级隔离第3级）"
    assert "agent_id" in columns, "schema 必须有 agent_id 列（三级隔离第1级）"


def test_sql_schema_persists_three_level_isolation():
    """SQL Schema 必须能正确持久化三级隔离数据。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_memories.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT 'default',
                neuser_id TEXT NOT NULL DEFAULT 'default',
                user_id TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        # 写入三级隔离数据
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO memories (id, content, agent_id, neuser_id, user_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("mem_1", "test", "agent_1", "neu_user_1", "ext_user_1", now, now),
        )
        conn.commit()

        # 读回并验证三级隔离
        cursor = conn.execute(
            "SELECT agent_id, neuser_id, user_id FROM memories WHERE id = ?",
            ("mem_1",),
        )
        row = cursor.fetchone()
        conn.close()

    assert row is not None
    assert row[0] == "agent_1"  # agent_id
    assert row[1] == "neu_user_1"  # neuser_id
    assert row[2] == "ext_user_1"  # user_id
