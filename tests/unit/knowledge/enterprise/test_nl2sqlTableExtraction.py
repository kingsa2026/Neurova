# -*- coding: utf-8 -*-
"""KNOW-07：NL2SQL 表名审计收集全部表引用，解析不完整即拒绝。

审计定位（全仓逐文件审计报告 2026-11-25 §6 KNOW-07）：仅正则提取简单
FROM/JOIN 标识符——逗号表、引号、方括号、反引号表名不会被完整收集，
可能访问目录外表。判据：方言解析器（sqlglot，仓内既有依赖）收集全部表引用；
无法完整解析的 SQL 在只读闸显式拒绝；CTE 别名不得误报为目录外表。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.enterprise.nl2sql import Nl2SqlService, tablesInSql

_TABLES = {"orders": {}, "customers": {}}


class TestTableExtraction:
    def test_commaSeparatedTablesAllCollected(self):
        """FROM a, b：两表都必须被收集（旧正则只收第一个）。"""
        tables = tablesInSql("SELECT * FROM orders, secrets LIMIT 5")
        assert set(tables) == {"orders", "secrets"}

    def test_quotedAndBacktickTablesCollected(self):
        """引号/反引号表名照常解析成目录键。"""
        assert tablesInSql('SELECT * FROM "orders" LIMIT 5') == ["orders"]
        assert tablesInSql("SELECT * FROM `orders` LIMIT 5") == ["orders"]

    def test_subqueryTablesCollected(self):
        """子查询里的外表也在收集范围。"""
        assert tablesInSql("SELECT * FROM (SELECT * FROM secrets) s LIMIT 5") \
            == ["secrets"]

    def test_cteAliasNotTreatedAsCatalogTable(self):
        """CTE 别名不是目录表：不得把 x 报成目录外表，真表 orders 要收集。"""
        sql = "WITH x AS (SELECT * FROM orders) SELECT * FROM x LIMIT 5"
        assert tablesInSql(sql) == ["orders"]

    def test_schemaQualifiedKept(self):
        """两段式限定名与旧口径一致（dbo.orders 整体进白名单比对）。"""
        assert tablesInSql("SELECT * FROM dbo.orders o LIMIT 5") == ["dbo.orders"]


class TestReadonlyGateRejects:
    def test_commaSeparatedOutOfCatalogRejected(self):
        """逗号表绕过面被封：第二个外表必须被拒。"""
        with pytest.raises(ValueError, match="目录外表"):
            Nl2SqlService._validateSql(
                "SELECT * FROM orders, secrets LIMIT 5", _TABLES, 200)

    def test_unparseableSqlRejected(self):
        """解析不完整即拒绝（不给正则粗提兜底过闸）。"""
        with pytest.raises(ValueError, match="完整解析"):
            Nl2SqlService._validateSql("SELECT FROM WHERE o", _TABLES, 200)

    def test_bracketedNameCollectedAndGated(self):
        """方括号名（T-SQL 方言）也要被收集并进白名单比对：本表放行、外表拒绝。"""
        assert tablesInSql("SELECT * FROM [orders] LIMIT 5") == ["orders"]
        with pytest.raises(ValueError, match="目录外表"):
            Nl2SqlService._validateSql(
                "SELECT * FROM [secrets] LIMIT 5", _TABLES, 200)

    def test_cteOverCatalogTableStillPasses(self):
        """CTE 包住目录表的合法形状照常过闸（别名不误报外表）。"""
        Nl2SqlService._validateSql(
            "WITH x AS (SELECT * FROM orders) SELECT * FROM x LIMIT 5",
            _TABLES, 200)
