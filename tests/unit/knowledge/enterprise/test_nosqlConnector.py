# -*- coding: utf-8 -*-
"""U-conn 扩展批：Cassandra 连接器——驱动桩注入 sys.modules（真 import 链路），
registry 分派、fetchBatch 切页、health 探测、驱动缺失诚实降级。
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from neurova.knowledge.enterprise.connectors_nosql import CassandraAdapter
from neurova.knowledge.enterprise.registry import buildAdapter


class FakeRow:
    def __init__(self, **fields):
        self._fields = tuple(fields)
        for key, value in fields.items():
            setattr(self, key, value)


class FakeSession:
    def __init__(self):
        self.executed = []

    def set_keyspace(self, keyspace):
        self.keyspace = keyspace

    def execute(self, cql, params=None):
        self.executed.append((cql, params))
        if "system.local" in cql:
            return [FakeRow(release_version="6.0.0")]
        if "system_schema.columns" in cql:
            return [FakeRow(table_name="orders", column_name="id", type="int"),
                    FakeRow(table_name="orders", column_name="city", type="text")]
        return [FakeRow(id=1, city="shanghai"), FakeRow(id=2, city="beijing")]


class FakeCluster:
    def __init__(self, contact_points, auth_provider=None):
        FakeCluster.lastContactPoints = list(contact_points)
        FakeCluster.lastAuthProvider = auth_provider

    def connect(self, keyspace=None):
        return FakeSession()

    def shutdown(self):
        pass


@pytest.fixture
def fakeDriver(monkeypatch):
    """向 sys.modules 注入 cassandra 驱动桩（真 import 链路走到桩）。"""
    clusterMod = types.ModuleType("cassandra.cluster")
    clusterMod.Cluster = FakeCluster
    authMod = types.ModuleType("cassandra.auth")
    authMod.PlainTextAuthProvider = lambda user, password: ("plain", user, password)
    cassandraMod = types.ModuleType("cassandra")
    cassandraMod.cluster = clusterMod
    cassandraMod.auth = authMod
    monkeypatch.setitem(sys.modules, "cassandra", cassandraMod)
    monkeypatch.setitem(sys.modules, "cassandra.cluster", clusterMod)
    monkeypatch.setitem(sys.modules, "cassandra.auth", authMod)
    return cassandraMod


def _adapter():
    return CassandraAdapter(
        {"sourceType": "cassandra", "contact_points": "127.0.0.1,127.0.0.2",
         "keyspace": "erp", "table": "orders", "cql": "SELECT id, city FROM orders",
         "credentialEnv": {"username": "T_CAS_USER", "password": "T_CAS_PASS"}},
        "cas1", "default")


class TestRegistryDispatch:
    def test_cassandraDispatchesToCassandraAdapter(self):
        assert isinstance(buildAdapter({"sourceType": "cassandra",
                                        "contact_points": "127.0.0.1"},
                                       "src-cas", "default"), CassandraAdapter)


class TestCassandraAdapter:
    def test_fetchBatchSlicesRowsWithOffsetCursor(self, fakeDriver):
        adapter = _adapter()
        batch = _run(adapter.fetchBatch(None, 1))
        assert batch.rows == [{"id": 1, "city": "shanghai"}]
        assert batch.hasMore is True
        batch2 = _run(adapter.fetchBatch(batch.nextCursor, 1))
        assert batch2.rows == [{"id": 2, "city": "beijing"}]
        assert batch2.hasMore is False

    def test_fetchFailureRaisesInsteadOfEmptySuccess(self, monkeypatch):
        adapter = _adapter()

        def boom(*args, **kwargs):
            raise ConnectionError("cassandra unavailable")

        monkeypatch.setattr(adapter, "_query", boom)
        with pytest.raises(ConnectionError, match="cassandra unavailable"):
            _run(adapter.fetchBatch(None, 10))

    def test_missingCqlRaisesInsteadOfEmptySuccess(self):
        adapter = CassandraAdapter({"sourceType": "cassandra"}, "cas-missing", "default")
        with pytest.raises(ValueError, match="cql"):
            _run(adapter.fetchBatch(None, 10))

    def test_healthProbesSystemLocal(self, fakeDriver):
        adapter = _adapter()
        health = _run(adapter.health())
        assert health.status == "ok" and health.reason == "6.0.0"

    def test_describeSchemaFallsBackToSystemSchema(self, fakeDriver):
        adapter = _adapter()
        schema = _run(adapter.describeSchema())
        assert schema.tables[0]["table_name"] == "orders"
        assert {"column_name": "id", "data_type": "int"} in schema.tables[0]["columns"]

    def test_credentialsReachAuthProvider(self, fakeDriver, monkeypatch):
        monkeypatch.setenv("T_CAS_USER", "casuser")
        monkeypatch.setenv("T_CAS_PASS", "caspass")
        adapter = _adapter()
        _run(adapter.health())
        assert FakeCluster.lastAuthProvider == ("plain", "casuser", "caspass")

    def test_missingDriverIsHonestError(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "cassandra", None)
        monkeypatch.setitem(sys.modules, "cassandra.cluster", None)
        monkeypatch.setitem(sys.modules, "cassandra.auth", None)
        adapter = _adapter()
        health = _run(adapter.health())
        assert health.status == "error" and "cassandra-driver" in health.reason


def _run(coro):
    return asyncio.run(coro)
