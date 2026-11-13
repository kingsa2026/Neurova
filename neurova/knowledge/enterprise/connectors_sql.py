# -*- coding: utf-8 -*-
"""数据库直连适配器（立项方案批 C4，2026-11-07 裁定 §2.4-1：直接做，依赖豁免已登记）。

`sourceType=sql` ＋ `driver` 变体（闭集在 schema_mapping.VARIANT_CLOSED_SETS 编译期
收口，工厂 registry.buildAdapter 惰性分派到本类——本模块只提供类，不碰工厂）。

纪律（方案 §2.4-1 补偿四条与 §4 原文有效）：
- 驱动全部惰性 import＋fail-soft：驱动未安装**不在构造期炸**，health() 显式
  status="error" reason="driver not installed: <module>"；fetchBatch/describeSchema
  如实抛 DriverNotInstalledError（不吞成空批）；
- 连接参数：host/port/database 在描述符；口令/密码只从 credentialEnv（「字段→
  环境变量名」映射，ERP 连接器同款形状）或 passwordEncrypted（经仓内唯一解密设施
  NEUROVA_KB_SECRET）取——描述符只放变量名/密文，绝不放明文（构造期显式拒）；
- sqlite 用只读 URI（mode=ro）开**独立**短连接，绝不 ATTACH、绝不共用主库连接；
- fetchBatch 按 cursorColumn 水位增量：首轮空游标＝全量快照（无 WHERE），此后
  WHERE col > 水位 ORDER BY col，多取一行判 hasMore，nextCursor=本批最大水位；
- query 路由（descriptor["query"]，只读模板含 {wmCond}/{lim} 槽位）与
  table+columns 路由二选一；任何写意图形状（INSERT/UPDATE/DELETE/DDL/ATTACH/
  PRAGMA/多语句/注释拼接）构造期显式 MappingError，不静默；
- 表/列/水位列全部过标识符白名单：值一律参数化、名字一律校验——描述符进不了
  任意 SQL（编译期 schema_mapping 的 SQL 形状守卫之外的第二道运行期门）；
- 日志只落计数与标志位，不落凭据与原始行全文；异常文本进 reason/日志前一律打码；
- 每操作开短连接、用毕即关（只读短事务纪律），close() 无长持句柄。

已知边界（如实登记）：水位值 json 编码进 token（int/float/str 原生；datetime 列
编码前转 ISO 字符串，同批混型由 max(repr) 兜底）；游标不可解析回退全量快照，
幂等由咽喉内容键去重兜底（B14 语义，连接器只遵守不改造）。
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import importlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import quote

from .protocols import ChangeBatch, SourceCursor, SourceHealth, SourceSchema
from .schema_mapping import MappingError, VARIANT_CLOSED_SETS

logger = logging.getLogger(__name__)

#: 驱动模块映射（闭集与 VARIANT_CLOSED_SETS["sql"] 对齐；sqlite 走 stdlib 恒在）
_DRIVER_MODULES: Dict[str, str] = {
    "postgresql": "psycopg2",
    "mysql": "pymysql",
    "mssql": "pymssql",
    "oracle": "oracledb",
    "sqlite": "sqlite3",
}

#: 描述符未配 port 时各网络驱动的缺省端口
_DEFAULT_PORTS: Dict[str, int] = {
    "postgresql": 5432, "mysql": 3306, "mssql": 1433, "oracle": 1521,
}

#: fetchBatch 表路由模板（水位在场：绑定序＝水位、上限）
_FETCH_TEMPLATES: Dict[str, str] = {
    "sqlite": "SELECT {cols} FROM {table} WHERE {col} > ? ORDER BY {col} LIMIT ?",
    "postgresql": "SELECT {cols} FROM {table} WHERE {col} > %s ORDER BY {col} LIMIT %s",
    "mysql": "SELECT {cols} FROM {table} WHERE {col} > %s ORDER BY {col} LIMIT %s",
    "mssql": "SELECT {cols} FROM {table} WHERE {col} > %s ORDER BY {col}"
             " OFFSET 0 ROWS FETCH FIRST %s ROWS ONLY",
    "oracle": "SELECT {cols} FROM {table} WHERE {col} > :1 ORDER BY {col}"
              " FETCH FIRST :2 ROWS ONLY",
}

#: fetchBatch 表路由模板（首轮全量快照：无 WHERE，绑定序＝上限）
_FETCH_TEMPLATES_FIRST: Dict[str, str] = {
    "sqlite": "SELECT {cols} FROM {table} ORDER BY {col} LIMIT ?",
    "postgresql": "SELECT {cols} FROM {table} ORDER BY {col} LIMIT %s",
    "mysql": "SELECT {cols} FROM {table} ORDER BY {col} LIMIT %s",
    "mssql": "SELECT {cols} FROM {table} ORDER BY {col}"
             " OFFSET 0 ROWS FETCH FIRST %s ROWS ONLY",
    "oracle": "SELECT {cols} FROM {table} ORDER BY {col} FETCH FIRST :1 ROWS ONLY",
}

#: describeSchema 目录查询（每驱动一小段；统一 (table_name, column_name, data_type) 形状）
_SCHEMA_QUERIES: Dict[str, Tuple[str, tuple]] = {
    "sqlite": (
        "SELECT m.name AS table_name, p.name AS column_name, p.type AS data_type"
        " FROM sqlite_master m, pragma_table_info(m.name) p"
        " WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%'"
        " ORDER BY m.name, p.cid", ()),
    "postgresql": (
        "SELECT table_name, column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = 'public' ORDER BY table_name, ordinal_position", ()),
    "mysql": (
        "SELECT table_name, column_name, column_type AS data_type"
        " FROM information_schema.columns WHERE table_schema = DATABASE()"
        " ORDER BY table_name, ordinal_position", ()),
    "mssql": (
        "SELECT table_name, column_name, data_type FROM information_schema.columns"
        " ORDER BY table_name, ordinal_position", ()),
    "oracle": (
        "SELECT table_name, column_name, data_type FROM user_tab_columns"
        " ORDER BY table_name, column_id", ()),
}

#: 探活语句（五驱动通用）
_HEALTH_PROBE_SQL = "SELECT 1"

#: 只读查询首词白名单（query 路由）
_READONLY_LEADING = ("select", "with", "explain", "show")

#: 写意图关键词：词边界匹配，query 里出现即拒（边界保守从紧：REPLACE 亦可作
#: 字符串函数，v1 按写意图拒，宁拒勿放）
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|merge|grant|revoke|replace|"
    r"call|exec|execute|attach|detach|pragma|vacuum|reindex|into)\b", re.IGNORECASE)

#: 标识符白名单（值一律参数化；名字只允许字母数字下划线，表名可带一个 schema 点）
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TABLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")

#: 单批行数上限钳制（协议义务具名化，ERP 连接器同款常量）
_MAX_BATCH_LIMIT = 500


class DriverNotInstalledError(RuntimeError):
    """可选驱动未安装：health 显式点名，fetch/describe 如实抛（不吞成空批）。"""


def _encodeWmValue(value: Any) -> str:
    """水位值 → token 载荷（json 编码：int/float/str 原生，类型可逆）。"""
    return json.dumps(value, ensure_ascii=False, default=repr)


class SqlDirectAdapter:
    """`sourceType=sql` 的 Protocol 实现（driver ∈ 五闭集，协议四动词）。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str = "default") -> None:
        self._descriptor = dict(descriptor or {})
        self._sourceId = str(sourceId)
        self._tenantId = str(tenantId or "default")

        # 适配器自守契约：工厂只查变体在场，闭集由实现自己把关（ERP 连接器同款）
        _closedField, closed = VARIANT_CLOSED_SETS["sql"]
        self._driver = str(self._descriptor.get("driver") or "")
        if self._driver not in closed:
            raise MappingError("sql.driver %r 不在闭集（%s）"
                               % (self._driver, " / ".join(closed)))
        # 凭据绝不进描述符：明文口令键在场即拒（补偿④，描述符只放变量名/密文）
        if "password" in self._descriptor or "secret" in self._descriptor:
            raise MappingError(
                "描述符不放口令明文——用 credentialEnv（环境变量名）或 passwordEncrypted（密文）")
        self._credentialEnv = {str(k): str(v) for k, v in
                               (self._descriptor.get("credentialEnv") or {}).items()}
        self._passwordEncrypted = str(self._descriptor.get("passwordEncrypted") or "")

        self._host = str(self._descriptor.get("host") or "")
        self._port = self._descriptor.get("port")
        self._database = str(self._descriptor.get("database") or "")

        self._cursorColumn = str(self._descriptor.get("cursorColumn") or "").strip()
        self._watermarkType = str(descriptor.get("watermarkType") or "integer").strip().lower()
        if not self._cursorColumn or not _IDENTIFIER.match(self._cursorColumn):
            raise MappingError("cursorColumn 标识符 %r 缺失或不合法（水位增量列，"
                               "只允许字母数字下划线）" % self._descriptor.get("cursorColumn"))

        query = str(self._descriptor.get("query") or "").strip()
        table = str(self._descriptor.get("table") or "").strip()
        if query and table:
            raise MappingError("query 与 table 二选一，不给两个")
        if query:
            self._route = "query"
            self._queryTemplate = query
            self._table = ""
            self._validateReadonlyQuery(query)
        elif table:
            self._route = "table"
            self._queryTemplate = ""
            self._table = table
            if not _TABLE_IDENTIFIER.match(table):
                raise MappingError("表名标识符 %r 不合法（只允许字母数字下划线与一个 schema 点）"
                                   % table)
        else:
            raise MappingError("sql 源缺 query 或 table（二选一）")

        self._columns = [str(c).strip() for c in (self._descriptor.get("columns") or [])]
        for column in self._columns:
            if not _IDENTIFIER.match(column):
                raise MappingError("列标识符 %r 不合法（只允许字母数字下划线）" % column)

        if self._driver == "sqlite":
            if not self._database:
                raise MappingError("sqlite 驱动缺 database（旁库文件路径）")
        else:
            if not self._host:
                raise MappingError("sql 源缺 host（网络驱动必配）")
            if not self._database:
                raise MappingError("sql 源缺 database（网络驱动必配）")

    # ── Protocol 四动词 ──────────────────────────────────────

    async def describeSchema(self) -> SourceSchema:
        return await asyncio.to_thread(self._describeSync)

    async def fetchBatch(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch:
        limit = max(1, min(int(limit), _MAX_BATCH_LIMIT))
        return await asyncio.to_thread(self._fetchSync, cursor, limit)

    async def health(self) -> SourceHealth:
        return await asyncio.to_thread(self._healthSync)

    async def close(self) -> None:
        """本适配器按操作开短连接（只读短事务纪律），无长持句柄可关。"""
        return None

    # ── 拉取（水位增量）─────────────────────────────────────

    def _fetchSync(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch:
        watermark = self._decodeWatermark(cursor)
        sql, params = self._buildFetchSql(watermark, limit + 1)
        with self._openCursor(sql, params) as cursorHandle:
            raw = cursorHandle.fetchall()
            description = cursorHandle.description
        rows = self._normalizeRows(description, raw)
        hasMore = len(rows) > limit
        if hasMore:
            rows = rows[:limit]
        nextCursor = None
        maxWatermark = self._maxWatermark(rows)
        if maxWatermark is not None:
            nextCursor = SourceCursor("wm=%s" % _encodeWmValue(maxWatermark))
        logger.debug("sql[%s/%s] fetch rows=%d hasMore=%s cursor=%s",
                     self._driver, self._sourceId, len(rows), hasMore,
                     "set" if nextCursor is not None else "none")
        return ChangeBatch(rows=rows, nextCursor=nextCursor, hasMore=hasMore)

    def _watermarkCondition(self) -> str:
        """W11 边界等值（specs/2026-11-12 §12）：timestamp 类型用 >=（防漏——
        同水位多行不跳过），integer 类型保持 >（唯一值不漏不重）。
        未声明 watermarkType 的存量行为零漂移（回退 integer → >）。"""
        if self._watermarkType == "timestamp":
            return ">="
        return ">"

    def _buildFetchSql(self, watermark: Optional[Any],
                       boundLimit: int) -> Tuple[str, Tuple[Any, ...]]:
        """组装取数 SQL：值一律参数化，名字全部来自已过白名单的标识符。"""
        if self._route == "table":
            fills = {"cols": ", ".join(self._columns) if self._columns else "*",
                     "table": self._table, "col": self._cursorColumn}
            if watermark is not None:
                template = _FETCH_TEMPLATES[self._driver]
                if self._watermarkCondition() == ">=":
                    template = template.replace(" > ", " >= ")
                return template.format(**fills), (watermark, boundLimit)
            return _FETCH_TEMPLATES_FIRST[self._driver].format(**fills), (boundLimit,)
        # query 路由：槽位参数化注入（绑定序固定 {wmCond} → {lim}）
        binds: List[Any] = []
        if watermark is not None:
            condition = "%s %s %s" % (self._cursorColumn, self._watermarkCondition(),
                                      self._nextMarker(binds))
            binds.append(watermark)
        else:
            condition = "1=1"  # 首轮全量快照
        sql = self._queryTemplate.replace("{wmCond}", condition)
        sql = sql.replace("{lim}", self._nextMarker(binds))
        binds.append(boundLimit)
        return sql, tuple(binds)

    def _nextMarker(self, binds: List[Any]) -> str:
        """按驱动 paramstyle 出下一个绑定占位符（oracle 数字位与绑定序一致）。"""
        if self._driver == "sqlite":
            return "?"
        if self._driver == "oracle":
            return ":%d" % (len(binds) + 1)
        return "%s"

    def _decodeWatermark(self, cursor: Optional[SourceCursor]) -> Optional[Any]:
        """token "wm=<json>" → 水位值；空/缺/不可解析 → None（回退全量快照）。

        回退不报错：幂等由咽喉内容键去重兜底（B14 语义），重放不产生重复事实。
        """
        if cursor is None or cursor.isEmpty():
            return None
        token = str(cursor.token or "")
        if not token.startswith("wm="):
            logger.warning("sql[%s/%s] 游标不可解析（非 wm= 形状），回退全量快照",
                           self._driver, self._sourceId)
            return None
        try:
            return json.loads(token[3:])
        except ValueError:
            logger.warning("sql[%s/%s] 游标水位不可解析，回退全量快照",
                           self._driver, self._sourceId)
            return None

    def _maxWatermark(self, rows: List[Dict[str, Any]]) -> Optional[Any]:
        values = [self._normalizeWmValue(row.get(self._cursorColumn)) for row in rows]
        values = [v for v in values if v is not None]
        if not values:
            return None
        try:
            return max(values)
        except TypeError:
            return max(values, key=repr)  # 同批混型兜底，不炸批

    @staticmethod
    def _normalizeWmValue(value: Any) -> Any:
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            return value.isoformat()
        return value

    @staticmethod
    def _normalizeRows(description: Any, raw: Any) -> List[Dict[str, Any]]:
        """DBAPI 行（tuple/Row/dict）→ 列 dict 行（按 cursor.description 列名）。"""
        if not description:
            return []
        names = [d[0] for d in description]
        rows: List[Dict[str, Any]] = []
        for record in raw or []:
            if isinstance(record, dict):
                rows.append(record)
            else:
                rows.append({names[i]: (record[i] if i < len(record) else None)
                             for i in range(len(names))})
        return rows

    # ── schema 推导 ─────────────────────────────────────────

    def _describeSync(self) -> SourceSchema:
        sql, params = _SCHEMA_QUERIES[self._driver]
        with self._openCursor(sql, params) as cursorHandle:
            raw = cursorHandle.fetchall()
        tables: Dict[str, List[Dict[str, Any]]] = {}
        for record in raw:
            if isinstance(record, dict):
                tableName = str(record.get("table_name", ""))
                columnName = str(record.get("column_name", ""))
                dataType = str(record.get("data_type", ""))
            else:
                tableName = str(record[0])
                columnName = str(record[1])
                dataType = str(record[2]) if len(record) > 2 else ""
            tables.setdefault(tableName, []).append({"name": columnName, "type": dataType})
        schemaTables = [{"name": name, "columns": tables[name]} for name in sorted(tables)]
        logger.debug("sql[%s/%s] describe tables=%d",
                     self._driver, self._sourceId, len(schemaTables))
        return SourceSchema(sourceId=self._sourceId, sourceType="sql", tables=schemaTables)

    # ── 健康（显式三态，失败点名）───────────────────────────

    def _healthSync(self) -> SourceHealth:
        try:
            self._importDriver()
        except DriverNotInstalledError as exc:
            return self._healthError(str(exc))
        if self._driver == "sqlite" and not Path(self._database).exists():
            return self._healthError("sqlite 旁库文件不存在: %s" % self._database)
        try:
            conn = self._connect()
        except Exception as exc:  # noqa: BLE001 - 健康探测失败如实点名，不静默 ok
            return self._healthError("连接失败: %s: %s"
                                     % (type(exc).__name__, self._redact(str(exc))))
        try:
            probe = conn.cursor()
            try:
                probe.execute(_HEALTH_PROBE_SQL, ())
                probe.fetchall()
            finally:
                probe.close()
        except Exception as exc:  # noqa: BLE001
            return self._healthError("探活失败: %s: %s"
                                     % (type(exc).__name__, self._redact(str(exc))))
        finally:
            conn.close()
        logger.debug("sql[%s/%s] health ok", self._driver, self._sourceId)
        return SourceHealth(status="ok")

    def _healthError(self, reason: str) -> SourceHealth:
        logger.warning("sql[%s/%s] health error: %s", self._driver, self._sourceId, reason)
        return SourceHealth(status="error", reason=reason)

    # ── 连接（惰性 import＋短连接）──────────────────────────

    def _importDriver(self) -> Any:
        moduleName = _DRIVER_MODULES[self._driver]
        try:
            return importlib.import_module(moduleName)
        except ImportError as exc:
            raise DriverNotInstalledError("driver not installed: %s" % moduleName) from exc

    def _connect(self) -> Any:
        module = self._importDriver()
        if self._driver == "sqlite":
            uri = "file:%s?mode=ro" % quote(Path(self._database).as_posix(), safe="/:")
            return module.connect(uri, uri=True)  # 只读独立连接，绝不 ATTACH 主库
        return module.connect(**self._connectKwargs())

    def _connectKwargs(self) -> Dict[str, Any]:
        creds = self._resolveCredentials()
        port = int(self._port) if self._port else _DEFAULT_PORTS.get(self._driver, 0)
        kwargs: Dict[str, Any] = {}
        if self._driver == "postgresql":
            kwargs.update(host=self._host, port=port, dbname=self._database)
        elif self._driver == "mysql":
            kwargs.update(host=self._host, port=port, database=self._database)
        elif self._driver == "mssql":
            kwargs.update(server=self._host, port=port, database=self._database)
        elif self._driver == "oracle":
            kwargs.update(dsn=str(self._descriptor.get("dsn")
                                  or "%s:%s/%s" % (self._host, port, self._database)))
        user = creds.get("user", "")
        password = creds.get("password", "")
        if user:
            kwargs["user"] = user
        if password:
            kwargs["password"] = password
        return kwargs

    @contextlib.contextmanager
    def _openCursor(self, sql: str, params: Sequence[Any]) -> Iterator[Any]:
        """短连接短事务：开连接→execute→yield 游标→游标与连接用毕即关。"""
        conn = self._connect()
        try:
            cursorHandle = conn.cursor()
            try:
                cursorHandle.execute(sql, tuple(params))
                yield cursorHandle
            finally:
                cursorHandle.close()
        finally:
            conn.close()

    # ── 凭据（仓内设施＋环境变量，值不落任何输出面）─────────

    def _resolveCredentials(self) -> Dict[str, str]:
        """credentialEnv（字段→环境变量名）＋ passwordEncrypted（NEUROVA_KB_SECRET 解密）。

        描述符只放变量名/密文；解析出的值只进连接参数与打码清单，
        绝不进日志、描述符、reason 或任何返回值。
        """
        resolved: Dict[str, str] = {}
        for field, envName in self._credentialEnv.items():
            value = os.environ.get(envName, "")
            if value:
                resolved[field] = value
        if self._passwordEncrypted:
            from neurova.knowledge.storage import decryptSecret  # 仓内唯一解密设施（公开名，惰性）

            password = decryptSecret(self._passwordEncrypted)
            if password:
                resolved["password"] = password
        return resolved

    def _redact(self, text: str) -> str:
        """异常文本进 reason/日志前的单点打码：已解析凭据值一律替换为 ***。"""
        out = str(text)
        for value in self._resolveCredentials().values():
            if value:
                out = out.replace(value, "***")
        return out

    # ── 只读边界（写意图显式拒绝）───────────────────────────

    def _validateReadonlyQuery(self, query: str) -> None:
        """query 路由只收只读形状：首词白名单＋写关键词扫描＋禁多语句/注释拼接＋槽位强制。"""
        parts = query.split(None, 1)
        leading = parts[0].lower() if parts else ""
        if leading not in _READONLY_LEADING:
            raise MappingError("query 只允许只读形状（%s 开头），%r 不是——写意图显式拒绝"
                               % (" / ".join(_READONLY_LEADING), leading))
        if ";" in query or "--" in query or "/*" in query:
            raise MappingError("query 不允许多语句与注释拼接形状（; -- /*）——只读边界")
        hit = _WRITE_KEYWORDS.search(query)
        if hit:
            raise MappingError("query 含写意图关键词 %r——只读边界，显式拒绝" % hit.group(0))
        if "{wmCond}" not in query:
            raise MappingError(
                "query 模板缺 {wmCond} 槽位——水位条件由适配器参数化注入（首轮自动 1=1）")
        if "{lim}" not in query:
            raise MappingError("query 模板缺 {lim} 槽位——单批上限是 fetchBatch 的协议义务")
