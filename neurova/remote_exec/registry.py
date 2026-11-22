# -*- coding: utf-8 -*-
"""统一远程执行面·端点注册表（W1a，计划见 docs/04-plans/2026-11-22-reference-ad-tool-security-upgrade-implementation-plan.md §4）。

六形态（ssh/guest/tunnel/neuacp/mcp，中继代部署归 tunnel 段）此前各自为政：
ssh_runner/guest_agent/tunnel/neuacp 名册/mcp_source 各记各的连接信息，无统一
注册表与审计面。本模块提供唯一端点账本：

- **自然键** ``(tenantId, ownerId, kind, name)``：upsert 幂等；
  ``endpointId`` 由自然键 sha256 派生 16 hex，稳定可复现（重注册不换 id）。
- **不存明文凭据**：连接信息只存引用名 ``connectionRef``（凭据桶/配置键名）。
- **租户段隔离**：tenantId 是自然键首位，跨租户同名的端点互不可见。
- **健康度**：health(unknown|online|offline) + lastSeenAt（ISO8601 UTC），
  由分派漏斗（dispatch.py）在执行成功/离线 hold 时回写。
- **SQLite 落盘**：连接经 ``core/connection_pool`` 池化借还；schema 走
  ``core/db_migration`` 的 ``remote_exec`` 版本域（DDL 事实源在该注册表，
  本模块不自建第二份建表语句）。

深模块边界：本包禁止 import tool_executor/computer_use/guest_agent/tunnel/neuacp
（避免循环依赖）；各形态的执行体由调用方注入（见 dispatch.py 的 executor 参数）。
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from neurova.core.connection_pool import get_db_connection
from neurova.core.data_root import dataLanding
from neurova.core.db_migration import migrate as applyDomainMigrations
from neurova.core.logger import get_logger

logger = get_logger(__name__)

# ── 形态常量（唯一出处；分派漏斗与后续接线代理一律引用这里的名字） ──
KIND_SSH = "ssh"
KIND_GUEST = "guest"
KIND_TUNNEL = "tunnel"
KIND_NEUACP = "neuacp"
KIND_MCP = "mcp"

REMOTE_KINDS = frozenset({KIND_SSH, KIND_GUEST, KIND_TUNNEL, KIND_NEUACP, KIND_MCP})

#: db_migration 版本域名（DDL 注册在 core/db_migration.py 的 remote_exec 域）
REMOTE_EXEC_DB_DOMAIN = "remote_exec"

_HEALTH_UNKNOWN = "unknown"
_HEALTH_ONLINE = "online"
_HEALTH_OFFLINE = "offline"
_VALID_HEALTH = frozenset({_HEALTH_UNKNOWN, _HEALTH_ONLINE, _HEALTH_OFFLINE})


@dataclass
class RemoteEndpoint:
    """一个可寻址的远程执行端点（不携带明文凭据）。"""

    endpointId: str
    kind: str
    name: str
    ownerId: str = ""
    tenantId: str = "default"
    capabilities: Dict[str, Any] = field(default_factory=dict)
    connectionRef: str = ""
    health: str = _HEALTH_UNKNOWN
    lastSeenAt: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


def deriveEndpointId(tenantId: str, ownerId: str, kind: str, name: str) -> str:
    """自然键 → 16 hex 稳定 id（sha256 前 16 位；\\x00 分隔防拼接歧义）。"""
    naturalKey = "\x00".join(
        [tenantId or "default", ownerId or "", kind or "", name or ""]
    )
    return hashlib.sha256(naturalKey.encode("utf-8")).hexdigest()[:16]


def _utcNowIso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rowToEndpoint(row) -> RemoteEndpoint:
    capabilities = _loadJsonDict(row["capabilities_json"], row["endpoint_id"], "capabilities")
    meta = _loadJsonDict(row["meta_json"], row["endpoint_id"], "meta")
    return RemoteEndpoint(
        endpointId=row["endpoint_id"],
        kind=row["kind"],
        name=row["name"],
        ownerId=row["owner_id"] or "",
        tenantId=row["tenant_id"] or "default",
        capabilities=capabilities,
        connectionRef=row["connection_ref"] or "",
        health=row["health"] or _HEALTH_UNKNOWN,
        lastSeenAt=row["last_seen_at"],
        meta=meta,
    )


def _loadJsonDict(raw: Any, endpointId: str, fieldName: str) -> Dict[str, Any]:
    """JSON 列 → dict；损坏内容告警并按空 dict 处理（读路径不因单行脏数据中断）。"""
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning(
            "remote_endpoints 行 %s 的 %s 列不是合法 JSON，按空处理", endpointId, fieldName
        )
        return {}
    return loaded if isinstance(loaded, dict) else {}


class RemoteEndpointRegistry:
    """远程端点注册表（SQLite 持久化；连接经 core/connection_pool 池化借还）。"""

    def __init__(self, db_path: str = ""):
        self._db_path = str(db_path or dataLanding("remote_endpoints.db", legacy=()))
        self._lock = threading.RLock()
        self._ensureSchema()

    @property
    def dbPath(self) -> str:
        return self._db_path

    def _ensureSchema(self) -> None:
        with self._lock:
            with get_db_connection(self._db_path) as conn:
                applyDomainMigrations(conn, REMOTE_EXEC_DB_DOMAIN)

    def registerEndpoint(self, endpoint: RemoteEndpoint) -> RemoteEndpoint:
        """按自然键 upsert；返回库中落定后的端点（endpointId 为派生值）。

        冲突时保留首写 created_at，其余声明字段以后写为准。
        """
        tenantId = (endpoint.tenantId or "").strip() or "default"
        ownerId = endpoint.ownerId or ""
        kind = endpoint.kind or ""
        name = endpoint.name or ""
        endpointId = deriveEndpointId(tenantId, ownerId, kind, name)
        now = _utcNowIso()
        capabilitiesJson = json.dumps(endpoint.capabilities or {}, ensure_ascii=False, sort_keys=True)
        metaJson = json.dumps(endpoint.meta or {}, ensure_ascii=False, sort_keys=True)
        health = endpoint.health if endpoint.health in _VALID_HEALTH else _HEALTH_UNKNOWN
        with self._lock:
            with get_db_connection(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO remote_endpoints
                        (endpoint_id, tenant_id, owner_id, kind, name, connection_ref,
                         health, last_seen_at, capabilities_json, meta_json,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(endpoint_id) DO UPDATE SET
                        connection_ref = excluded.connection_ref,
                        health = excluded.health,
                        last_seen_at = excluded.last_seen_at,
                        capabilities_json = excluded.capabilities_json,
                        meta_json = excluded.meta_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        endpointId,
                        tenantId,
                        ownerId,
                        kind,
                        name,
                        endpoint.connectionRef or "",
                        health,
                        endpoint.lastSeenAt,
                        capabilitiesJson,
                        metaJson,
                        now,
                        now,
                    ),
                )
                conn.commit()
        stored = self.getEndpoint(endpointId)
        assert stored is not None  # 刚写入必然可读
        return stored

    def getEndpoint(self, endpointId: str) -> Optional[RemoteEndpoint]:
        with get_db_connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM remote_endpoints WHERE endpoint_id = ?", (endpointId,)
            ).fetchone()
        return _rowToEndpoint(row) if row is not None else None

    def findEndpoints(
        self,
        *,
        tenantId: Optional[str] = None,
        ownerId: Optional[str] = None,
        kind: Optional[str] = None,
        name: Optional[str] = None,
    ) -> List[RemoteEndpoint]:
        """等值过滤（None = 不限），结果按自然键稳定排序。"""
        clauses: List[str] = []
        args: List[Any] = []
        if tenantId is not None:
            clauses.append("tenant_id = ?")
            args.append(tenantId)
        if ownerId is not None:
            clauses.append("owner_id = ?")
            args.append(ownerId)
        if kind is not None:
            clauses.append("kind = ?")
            args.append(kind)
        if name is not None:
            clauses.append("name = ?")
            args.append(name)
        sql = "SELECT * FROM remote_endpoints"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY tenant_id, owner_id, kind, name"
        with get_db_connection(self._db_path) as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_rowToEndpoint(row) for row in rows]

    def markEndpointSeen(self, endpointId: str, health: str = _HEALTH_ONLINE) -> None:
        """回写健康度与 lastSeenAt（ISO8601 UTC）；未知 id 静默无操作。"""
        normalized = health if health in _VALID_HEALTH else _HEALTH_UNKNOWN
        now = _utcNowIso()
        with self._lock:
            with get_db_connection(self._db_path) as conn:
                conn.execute(
                    "UPDATE remote_endpoints"
                    " SET health = ?, last_seen_at = ?, updated_at = ?"
                    " WHERE endpoint_id = ?",
                    (normalized, now, now, endpointId),
                )
                conn.commit()

    def removeEndpoint(self, endpointId: str) -> bool:
        with self._lock:
            with get_db_connection(self._db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM remote_endpoints WHERE endpoint_id = ?", (endpointId,)
                )
                conn.commit()
        return cursor.rowcount > 0


# ── 进程内单例（DCL + RLock；库落点随数据根，可注入 NEUROVA_DATA_DIR） ──
_REGISTRY_LOCK = threading.RLock()
_REGISTRY_SINGLETON: Optional[RemoteEndpointRegistry] = None


def getRemoteEndpointRegistry() -> RemoteEndpointRegistry:
    global _REGISTRY_SINGLETON
    if _REGISTRY_SINGLETON is None:
        with _REGISTRY_LOCK:
            if _REGISTRY_SINGLETON is None:
                _REGISTRY_SINGLETON = RemoteEndpointRegistry()
    return _REGISTRY_SINGLETON
