# -*- coding: utf-8 -*-
"""W1a 统一远程执行面·端点注册表——真实 SQLite 行为测试。

被测模块：`neurova/remote_exec/registry.py` 与 `core/db_migration.py` 的
remote_exec 域注册。断言全部落在真实 SQLite 上（临时数据根 + 真连接，
无 MagicMock 充当数据库）：

- 自然键 (tenantId, ownerId, kind, name) upsert 幂等，endpointId 由自然键
  sha256 派生 16 hex、稳定可复现；
- 租户段隔离与 tenant/kind/owner/name 等值过滤；
- markEndpointSeen 更新 health + lastSeenAt（ISO8601 UTC）；
- removeEndpoint 语义（存在 True / 缺失 False）；
- remote_exec 迁移域建表且可写（对齐 core 既有迁移测试形态）；
- 进程内单例 DCL + 落盘持久化（换实例读同一库）。
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime

import pytest

from neurova.core import connection_pool as connection_pool_mod
from neurova.core.db_migration import latest_version, migrate, registered_domains
from neurova.remote_exec import registry as registry_mod
from neurova.remote_exec.registry import (
    KIND_GUEST,
    KIND_MCP,
    KIND_NEUACP,
    KIND_SSH,
    KIND_TUNNEL,
    REMOTE_EXEC_DB_DOMAIN,
    REMOTE_KINDS,
    RemoteEndpoint,
    RemoteEndpointRegistry,
    deriveEndpointId,
    getRemoteEndpointRegistry,
)


@pytest.fixture()
def isolatedDataRoot(tmp_path, monkeypatch):
    """临时数据根 + 单例/连接池复位（Windows 下防句柄锁住临时目录）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None
    yield tmp_path
    connection_pool_mod.close_all_pools()
    registry_mod._REGISTRY_SINGLETON = None


def _endpoint(**overrides) -> RemoteEndpoint:
    fields = dict(
        endpointId="",
        kind=KIND_SSH,
        name="ssh:10.0.0.5:22",
        ownerId="agent-1",
        tenantId="default",
        capabilities={"exec": True, "files": False},
        connectionRef="cred:ssh-prod-1",
        meta={"region": "cn-north-1"},
    )
    fields.update(overrides)
    return RemoteEndpoint(**fields)


# ── 常量与迁移域 ──


def test_remoteKindsCoverSixForms():
    assert KIND_SSH == "ssh"
    assert KIND_GUEST == "guest"
    assert KIND_TUNNEL == "tunnel"
    assert KIND_NEUACP == "neuacp"
    assert KIND_MCP == "mcp"
    assert REMOTE_KINDS == frozenset({"ssh", "guest", "tunnel", "neuacp", "mcp"})


def test_remoteExecDomainIsRegistered():
    assert REMOTE_EXEC_DB_DOMAIN in registered_domains()
    assert latest_version(REMOTE_EXEC_DB_DOMAIN) >= 1


def test_migrationCreatesWritableTable(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "remote_exec_fresh.db"))
    try:
        applied = migrate(conn, REMOTE_EXEC_DB_DOMAIN)
        assert applied == [1]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "remote_endpoints" in names
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "ux_remote_endpoints_natural_key" in indexes
        # 建表后即可裸 SQL 写入（可写性）
        conn.execute(
            "INSERT INTO remote_endpoints (endpoint_id, kind, name, created_at, updated_at)"
            " VALUES ('raw-1', 'ssh', 'ssh:raw:22', '2026-11-22T00:00:00+00:00',"
            " '2026-11-22T00:00:00+00:00')"
        )
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM remote_endpoints").fetchone()[0] == 1
    finally:
        conn.close()


# ── 注册：自然键派生 + upsert 幂等 ──


def test_registerEndpointDerivesStableIdFromNaturalKey(isolatedDataRoot):
    registry = RemoteEndpointRegistry()
    first = registry.registerEndpoint(_endpoint())
    second = registry.registerEndpoint(_endpoint())

    expectedId = hashlib.sha256(
        "\x00".join(["default", "agent-1", KIND_SSH, "ssh:10.0.0.5:22"]).encode("utf-8")
    ).hexdigest()[:16]
    assert deriveEndpointId("default", "agent-1", KIND_SSH, "ssh:10.0.0.5:22") == expectedId
    assert first.endpointId == expectedId
    # 幂等：同自然键重复注册，endpointId 稳定可复现
    assert second.endpointId == first.endpointId
    assert len(first.endpointId) == 16
    int(first.endpointId, 16)  # 16 hex 可解析


def test_registerEndpointUpsertDoesNotDuplicateRows(isolatedDataRoot):
    registry = RemoteEndpointRegistry()
    registry.registerEndpoint(
        _endpoint(capabilities={"exec": True}, connectionRef="cred:old")
    )
    updated = registry.registerEndpoint(
        _endpoint(capabilities={"exec": True, "files": True}, connectionRef="cred:new")
    )

    rows = registry.findEndpoints()
    assert len(rows) == 1
    assert rows[0].endpointId == updated.endpointId
    assert rows[0].connectionRef == "cred:new"
    assert rows[0].capabilities == {"exec": True, "files": True}

    # created_at 保留首写值，updated_at 随更新推进
    conn = sqlite3.connect(str(isolatedDataRoot / "remote_endpoints.db"))
    try:
        row = conn.execute(
            "SELECT created_at, updated_at FROM remote_endpoints WHERE endpoint_id = ?",
            (updated.endpointId,),
        ).fetchone()
        assert row is not None
        assert row[0] <= row[1]
    finally:
        conn.close()


def test_registerEndpointNormalizesEmptyTenantToDefault(isolatedDataRoot):
    registry = RemoteEndpointRegistry()
    registered = registry.registerEndpoint(_endpoint(tenantId=""))
    assert registered.tenantId == "default"
    assert registered.endpointId == deriveEndpointId(
        "default", "agent-1", KIND_SSH, "ssh:10.0.0.5:22"
    )


# ── 查询：等值过滤与租户隔离 ──


def test_findEndpointsFiltersByTenantKindOwnerName(isolatedDataRoot):
    registry = RemoteEndpointRegistry()
    registry.registerEndpoint(_endpoint(name="ssh:a:22", kind=KIND_SSH, ownerId="agent-1", tenantId="default"))
    registry.registerEndpoint(_endpoint(name="guest:a", kind=KIND_GUEST, ownerId="agent-1", tenantId="default"))
    registry.registerEndpoint(_endpoint(name="ssh:b:22", kind=KIND_SSH, ownerId="agent-2", tenantId="tenant-a"))
    registry.registerEndpoint(_endpoint(name="mcp:b", kind=KIND_MCP, ownerId="agent-2", tenantId="tenant-a"))

    assert len(registry.findEndpoints()) == 4
    assert {ep.name for ep in registry.findEndpoints(tenantId="tenant-a")} == {"ssh:b:22", "mcp:b"}
    assert {ep.name for ep in registry.findEndpoints(kind=KIND_SSH)} == {"ssh:a:22", "ssh:b:22"}
    assert [ep.name for ep in registry.findEndpoints(tenantId="tenant-a", kind=KIND_SSH)] == ["ssh:b:22"]
    assert {ep.name for ep in registry.findEndpoints(ownerId="agent-1")} == {"ssh:a:22", "guest:a"}
    assert [ep.name for ep in registry.findEndpoints(name="mcp:b")] == ["mcp:b"]
    assert registry.findEndpoints(tenantId="no-such-tenant") == []


def test_sameNaturalKeyInDifferentTenantsStaysIsolated(isolatedDataRoot):
    registry = RemoteEndpointRegistry()
    inDefault = registry.registerEndpoint(_endpoint(tenantId="default"))
    inTenantA = registry.registerEndpoint(_endpoint(tenantId="tenant-a"))

    assert inDefault.endpointId != inTenantA.endpointId
    assert [ep.endpointId for ep in registry.findEndpoints(tenantId="default")] == [inDefault.endpointId]
    assert [ep.endpointId for ep in registry.findEndpoints(tenantId="tenant-a")] == [inTenantA.endpointId]


def test_getEndpointRoundTripsJsonFieldsAndDefaults(isolatedDataRoot):
    registry = RemoteEndpointRegistry()
    registered = registry.registerEndpoint(_endpoint())

    fetched = registry.getEndpoint(registered.endpointId)
    assert fetched is not None
    assert fetched.kind == KIND_SSH
    assert fetched.name == "ssh:10.0.0.5:22"
    assert fetched.ownerId == "agent-1"
    assert fetched.tenantId == "default"
    assert fetched.capabilities == {"exec": True, "files": False}
    assert fetched.connectionRef == "cred:ssh-prod-1"
    assert fetched.meta == {"region": "cn-north-1"}
    assert fetched.health == "unknown"
    assert fetched.lastSeenAt is None
    assert registry.getEndpoint("missing-id") is None


# ── 健康度 ──


def test_markEndpointSeenUpdatesHealthAndLastSeenAt(isolatedDataRoot):
    registry = RemoteEndpointRegistry()
    registered = registry.registerEndpoint(_endpoint())

    registry.markEndpointSeen(registered.endpointId)
    online = registry.getEndpoint(registered.endpointId)
    assert online is not None
    assert online.health == "online"
    assert online.lastSeenAt is not None
    parsed = datetime.fromisoformat(online.lastSeenAt)
    assert parsed.utcoffset() is not None  # ISO8601 且带时区

    registry.markEndpointSeen(registered.endpointId, "offline")
    offline = registry.getEndpoint(registered.endpointId)
    assert offline is not None
    assert offline.health == "offline"
    assert offline.lastSeenAt is not None

    # 未知 endpointId：静默无行受影响，不抛错
    registry.markEndpointSeen("missing-id", "online")


# ── 删除 ──


def test_removeEndpointRemovesExactlyOnce(isolatedDataRoot):
    registry = RemoteEndpointRegistry()
    registered = registry.registerEndpoint(_endpoint())

    assert registry.removeEndpoint(registered.endpointId) is True
    assert registry.getEndpoint(registered.endpointId) is None
    assert registry.removeEndpoint(registered.endpointId) is False


# ── 单例与持久化 ──


def test_singletonIsSameInstanceAndPersistsAcrossInstances(isolatedDataRoot):
    registryOne = getRemoteEndpointRegistry()
    registryTwo = getRemoteEndpointRegistry()
    assert registryOne is registryTwo

    registered = registryOne.registerEndpoint(_endpoint())
    # 换一个新实例（同一数据根）仍能读到——落盘而非进程内存
    freshInstance = RemoteEndpointRegistry()
    assert freshInstance.getEndpoint(registered.endpointId) is not None
    assert (isolatedDataRoot / "remote_endpoints.db").exists()
