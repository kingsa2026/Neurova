"""
#4 SQLite 孤儿表删除测试

背景:
    neurova/memory/scripts/init_db.py 中定义了三张孤儿表:
    - sessions (line 76-87)
    - session_messages (line 90-101)
    - session_context_snapshots (line 104-113)

    以及 5 个相关索引 (line 431-435):
    - idx_sessions_agent_status
    - idx_sessions_user_active
    - idx_messages_session_seq
    - idx_messages_session_recent
    - idx_snapshots_lookup

    这三张表仅有 CREATE TABLE 语句,无任何 INSERT/SELECT/UPDATE/DELETE 代码引用。
    SessionManager 文件层已提供会话持久化(sessions/<agent_id>/session_<sid>_<date>.json)。
    auth_system.py 中的 sessions 表是认证会话表(token-based),与 chat session 无关,保留。

Deletion test:
    删除表定义后 complexity 消失(无代码引用) → pass-through,应删。
    不补全为 SqliteSessionRepository,因为会创造第二套持久化,违反单一存储抽象原则。

TDD RED 阶段:本测试在删除前应全部失败(确认表/索引仍存在)。
TDD GREEN 阶段:删除表定义 + 索引后,本测试应全部通过。
"""

import os
import sqlite3
import tempfile

import pytest

# init_db 模块路径
INIT_DB_PATH = os.path.join("neurova", "memory", "scripts", "init_db.py")


@pytest.fixture
def init_db_module():
    """加载 init_db 模块"""
    import importlib

    mod = importlib.import_module("neurova.memory.scripts.init_db")
    return mod


@pytest.fixture
def temp_db(tmp_path):
    """创建临时数据库并初始化"""
    db_path = str(tmp_path / "test_memory.db")
    yield db_path


# ---------------------------------------------------------------------------
# RED 测试:验证孤儿表已从 init_db.py 中删除
# ---------------------------------------------------------------------------


class TestOrphanTablesRemoved:
    """验证三张孤儿表的 CREATE TABLE 语句已从 init_db.py 中删除"""

    def test_init_db_source_no_sessions_table(self):
        """RED: init_db.py 不应包含 chat session 的 sessions 表定义

        注意:auth_system.py 中的 sessions 表是认证会话表,不在 init_db.py 中,
        所以 init_db.py 中所有 sessions 表定义都是孤儿表。
        """
        with open(INIT_DB_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # 不应包含 CREATE TABLE IF NOT EXISTS sessions
        assert "CREATE TABLE IF NOT EXISTS sessions (" not in content, (
            "#4 失败:init_db.py 仍包含孤儿表 sessions 的 CREATE TABLE 定义"
        )

    def test_init_db_source_no_session_messages_table(self):
        """RED: init_db.py 不应包含 session_messages 表定义"""
        with open(INIT_DB_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        assert "CREATE TABLE IF NOT EXISTS session_messages (" not in content, (
            "#4 失败:init_db.py 仍包含孤儿表 session_messages 的 CREATE TABLE 定义"
        )

    def test_init_db_source_no_session_context_snapshots_table(self):
        """RED: init_db.py 不应包含 session_context_snapshots 表定义"""
        with open(INIT_DB_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        assert "CREATE TABLE IF NOT EXISTS session_context_snapshots (" not in content, (
            "#4 失败:init_db.py 仍包含孤儿表 session_context_snapshots 的 CREATE TABLE 定义"
        )


class TestOrphanIndexesRemoved:
    """验证 5 个孤儿索引已从 init_db.py 中删除

    注意:只检查 CREATE INDEX 语句,允许注释中保留索引名(用于代码考古)。
    """

    ORPHAN_INDEX_NAMES = [
        "idx_sessions_agent_status",
        "idx_sessions_user_active",
        "idx_messages_session_seq",
        "idx_messages_session_recent",
        "idx_snapshots_lookup",
    ]

    def test_init_db_source_no_orphan_indexes(self):
        """RED: init_db.py 不应包含孤儿索引的 CREATE INDEX 语句"""
        with open(INIT_DB_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        for idx_name in self.ORPHAN_INDEX_NAMES:
            # 只检查 CREATE INDEX 语句,允许注释中保留索引名
            create_pattern = f"CREATE INDEX IF NOT EXISTS {idx_name}"
            assert create_pattern not in content, (
                f"#4 失败:init_db.py 仍包含孤儿索引的 CREATE INDEX 语句: {idx_name}"
            )


# ---------------------------------------------------------------------------
# RED 测试:验证运行 init_db 后,SQLite 数据库中不存在孤儿表
# ---------------------------------------------------------------------------


class TestOrphanTablesNotCreated:
    """验证运行 init_db 后,SQLite 数据库中不创建孤儿表"""

    def test_init_db_creates_no_sessions_table(self, init_db_module, temp_db):
        """RED: 运行 init_db 后,sessions 表不应存在于 SQLite 数据库"""
        init_db_module.init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        )
        tables = cursor.fetchall()
        conn.close()

        assert len(tables) == 0, (
            f"#4 失败:运行 init_db 后仍创建了 sessions 表(应为孤儿表已删除): {tables}"
        )

    def test_init_db_creates_no_session_messages_table(self, init_db_module, temp_db):
        """RED: 运行 init_db 后,session_messages 表不应存在"""
        init_db_module.init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_messages'"
        )
        tables = cursor.fetchall()
        conn.close()

        assert len(tables) == 0, (
            f"#4 失败:运行 init_db 后仍创建了 session_messages 表: {tables}"
        )

    def test_init_db_creates_no_session_context_snapshots_table(self, init_db_module, temp_db):
        """RED: 运行 init_db 后,session_context_snapshots 表不应存在"""
        init_db_module.init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_context_snapshots'"
        )
        tables = cursor.fetchall()
        conn.close()

        assert len(tables) == 0, (
            f"#4 失败:运行 init_db 后仍创建了 session_context_snapshots 表: {tables}"
        )

    def test_init_db_creates_no_orphan_indexes(self, init_db_module, temp_db):
        """RED: 运行 init_db 后,5 个孤儿索引不应存在"""
        init_db_module.init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name IN "
            "('idx_sessions_agent_status', 'idx_sessions_user_active', "
            "'idx_messages_session_seq', 'idx_messages_session_recent', 'idx_snapshots_lookup')"
        )
        indexes = cursor.fetchall()
        conn.close()

        assert len(indexes) == 0, (
            f"#4 失败:运行 init_db 后仍创建了孤儿索引: {indexes}"
        )


# ---------------------------------------------------------------------------
# GREEN 守卫:验证非孤儿表(应保留)不受影响
# ---------------------------------------------------------------------------


class TestNonOrphanTablesPreserved:
    """验证非孤儿表(memories, memory_emotions, users 等)不受影响"""

    def test_init_db_still_creates_memories_table(self, init_db_module, temp_db):
        """GREEN 守卫:memories 主表应仍然被创建"""
        init_db_module.init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
        )
        tables = cursor.fetchall()
        conn.close()

        assert len(tables) == 1, (
            f"GREEN 守卫失败:memories 主表应被创建,但实际: {tables}"
        )

    def test_init_db_still_creates_memory_emotions_table(self, init_db_module, temp_db):
        """GREEN 守卫:memory_emotions 副表应仍然被创建"""
        init_db_module.init_db(temp_db)

        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_emotions'"
        )
        tables = cursor.fetchall()
        conn.close()

        assert len(tables) == 1, (
            f"GREEN 守卫失败:memory_emotions 副表应被创建,但实际: {tables}"
        )
