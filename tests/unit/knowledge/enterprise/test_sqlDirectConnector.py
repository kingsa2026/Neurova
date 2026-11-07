# -*- coding: utf-8 -*-
"""批 C4：数据库直连适配器（2026-11-07 裁定 §2.4-1「直接做」，依赖豁免已登记）。

判据（立项方案 §3-C4）：全部假 connection/cursor 夹具（CI 零驱动依赖、零网络）——
- 驱动缺失 → health() 显式 error 点名 "driver not installed: <module>"，构造期不炸；
- 游标水位推进（首轮全量快照无 WHERE；此后 WHERE col > 水位，nextCursor=本批最大值）；
- 写意图（任何非只读形状）显式 MappingError，不静默；
- 凭据不落日志（caplog 断言）也不落描述符；
- describeSchema 每驱动一段目录查询推 columns；
- sqlite 驱动用真实旁库文件端到端（stdlib sqlite3，零网络），含 runOnce→admission 全链；
- 四网络驱动各一条「假连接走完 fetchBatch 全链」格（证明适配层不依赖真库）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
import types

import pytest

from neurova.knowledge.enterprise.connectors_sql import (
    DriverNotInstalledError,
    SqlDirectAdapter,
)
from neurova.knowledge.enterprise.protocols import SourceCursor
from neurova.knowledge.enterprise.schema_mapping import MappingError


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _sqlCredentials(monkeypatch):
    """凭据走环境变量（值不进描述符——正是被测纪律）。"""
    monkeypatch.setenv("SQL_USER", "kuai")
    monkeypatch.setenv("SQL_PASS", "s3cret-pw")


# ── 假 DBAPI 面（零真实驱动、零网络）─────────────────────────────────

class FakeCursor:
    def __init__(self, description=None, rows=None):
        self.description = description or []
        self._rows = list(rows or [])
        self.executed = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, tuple(params) if params is not None else None))

    def fetchall(self):
        return list(self._rows)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, cursors=None):
        self._cursors = list(cursors or [])
        self.closed = False

    def cursor(self):
        if not self._cursors:
            raise AssertionError("假连接游标已用尽（夹具编排错误）")
        return self._cursors.pop(0)

    def close(self):
        self.closed = True


class FakeDriver(types.ModuleType):
    """惰性 import 命中的假驱动模块：connect 出队一个假连接。"""

    def __init__(self, name, connections):
        super().__init__(name)
        self._connections = list(connections)
        self.connectCalls = []

    def connect(self, *args, **kwargs):
        self.connectCalls.append(kwargs if kwargs else args)
        if not self._connections:
            raise AssertionError("假驱动连接已用尽（夹具编排错误）")
        return self._connections.pop(0)


class BoomDriver(FakeDriver):
    """connect 即炸的假驱动（异常文本故意夹带口令——验证打码纪律）。"""

    def connect(self, *args, **kwargs):
        raise RuntimeError("connect failed host=db.internal password=s3cret-pw")


def _installDriver(monkeypatch, name, connections):
    driver = FakeDriver(name, connections)
    monkeypatch.setitem(sys.modules, name, driver)
    return driver


_ORDER_DESCRIPTION = [("order_id",), ("status",)]


def _pgDescriptor(**overrides):
    descriptor = {
        "sourceId": "pg_orders", "tenantId": "default", "sourceType": "sql",
        "driver": "postgresql",
        "host": "db.internal", "port": 5432, "database": "erp",
        "table": "orders", "cursorColumn": "order_id",
        "columns": ["order_id", "status"],
        "credentialEnv": {"user": "SQL_USER", "password": "SQL_PASS"},
        "subject": {"template": "order:{order_id}"},
        "predicate": {"termId": "has_status"},
        "object": {"column": "status", "kind": "column"},
        "qualifiers": {}, "enabled": True, "agentId": "default",
    }
    descriptor.update(overrides)
    return descriptor


class TestWatermarkFetch:
    def test_firstBatchFullSnapshotThenWatermarkIncrement(self, monkeypatch):
        first_cursor = FakeCursor(_ORDER_DESCRIPTION,
                                  [(42, "open"), (43, "closed"), (44, "open")])
        second_cursor = FakeCursor(_ORDER_DESCRIPTION, [(45, "open")])
        _installDriver(monkeypatch, "psycopg2",
                       [FakeConnection([first_cursor]), FakeConnection([second_cursor])])
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")

        first = _run(adapter.fetchBatch(None, 2))
        sql, params = first_cursor.executed[0]
        assert "WHERE" not in sql, "空游标＝首轮全量快照，无 WHERE"
        assert params == (3,), "绑定上限＝limit+1（多取一行判 hasMore）"
        assert [r["order_id"] for r in first.rows] == [42, 43], "批裁到 limit"
        assert first.hasMore is True
        assert first.nextCursor.token == "wm=43", "nextCursor=本批最大水位（json 编码）"

        second = _run(adapter.fetchBatch(first.nextCursor, 2))
        sql, params = second_cursor.executed[0]
        assert "order_id > %s" in sql, "水位增量：WHERE col > 水位"
        assert params[0] == 43 and params[1] == 3
        assert [r["order_id"] for r in second.rows] == [45]
        assert second.hasMore is False

    def test_emptyCursorTokenMeansFullSnapshot(self, monkeypatch):
        cursor = FakeCursor(_ORDER_DESCRIPTION, [(42, "open")])
        _installDriver(monkeypatch, "psycopg2", [FakeConnection([cursor])])
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")
        batch = _run(adapter.fetchBatch(SourceCursor(""), 2))
        assert "WHERE" not in cursor.executed[0][0]
        assert [r["order_id"] for r in batch.rows] == [42]

    def test_unparseableCursorFallsBackToFullSnapshot(self, monkeypatch, caplog):
        cursor = FakeCursor(_ORDER_DESCRIPTION, [(42, "open")])
        _installDriver(monkeypatch, "psycopg2", [FakeConnection([cursor])])
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")
        with caplog.at_level(logging.DEBUG,
                             logger="neurova.knowledge.enterprise.connectors_sql"):
            batch = _run(adapter.fetchBatch(SourceCursor("fp=abc:off=2"), 2))
        assert "WHERE" not in cursor.executed[0][0], \
            "不可解析游标回退全量快照（幂等由咽喉内容键兜底）"
        assert "回退全量快照" in caplog.text

    def test_stringWatermarkRoundTripKeepsType(self, monkeypatch):
        first_cursor = FakeCursor(_ORDER_DESCRIPTION,
                                  [("42", "open"), ("43", "closed"), ("44", "open")])
        second_cursor = FakeCursor(_ORDER_DESCRIPTION, [("45", "open")])
        _installDriver(monkeypatch, "psycopg2",
                       [FakeConnection([first_cursor]), FakeConnection([second_cursor])])
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")

        first = _run(adapter.fetchBatch(None, 2))
        assert first.nextCursor.token == 'wm="43"', "文本水位 json 编码带引号，类型不漂"
        second = _run(adapter.fetchBatch(first.nextCursor, 2))
        assert second_cursor.executed[0][1][0] == "43", "水位解码回文本，比较参数不带引号"


class TestWriteIntentRejection:
    @pytest.mark.parametrize("bad", [
        "INSERT INTO orders VALUES (1)",
        "DELETE FROM orders WHERE id = 1",
        "UPDATE orders SET status = 'x'",
        "DROP TABLE orders",
        "TRUNCATE TABLE orders",
        "ALTER TABLE orders ADD x",
        "CREATE TABLE t (a int)",
        "ATTACH DATABASE 'side.db' AS side",
        "PRAGMA journal_mode = WAL",
        "REPLACE INTO orders VALUES (1)",
        "SELECT * FROM orders; DROP TABLE orders",
        "SELECT * FROM orders WHERE id > 1 -- 注释拼接",
        "WITH w AS (SELECT 1 FROM orders) INSERT INTO orders SELECT * FROM w",
    ])
    def test_writeShapesRejectedExplicitly(self, bad):
        with pytest.raises(MappingError):
            SqlDirectAdapter(_pgDescriptor(query=bad), "pg_orders", "default")

    def test_queryMissingLimSlotRejected(self):
        with pytest.raises(MappingError, match=r"\{lim\}"):
            SqlDirectAdapter(
                _pgDescriptor(table=None,
                              query="SELECT * FROM orders WHERE id > {wmCond}"),
                "pg_orders", "default")

    def test_queryMissingWmCondSlotRejected(self):
        with pytest.raises(MappingError, match=r"\{wmCond\}"):
            SqlDirectAdapter(
                _pgDescriptor(table=None, query="SELECT * FROM orders LIMIT {lim}"),
                "pg_orders", "default")

    def test_queryAndTableBothGivenRejected(self):
        with pytest.raises(MappingError, match="二选一"):
            SqlDirectAdapter(
                _pgDescriptor(query="SELECT * FROM orders WHERE id > {wmCond} LIMIT {lim}"),
                "pg_orders", "default")

    def test_neitherQueryNorTableRejected(self):
        with pytest.raises(MappingError, match="query 或 table"):
            SqlDirectAdapter(_pgDescriptor(table=None), "pg_orders", "default")

    def test_plaintextPasswordKeyRejected(self):
        with pytest.raises(MappingError, match="明文"):
            SqlDirectAdapter(_pgDescriptor(password="plain-pw"), "pg_orders", "default")

    def test_identifierInjectionRejected(self):
        with pytest.raises(MappingError, match="标识符"):
            SqlDirectAdapter(_pgDescriptor(table="orders; DROP TABLE x"),
                             "pg_orders", "default")
        with pytest.raises(MappingError, match="标识符"):
            SqlDirectAdapter(_pgDescriptor(cursorColumn="order_id--"),
                             "pg_orders", "default")
        with pytest.raises(MappingError, match="标识符"):
            SqlDirectAdapter(_pgDescriptor(columns=["order_id", "status; DROP"]),
                             "pg_orders", "default")

    def test_configGuardsForMissingConnectionFields(self):
        with pytest.raises(MappingError, match="database"):
            SqlDirectAdapter(_pgDescriptor(driver="sqlite", database=""),
                             "s", "default")
        with pytest.raises(MappingError, match="host"):
            SqlDirectAdapter(_pgDescriptor(host=""), "s", "default")
        with pytest.raises(MappingError, match="driver"):
            SqlDirectAdapter(_pgDescriptor(driver="mongodb"), "s", "default")


class TestDriverMissing:
    def test_missingDriverHealthNamesModule(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "psycopg2", None)  # import 即 ImportError
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")  # 构造期不炸
        health = _run(adapter.health())
        assert health.status == "error"
        assert "driver not installed: psycopg2" in health.reason, "点名缺失驱动模块"

    def test_missingDriverFetchRaisesNotSilentEmpty(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "psycopg2", None)
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")
        with pytest.raises(DriverNotInstalledError, match="driver not installed"):
            _run(adapter.fetchBatch(None, 2)), "驱动缺失不吞成空批"

    def test_driverModuleMapCoversClosedSet(self):
        from neurova.knowledge.enterprise.connectors_sql import _DRIVER_MODULES
        from neurova.knowledge.enterprise.schema_mapping import VARIANT_CLOSED_SETS

        assert set(_DRIVER_MODULES) == set(VARIANT_CLOSED_SETS["sql"][1])
        assert _DRIVER_MODULES["sqlite"] == "sqlite3", "sqlite 走 stdlib，恒在"


class TestNetworkDriversFakeChain:
    """四网络驱动各一条「假连接走完 fetchBatch 全链」：适配层不依赖真库。"""

    @pytest.mark.parametrize("driver,module,sqlBit,kwargKey,defaultPort", [
        ("postgresql", "psycopg2", "%s", "dbname", 5432),
        ("mysql", "pymysql", "%s", "database", 3306),
        ("mssql", "pymssql", "FETCH FIRST", "server", 1433),
        ("oracle", "oracledb", ":1", "dsn", 1521),
    ])
    def test_fetchFullChainThroughFakeConnection(
            self, monkeypatch, driver, module, sqlBit, kwargKey, defaultPort):
        cursor = FakeCursor(_ORDER_DESCRIPTION, [(42, "open")])
        connection = FakeConnection([cursor])
        driverModule = _installDriver(monkeypatch, module, [connection])
        adapter = SqlDirectAdapter(
            _pgDescriptor(driver=driver, port=None), "sql_orders", "default")

        batch = _run(adapter.fetchBatch(None, 2))

        assert [r["status"] for r in batch.rows] == ["open"], "假连接走完 fetchBatch 全链"
        assert batch.rows[0]["order_id"] == 42, "行按 cursor.description 列名归一成 dict"
        assert batch.nextCursor.token == "wm=42"
        sql, params = cursor.executed[0]
        assert sqlBit in sql, "各驱动方言形状（占位符/分页子句）"
        assert params == (3,), "首轮全量快照：只绑上限（limit+1）"
        kwargs = driverModule.connectCalls[0]
        assert kwargs.get(kwargKey), "连接参数按驱动分派（%s）" % kwargKey
        if driver == "oracle":
            assert str(defaultPort) in kwargs.get("dsn", ""), "oracle 端口折进 dsn"
        else:
            assert kwargs.get("port") == defaultPort, "描述符未配 port 用驱动缺省"
        assert kwargs.get("user") == "kuai" and kwargs.get("password") == "s3cret-pw", \
            "凭据只从环境变量进连接参数"
        assert connection.closed and cursor.closed, "短连接纪律：用毕即关"


class TestDescribeSchema:
    def test_describeSchemaGroupsRowsByTable(self, monkeypatch):
        cursor = FakeCursor(
            [("table_name",), ("column_name",), ("data_type",)],
            [("orders", "order_id", "integer"), ("orders", "status", "text"),
             ("users", "uid", "int")])
        _installDriver(monkeypatch, "psycopg2", [FakeConnection([cursor])])
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")
        schema = _run(adapter.describeSchema())
        assert schema.sourceType == "sql" and schema.sourceId == "pg_orders"
        assert [t["name"] for t in schema.tables] == ["orders", "users"], "按表分组"
        assert {"name": "order_id", "type": "integer"} in schema.tables[0]["columns"]


class TestSqliteRealSidecar:
    """sqlite 驱动用真实旁库文件端到端（stdlib sqlite3，零网络真连）。"""

    def _makeSidecar(self, path):
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE orders (order_id INTEGER PRIMARY KEY, status TEXT)")
        conn.executemany("INSERT INTO orders VALUES (?,?)",
                         [(1, "open"), (2, "closed"), (3, "open")])
        conn.commit()
        conn.close()

    def _sqliteDescriptor(self, dbPath, **overrides):
        descriptor = {
            "sourceId": "sqlite_orders", "tenantId": "default", "sourceType": "sql",
            "driver": "sqlite", "database": str(dbPath),
            "table": "orders", "cursorColumn": "order_id",
            "columns": ["order_id", "status"],
            "subject": {"template": "order:{order_id}"},
            "predicate": {"termId": "has_status"},
            "object": {"column": "status", "kind": "column"},
            "qualifiers": {}, "enabled": True, "agentId": "default",
        }
        descriptor.update(overrides)
        return descriptor

    def test_fetchWatermarkIncrementsOnRealSidecarFile(self, tmp_path):
        dbPath = tmp_path / "sidecar.db"
        self._makeSidecar(dbPath)
        adapter = SqlDirectAdapter(self._sqliteDescriptor(dbPath),
                                   "sqlite_orders", "default")
        first = _run(adapter.fetchBatch(None, 2))
        assert [r["order_id"] for r in first.rows] == [1, 2] and first.hasMore
        second = _run(adapter.fetchBatch(first.nextCursor, 2))
        assert [r["order_id"] for r in second.rows] == [3] and not second.hasMore
        # 源侧新增一行 → 水位推进后再取只取新行
        writer = sqlite3.connect(str(dbPath))
        writer.execute("INSERT INTO orders VALUES (4, 'open')")
        writer.commit()
        writer.close()
        third = _run(adapter.fetchBatch(second.nextCursor, 2))
        assert [r["order_id"] for r in third.rows] == [4], "水位增量对真实旁库成立"

    def test_describeSchemaReadsPragmaColumns(self, tmp_path):
        dbPath = tmp_path / "sidecar.db"
        self._makeSidecar(dbPath)
        adapter = SqlDirectAdapter(self._sqliteDescriptor(dbPath),
                                   "sqlite_orders", "default")
        schema = _run(adapter.describeSchema())
        assert [t["name"] for t in schema.tables] == ["orders"]
        columns = {c["name"]: c["type"] for c in schema.tables[0]["columns"]}
        assert columns.get("order_id") == "INTEGER" and columns.get("status") == "TEXT"

    def test_readonlyUriAndIndependentConnections(self, tmp_path):
        dbPath = tmp_path / "sidecar.db"
        self._makeSidecar(dbPath)
        adapter = SqlDirectAdapter(self._sqliteDescriptor(dbPath),
                                   "sqlite_orders", "default")
        conn = adapter._connect()
        try:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("CREATE TABLE t_probe (a int)"), "mode=ro 旁库写面显式失败"
        finally:
            conn.close()
        conn2 = adapter._connect()
        try:
            assert conn2 is not conn, "旁库独立连接，绝不共用主库连接"
        finally:
            conn2.close()

    def test_missingSidecarFileHealthError(self, tmp_path):
        adapter = SqlDirectAdapter(
            self._sqliteDescriptor(tmp_path / "missing.db"), "ghost", "default")
        health = _run(adapter.health())
        assert health.status == "error"
        assert "不存在" in health.reason

    def test_factoryWiringViaRegistry(self, tmp_path):
        from neurova.knowledge.enterprise.registry import buildAdapter

        adapter = buildAdapter(self._sqliteDescriptor(tmp_path / "s.db"),
                               "sqlite_orders", "default")
        assert isinstance(adapter, SqlDirectAdapter), \
            "工厂位 registry.buildAdapter 惰性分派到本模块"

    def test_runOnceEndToEndThroughAdmission(self, tmp_path):
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor

        dbPath = tmp_path / "sidecar.db"
        self._makeSidecar(dbPath)
        store = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
        try:
            termRegistry = OntologyTermRegistry(store)
            termRegistry.registerMany([{"termId": "has_status", "kind": "relation"}])
            ingestor = EnterpriseIngestor(store, registry=termRegistry)
            ingestor.saveConfig("default", "sqlite_orders",
                                self._sqliteDescriptor(dbPath), enabled=True)

            first = ingestor.runOnce("default", "sqlite_orders")
            assert first["admitted"] == 3, "三行旁库全量入账"
            facts = store.searchableFacts(agentId="default")
            assert any(f["canonical_label"] == "order:1" and f["object_term"] == "open"
                       for f in facts)
            assert ingestor.loadConfig("default", "sqlite_orders")["cursor"] == "wm=3", \
                "水位游标已持久化"

            writer = sqlite3.connect(str(dbPath))
            writer.execute("INSERT INTO orders VALUES (4, 'open')")
            writer.commit()
            writer.close()
            second = ingestor.runOnce("default", "sqlite_orders")
            assert second["admitted"] == 1, "水位推进后只摄取新行"

            third = ingestor.runOnce("default", "sqlite_orders")
            assert third["admitted"] == 0, "无新行收束：游标收口＋内容键幂等"
        finally:
            store.close()


class TestCredentialHygiene:
    def test_credentialsResolvedFromEnvNotDescriptor(self):
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")
        creds = adapter._resolveCredentials()
        assert creds == {"user": "kuai", "password": "s3cret-pw"}
        assert "s3cret-pw" not in json.dumps(adapter._descriptor), "描述符只有变量名"

    def test_connectFailureMasksSecretInReasonAndLogs(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "psycopg2", BoomDriver("psycopg2", []))
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")
        with caplog.at_level(logging.DEBUG,
                             logger="neurova.knowledge.enterprise.connectors_sql"):
            health = _run(adapter.health())
        assert health.status == "error"
        assert "s3cret-pw" not in health.reason and "***" in health.reason, \
            "失败原因打码后回显"
        assert "s3cret-pw" not in caplog.text, "凭据不落日志"

    def test_passwordEncryptedRouteUsesKbSecretFacility(self, monkeypatch):
        from cryptography.fernet import Fernet

        from neurova.knowledge.storage import _encrypt_secret

        monkeypatch.setenv("NEUROVA_KB_SECRET", Fernet.generate_key().decode())
        token = _encrypt_secret("s3cret-pw")
        assert token and token != "s3cret-pw"
        descriptor = _pgDescriptor(credentialEnv={}, passwordEncrypted=token)
        cursor = FakeCursor(_ORDER_DESCRIPTION, [(42, "open")])
        driverModule = _installDriver(monkeypatch, "psycopg2",
                                      [FakeConnection([cursor])])
        adapter = SqlDirectAdapter(descriptor, "pg_orders", "default")
        batch = _run(adapter.fetchBatch(None, 2))
        assert [r["order_id"] for r in batch.rows] == [42]
        assert driverModule.connectCalls[0].get("password") == "s3cret-pw", \
            "NEUROVA_KB_SECRET 解密设施只进连接参数"
        assert "s3cret-pw" not in json.dumps(descriptor), "描述符只放密文"

    def test_successLogsCarryCountsNotRowContents(self, monkeypatch, caplog):
        cursor = FakeCursor(_ORDER_DESCRIPTION, [(42, "open"), (43, "closed")])
        _installDriver(monkeypatch, "psycopg2", [FakeConnection([cursor])])
        adapter = SqlDirectAdapter(_pgDescriptor(), "pg_orders", "default")
        with caplog.at_level(logging.DEBUG,
                             logger="neurova.knowledge.enterprise.connectors_sql"):
            _run(adapter.fetchBatch(None, 2))
        assert "rows=2" in caplog.text, "日志只落计数与标志位"
        assert "open" not in caplog.text and "closed" not in caplog.text, \
            "原始行内容不落日志"


class TestQueryRouteCompileGuard:
    """query 路由过编译期守卫的豁免面（C4 共享文件点①的收口判据）。"""

    def test_sqlQueryTemplatePassesCompileValidation(self, tmp_path):
        from neurova.knowledge.enterprise.schema_mapping import validateDescriptor
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
        from neurova.knowledge.enterprise.registry import EnterpriseIngestor
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        store = KnowledgeFactStore(":memory:")
        try:
            registry = OntologyTermRegistry(store)
            registry.registerMany([{"termId": "has_status", "kind": "relation"}])
            descriptor = _pgDescriptor(sourceType="sql", driver="sqlite")
            descriptor["query"] = ("SELECT {columns} FROM orders"
                                   " WHERE {wmCond} ORDER BY id {lim}")
            descriptor.pop("table", None)
            validateDescriptor(descriptor, registry), "只读查询模板过编译期守卫"
            ingestor = EnterpriseIngestor(store, registry=registry)
            ingestor.saveConfig("default", "sql_query_src", descriptor, enabled=False)
            config = ingestor.loadConfig("default", "sql_query_src")
            assert "SELECT" in config["descriptor"]["query"], "query 路由可存库"
        finally:
            store.close()

    def test_queryFieldStillGuardedForNonSqlTypes(self, tmp_path):
        from neurova.knowledge.enterprise.schema_mapping import (
            MappingError,
            validateDescriptor,
        )
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
        from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

        store = KnowledgeFactStore(":memory:")
        try:
            registry = OntologyTermRegistry(store)
            registry.registerMany([{"termId": "has_status", "kind": "relation"}])
            descriptor = _pgDescriptor(sourceType="file")
            descriptor.pop("driver", None)
            descriptor.pop("host", None)
            descriptor.pop("port", None)
            descriptor.pop("database", None)
            descriptor.pop("cursorColumn", None)
            descriptor.pop("credentialEnv", None)
            descriptor["format"] = "csv"
            descriptor["path"] = "orders.csv"
            descriptor["query"] = "SELECT secret_column FROM orders"
            with pytest.raises(MappingError, match="SQL 形状"):
                validateDescriptor(descriptor, registry), "非 sql 源的 query 字段照旧全禁"
        finally:
            store.close()
