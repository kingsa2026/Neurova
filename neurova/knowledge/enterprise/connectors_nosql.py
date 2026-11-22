# -*- coding: utf-8 -*-
"""NoSQL 连接器（U-conn 扩展批）：Cassandra CQL。

驱动 ``cassandra-driver`` 是**可选依赖**（requirements.txt 注释段，按需安装）：
惰性 import＋fail-soft——未安装时 health/fetchBatch 显式 error（点名驱动缺失），
不炸注册表、不假装连通。凭据走 NEUROVA_KB_SECRET 指针纪律（credentialEnv
对象：{username, password} 两个环境变量名）。

CQL 结果集在客户端做 offset 切页（游标 token=已消费行数）；CQL 本身带
LIMIT 时以实际返回行为准。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class CassandraAdapter:
    """`sourceType=cassandra` 的 Protocol 实现（CQL 只读拉取）。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str = "default") -> None:
        self._descriptor = dict(descriptor or {})
        self._sourceId = str(sourceId)
        self._tenantId = str(tenantId or "default")
        self._contactPoints = [p.strip() for p in
                               str(self._descriptor.get("contact_points") or "").split(",")
                               if p.strip()]
        self._keyspace = str(self._descriptor.get("keyspace") or "")
        self._table = str(self._descriptor.get("table") or "")
        self._cql = str(self._descriptor.get("cql") or "")
        creds = dict(self._descriptor.get("credentialEnv") or {})
        self._credentialEnv = {str(k): str(v) for k, v in creds.items()}
        self._cluster: Optional[Any] = None
        self._session: Optional[Any] = None
        self._connectLock = threading.Lock()

    def _password(self) -> str:
        import os

        envName = self._passwordEnv.strip()
        return os.environ.get(envName, "") if envName else ""

    def _connect(self) -> Any:
        """惰性建连（进程内复用）；驱动缺失显式 RuntimeError（不吞成空批）。"""
        if self._session is not None:
            return self._session
        with self._connectLock:
            if self._session is not None:
                return self._session
            try:
                from cassandra.cluster import Cluster  # 可选依赖：requirements 注释段
            except ImportError as exc:
                raise RuntimeError(
                    "cassandra-driver 未安装（可选依赖，按需安装）：%s" % exc) from exc
            if not self._contactPoints:
                raise RuntimeError("contact_points 缺失（描述符）")
            cluster = Cluster(self._contactPoints,
                              auth_provider=self._authProvider())
            session = cluster.connect(self._keyspace or None)
            self._cluster = cluster
            self._session = session
            return session

    def _authProvider(self) -> Optional[Any]:
        from .protocols import resolveCredentialEnv

        creds = resolveCredentialEnv(self._descriptor, "credentialEnv")
        user = creds.get("username", "")
        password = creds.get("password", "")
        if user and password:
            from cassandra.auth import PlainTextAuthProvider

            return PlainTextAuthProvider(user, password)
        return None

    async def describeSchema(self) -> Any:
        from .protocols import SourceSchema

        tables = self._descriptor.get("tables") or []
        if tables:
            return SourceSchema(sourceId=self._sourceId,
                                sourceType="cassandra",
                                tables=[dict(t) for t in tables])
        # 缺省从 system_schema 反查键空间的表与列（只读系统表）
        rows = self._query(
            "SELECT table_name, column_name, type FROM system_schema.columns"
            " WHERE keyspace_name = %s", (self._keyspace,))
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get("table_name")), []).append(
                {"column_name": row.get("column_name"), "data_type": row.get("type")})
        tables = [{"table_name": name, "columns": columns}
                  for name, columns in sorted(grouped.items())]
        return SourceSchema(sourceId=self._sourceId, sourceType="cassandra",
                            tables=tables)

    async def health(self) -> Any:
        from .protocols import SourceHealth

        try:
            rows = self._query("SELECT release_version FROM system.local", (),
                               keyspaceless=True)
            return SourceHealth(status="ok",
                                 reason=str(rows[0].get("release_version")) if rows else "")
        except Exception as exc:  # noqa: BLE001 - health 是读数不是断言
            return SourceHealth(status="error", reason=str(exc))

    async def close(self) -> None:
        if self._cluster is not None:
            try:
                self._cluster.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self._cluster = None
            self._session = None

    def _query(self, cql: str, params: Tuple[Any, ...] = (),
               keyspaceless: bool = False) -> List[Dict[str, Any]]:
        session = self._connect()
        if not keyspaceless and self._keyspace:
            session.set_keyspace(self._keyspace)
        rows = session.execute(cql, params or None)
        out: List[Dict[str, Any]] = []
        for row in rows:
            try:
                out.append({field: getattr(row, field) for field in row._fields})
            except AttributeError:
                out.append({str(i): value for i, value in enumerate(row)})
        return out

    async def fetchBatch(self, cursor: Any, limit: int) -> Any:
        from .protocols import ChangeBatch, SourceCursor

        if not self._cql:
            return ChangeBatch(rows=[], nextCursor=None, hasMore=False)
        offset = 0
        if cursor and getattr(cursor, "token", ""):
            try:
                offset = int(cursor.token)
            except (ValueError, TypeError):
                offset = 0
        try:
            rows = self._query(self._cql)
        except Exception as exc:  # noqa: BLE001 - 拉取失败诚实空批＋日志留名
            logger.warning("cassandra: 拉取失败 %s: %s", self._sourceId, exc)
            rows = []
        window = rows[offset:offset + max(1, int(limit))]
        hasMore = offset + len(window) < len(rows)
        nextCursor = SourceCursor(token=str(offset + len(window))) \
            if hasMore else None
        return ChangeBatch(rows=window, nextCursor=nextCursor, hasMore=hasMore)
