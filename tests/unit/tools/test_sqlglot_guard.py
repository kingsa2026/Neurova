# -*- coding: utf-8 -*-
"""sqlglot AST 复核与表名审计（query_database 纵深防御 + 审计读数）。

现有只读闸（head 白名单 + EXPLAIN 干跑授权器）已覆盖 SQLite 写语句拦截，
本批补两件**增量**，不另造第二把拦截尺：

1. `astReadOnlyCheck`：AST 前置复核（纵深防御——白名单/干跑判据将来漂移时
   的第二道网）；解析失败一律返回 None 放行，语法错误由干跑与真实执行诚实报，
   不因 sqlglot 解析不动而误杀；
2. `extractSqlTables`：表名审计——query_database 的 SQL 查询返回
   `tables_accessed`，动了哪些表有账可查。
"""

from __future__ import annotations

import sqlite3

import pytest

from neurova.attachment_dataset import (
    assertReadOnlySql,
    astReadOnlyCheck,
    extractSqlTables,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT)")
    c.execute("CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, action TEXT)")
    yield c
    c.close()


class TestAstReadOnlyCheck:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM memories",
            "SELECT content FROM memories WHERE id = 1",
            "WITH recent AS (SELECT * FROM memories) SELECT * FROM recent",
            "SELECT * FROM memories UNION SELECT * FROM memories",
            "PRAGMA table_info(memories)",
        ],
    )
    def test_readStatementsPass(self, sql):
        assert astReadOnlyCheck(sql) is None, sql

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO memories (content) VALUES ('x')",
            "UPDATE memories SET content = 'x'",
            "DELETE FROM memories",
            "DROP TABLE memories",
            "DROP TABLE audit_logs",
            "CREATE TABLE evil (id INTEGER)",
            "ALTER TABLE memories ADD COLUMN hack TEXT",
            "ATTACH DATABASE 'evil.db' AS evil",
            "DETACH DATABASE evil",
            "VACUUM",
        ],
    )
    def test_writeStatementsRejected(self, sql):
        verdict = astReadOnlyCheck(sql)
        assert verdict is not None, f"写语句必须被 AST 复核点名: {sql}"
        assert sql.split()[0].upper() in verdict.upper() or "写" in verdict or "不允许" in verdict, verdict

    def test_unparseablePassesThrough(self):
        """解析不动的语句返回 None 放行——语法错误由干跑与真实执行诚实报。"""
        assert astReadOnlyCheck("SELCT nonsense ///") is None
        assert astReadOnlyCheck("") is None
        assert astReadOnlyCheck(None) is None


class TestExtractSqlTables:
    def test_simpleSelect(self):
        assert extractSqlTables("SELECT * FROM memories") == ["memories"]

    def test_join(self):
        tables = extractSqlTables(
            "SELECT * FROM memories m JOIN audit_logs a ON m.id = a.id"
        )
        assert tables == ["audit_logs", "memories"], "去重排序，审计读数稳定"

    def test_cteExtractsBaseTablesOnly(self):
        tables = extractSqlTables(
            "WITH recent AS (SELECT * FROM memories) SELECT * FROM recent"
        )
        assert tables == ["memories"], "CTE 别名不是表，只计基表"

    def test_subquery(self):
        tables = extractSqlTables(
            "SELECT * FROM memories WHERE id IN (SELECT id FROM audit_logs)"
        )
        assert tables == ["audit_logs", "memories"]

    def test_unparseableReturnsEmpty(self):
        assert extractSqlTables("SELCT ///") == []
        assert extractSqlTables("") == []
        assert extractSqlTables(None) == []


class TestAssertReadOnlySqlRegression:
    """sqlglot 复核并入后，既有白名单行为必须零变化（回归钉）。"""

    def test_selectPassesAndReturnsOriginal(self, conn):
        sql = "SELECT * FROM memories"
        assert assertReadOnlySql(sql, conn) == sql

    def test_dropRejected(self, conn):
        with pytest.raises(ValueError, match="只读"):
            assertReadOnlySql("DROP TABLE memories", conn)

    def test_multiStatementRejected(self, conn):
        with pytest.raises(ValueError, match="多语句"):
            assertReadOnlySql("SELECT 1; DROP TABLE memories", conn)

    def test_writePragmaRejected(self, conn):
        with pytest.raises(ValueError):
            assertReadOnlySql("PRAGMA journal_mode = WAL", conn)

    def test_emptyRejected(self, conn):
        with pytest.raises(ValueError, match="不能为空"):
            assertReadOnlySql("   ", conn)
