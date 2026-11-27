# -*- coding: utf-8 -*-
"""schema 目录自动摄取（对照研究 P1-1，2026-11-15）。

企业源适配器的 `describeSchema()` 此前五驱动已实现但全仓零生产调用——
「数据源里有什么表/列/键」这件事没有一处落账。本模块把 schema 自省接进
生产链：源注册与显式刷新时拉取目录，落 `ontology_catalog_tables` /
`ontology_catalog_columns`（v51），作为术语建议（P1-2）、就绪探针（P2-2）
与 NL2SQL grounding（P1-4）的唯一数据入口。

边界：
- 只读元数据，零行数据采样（采样属 P1-2 数据证实批，按源显式开）；
- 目录是缓存不是事实源：源端 schema 变化以 refresh 为准（同源整体替换）；
  删除源配置不级联删目录行，读面按现役配置归并；
- 外键/主键来自 `describeRelations()`（可选能力，SQL 适配器实现；其余源空表）；
- 表/列到本体术语的链接（term_id）只由 P1-2 建议审批流写入，摄取不清空它
  ——重摄取按稳定 id 覆盖元数据列，term_id 列原样保留。
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional

from neurova.core.time_utils import nowIso as _now
from neurova.core.tenant_scope import tenant_sql_where

#: v51：schema 目录两表。term_id 是 P1-2 审批通过后回填的本体链接；
#: 摄取本身永远写空它（机器不替人拍板）。
_SCHEMA_V51_CATALOG = """
CREATE TABLE IF NOT EXISTS ontology_catalog_tables (
    catalog_table_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT '',
    table_schema TEXT NOT NULL DEFAULT '',
    table_name TEXT NOT NULL,
    table_type TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    term_id TEXT NOT NULL DEFAULT '',
    column_count INTEGER NOT NULL DEFAULT 0,
    ingested_at TEXT NOT NULL,
    UNIQUE(tenant_id, source_id, table_schema, table_name)
);
CREATE INDEX IF NOT EXISTS idx_catalog_tables_tenant
    ON ontology_catalog_tables(tenant_id, source_id, table_name);
CREATE TABLE IF NOT EXISTS ontology_catalog_columns (
    catalog_column_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT 'default',
    source_id TEXT NOT NULL,
    catalog_table_id TEXT NOT NULL,
    column_name TEXT NOT NULL,
    data_type TEXT NOT NULL DEFAULT '',
    ordinal_position INTEGER,
    is_primary_key INTEGER NOT NULL DEFAULT 0,
    is_foreign_key INTEGER NOT NULL DEFAULT 0,
    foreign_key_target TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    term_id TEXT NOT NULL DEFAULT '',
    ingested_at TEXT NOT NULL,
    UNIQUE(tenant_id, catalog_table_id, column_name)
);
CREATE INDEX IF NOT EXISTS idx_catalog_columns_table
    ON ontology_catalog_columns(tenant_id, catalog_table_id, ordinal_position);
CREATE INDEX IF NOT EXISTS idx_catalog_columns_name
    ON ontology_catalog_columns(tenant_id, column_name);
"""

#: v59（U10 连接器列画像，2026-11-23）：目录列表只增列，不建第二套目录。
#: NULL / sample_rows=0 / samples='[]' ＝未采样（file/chat 等无行数据连接的
#: 源型如实缺席，不冒充 0 值画像）。min/max 以文本归一（connectors_sql
#: ._profileText 口径），样例值是 JSON 数组（≤5 个）。
_SCHEMA_V59_COLUMN_PROFILE = """
ALTER TABLE ontology_catalog_columns ADD COLUMN profile_distinct INTEGER;
ALTER TABLE ontology_catalog_columns ADD COLUMN profile_null_rate REAL;
ALTER TABLE ontology_catalog_columns ADD COLUMN profile_min TEXT;
ALTER TABLE ontology_catalog_columns ADD COLUMN profile_max TEXT;
ALTER TABLE ontology_catalog_columns ADD COLUMN profile_samples_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE ontology_catalog_columns ADD COLUMN profile_sample_rows INTEGER NOT NULL DEFAULT 0;
"""


def _tableId(tenantId: str, sourceId: str, tableSchema: str, tableName: str) -> str:
    raw = "|".join([tenantId, sourceId, tableSchema, tableName])
    return "cat_t_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _columnId(tenantId: str, tableId: str, columnName: str) -> str:
    raw = "|".join([tenantId, tableId, columnName])
    return "cat_c_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class SchemaCatalogStore:
    """`ontology_catalog_tables/_columns` 的唯一读写面（单一事实源）。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        from ..foundation.foundation_schema import applyTo

        with self._store._lock, self._store._conn:
            applyTo(self._store._conn)

    # ── 写入（整体替换）─────────────────────────────────────

    def ingestSchema(self, tenantId: str, sourceId: str, sourceType: str,
                     schema: Any, relations: Optional[Dict[str, Any]] = None,
                     profiles: Optional[Dict[str, Dict[str, Dict[str, Any]]]] = None
                     ) -> Dict[str, int]:
        """一份 SourceSchema 落目录：同 (租户, 源) 差量更新后清除陈旧表列。

        仍存在的稳定 ID 只覆盖元数据与画像，保留审批写入的 term_id。

        relations 形状：{"foreign_keys": [{source_table, source_column,
        target_table, target_column}], "primary_keys": {table: [col, ...]}}；
        缺省（适配器无 describeRelations 能力）按无键处理，如实落 0。

        profiles 形状（U10，缺省＝未采样）：{table_name: {column_name: 画像}}，
        画像键与 ontology_catalog_columns 的 v59 列同名（computeColumnProfiles
        的产出原样落账）；未给出的列画像列落缺省（distinct NULL、行数 0）。
        """
        tenant = str(tenantId or "default")
        source = str(sourceId or "")
        relations = relations or {}
        profiles = profiles or {}
        foreignKeys = list(relations.get("foreign_keys") or [])
        primaryKeys = dict(relations.get("primary_keys") or {})
        stamp = _now()
        tables = list(getattr(schema, "tables", None) or [])
        tableCount = 0
        columnCount = 0
        fkCount = 0
        with self._store._lock, self._store._conn:
            tenantClause, tenantParams = tenant_sql_where(tenant)
            existingTables = {str(row[0]) for row in self._store._conn.execute(
                "SELECT catalog_table_id FROM ontology_catalog_tables"
                " WHERE %s AND source_id = ?" % tenantClause,
                (*tenantParams, source)).fetchall()}
            existingColumns = {str(row[0]) for row in self._store._conn.execute(
                "SELECT catalog_column_id FROM ontology_catalog_columns"
                " WHERE %s AND source_id = ?" % tenantClause,
                (*tenantParams, source)).fetchall()}
            retainedTables = set()
            retainedColumns = set()
            for table in tables:
                tableName = str(table.get("name") or "").strip()
                if not tableName:
                    continue
                tableId = _tableId(tenant, source, "", tableName)
                columns = list(table.get("columns") or [])
                pkColumns = {str(c) for c in (primaryKeys.get(tableName) or [])}
                self._store._conn.execute(
                    "INSERT INTO ontology_catalog_tables"
                    " (catalog_table_id, tenant_id, source_id, source_type, table_schema,"
                    "  table_name, table_type, description, term_id, column_count, ingested_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(catalog_table_id) DO UPDATE SET"
                    " source_type=excluded.source_type, table_schema=excluded.table_schema,"
                    " table_name=excluded.table_name, table_type=excluded.table_type,"
                    " description=excluded.description, column_count=excluded.column_count,"
                    " ingested_at=excluded.ingested_at",
                    (tableId, tenant, source, str(sourceType or ""), "",
                     tableName, str(table.get("table_type") or ""),
                     str(table.get("description") or ""), "",
                     len(columns), stamp),
                )
                retainedTables.add(tableId)
                tableCount += 1
                for position, column in enumerate(columns):
                    # 适配器列形状两态并存：SQL 族是 {name, type}，文件族是裸列名
                    # 字符串。目录层归一，不要求适配器改形状。
                    if isinstance(column, dict):
                        columnName = str(column.get("name") or "").strip()
                        dataType = str(column.get("type") or "")
                        columnDescription = str(column.get("description") or "")
                    else:
                        columnName = str(column or "").strip()
                        dataType = ""
                        columnDescription = ""
                    if not columnName:
                        continue
                    isFk = 0
                    fkTarget = ""
                    for edge in foreignKeys:
                        if (str(edge.get("source_table") or "") == tableName
                                and str(edge.get("source_column") or "") == columnName):
                            isFk = 1
                            fkTarget = "%s.%s" % (edge.get("target_table") or "",
                                                  edge.get("target_column") or "")
                            fkCount += 1
                            break
                    profile = (profiles.get(tableName) or {}).get(columnName) or {}
                    columnId = _columnId(tenant, tableId, columnName)
                    self._store._conn.execute(
                        "INSERT INTO ontology_catalog_columns"
                        " (catalog_column_id, tenant_id, source_id, catalog_table_id,"
                        "  column_name, data_type, ordinal_position, is_primary_key,"
                        "  is_foreign_key, foreign_key_target, description, term_id,"
                        "  ingested_at, profile_distinct, profile_null_rate,"
                        "  profile_min, profile_max, profile_samples_json,"
                        "  profile_sample_rows)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                        " ON CONFLICT(catalog_column_id) DO UPDATE SET"
                        " column_name=excluded.column_name, data_type=excluded.data_type,"
                        " ordinal_position=excluded.ordinal_position,"
                        " is_primary_key=excluded.is_primary_key,"
                        " is_foreign_key=excluded.is_foreign_key,"
                        " foreign_key_target=excluded.foreign_key_target,"
                        " description=excluded.description, ingested_at=excluded.ingested_at,"
                        " profile_distinct=excluded.profile_distinct,"
                        " profile_null_rate=excluded.profile_null_rate,"
                        " profile_min=excluded.profile_min, profile_max=excluded.profile_max,"
                        " profile_samples_json=excluded.profile_samples_json,"
                        " profile_sample_rows=excluded.profile_sample_rows",
                        (columnId, tenant, source, tableId,
                         columnName, dataType, position,
                         1 if columnName in pkColumns else 0,
                         isFk, fkTarget, columnDescription, "", stamp,
                         profile.get("profile_distinct"),
                         profile.get("profile_null_rate"),
                         profile.get("profile_min"),
                         profile.get("profile_max"),
                         profile.get("profile_samples_json") or "[]",
                         int(profile.get("profile_sample_rows") or 0)),
                    )
                    retainedColumns.add(columnId)
                    columnCount += 1
            for staleTable in existingTables - retainedTables:
                self._store._conn.execute(
                    "DELETE FROM ontology_catalog_columns"
                    " WHERE %s AND source_id = ? AND catalog_table_id = ?" % tenantClause,
                    (*tenantParams, source, staleTable))
                self._store._conn.execute(
                    "DELETE FROM ontology_catalog_tables"
                    " WHERE %s AND source_id = ? AND catalog_table_id = ?" % tenantClause,
                    (*tenantParams, source, staleTable))
            for staleColumn in existingColumns - retainedColumns:
                self._store._conn.execute(
                    "DELETE FROM ontology_catalog_columns"
                    " WHERE %s AND source_id = ? AND catalog_column_id = ?" % tenantClause,
                    (*tenantParams, source, staleColumn))
        return {"tables": tableCount, "columns": columnCount, "foreign_keys": fkCount}

    # ── 读取 ────────────────────────────────────────────────

    def listTables(self, tenantId: str, sourceId: str = "", q: str = "",
                   limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        tenantClause, tenantParams = tenant_sql_where(str(tenantId or "default"), alias="t")
        sql = ("SELECT t.*, (SELECT COUNT(*) FROM ontology_catalog_columns c"
               " WHERE c.tenant_id = t.tenant_id AND c.catalog_table_id = t.catalog_table_id)"
               " AS column_count FROM ontology_catalog_tables t WHERE %s" % tenantClause)
        params: List[Any] = list(tenantParams)
        if sourceId:
            sql += " AND t.source_id = ?"
            params.append(str(sourceId))
        needle = str(q or "").strip().lower()
        if needle:
            sql += " AND LOWER(t.table_name) LIKE ?"
            params.append("%" + needle + "%")
        sql += " ORDER BY t.source_id, t.table_name LIMIT ? OFFSET ?"
        params += [max(1, int(limit)), max(0, int(offset))]
        with self._store._lock:
            rows = self._store._conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def tableDetail(self, tenantId: str, tableId: str) -> Optional[Dict[str, Any]]:
        tenant = str(tenantId or "default")
        with self._store._lock:
            tenantClause, tenantParams = tenant_sql_where(tenant)
            row = self._store._conn.execute(
                "SELECT * FROM ontology_catalog_tables"
                " WHERE %s AND catalog_table_id = ?" % tenantClause,
                (*tenantParams, str(tableId or ""))).fetchone()
            if row is None:
                return None
            table = dict(row)
            table["columns"] = [dict(c) for c in self._store._conn.execute(
                "SELECT * FROM ontology_catalog_columns"
                " WHERE %s AND catalog_table_id = ?"
                " ORDER BY COALESCE(ordinal_position, 9999), column_name" % tenantClause,
                (*tenantParams, str(tableId or ""))).fetchall()]
        return table

    def search(self, tenantId: str, q: str, limit: int = 50) -> List[Dict[str, Any]]:
        """目录子串搜索（表名/列名）：规模是元数据级，LIKE + 排序足够；
        FTS5 归并见报告 P3-4 的机制注记。"""
        needle = str(q or "").strip().lower()
        if not needle:
            return []
        tenant = str(tenantId or "default")
        like = "%" + needle + "%"
        hits: List[Dict[str, Any]] = []
        with self._store._lock:
            tenantClause, tenantParams = tenant_sql_where(tenant)
            for row in self._store._conn.execute(
                    "SELECT table_name, source_id, catalog_table_id"
                    " FROM ontology_catalog_tables WHERE %s"
                    " AND LOWER(table_name) LIKE ? ORDER BY table_name LIMIT ?" % tenantClause,
                    (*tenantParams, like, int(limit))).fetchall():
                hits.append({"kind": "table", "name": row["table_name"],
                             "source_id": row["source_id"],
                             "catalog_table_id": row["catalog_table_id"]})
            colTenantClause, colTenantParams = tenant_sql_where(tenant, alias="c")
            for row in self._store._conn.execute(
                    "SELECT c.column_name, c.source_id, c.catalog_table_id, c.data_type"
                    " FROM ontology_catalog_columns c WHERE %s"
                    " AND LOWER(c.column_name) LIKE ?"
                    " ORDER BY c.column_name LIMIT ?" % colTenantClause,
                    (*colTenantParams, like, int(limit))).fetchall():
                hits.append({"kind": "column", "name": row["column_name"],
                             "source_id": row["source_id"],
                             "catalog_table_id": row["catalog_table_id"],
                             "data_type": row["data_type"]})
        # 精确前缀优先（与全局搜索体验对齐的最小排序）
        hits.sort(key=lambda h: (not str(h["name"]).lower().startswith(needle),
                                 str(h["name"]).lower()))
        return hits[:max(1, int(limit))]

    def foreignKeyEdges(self, tenantId: str, sourceId: str = "") -> List[Dict[str, Any]]:
        tenantClause, tenantParams = tenant_sql_where(str(tenantId or "default"), alias="c")
        sql = ("SELECT c.source_id, t.table_name AS source_table, c.column_name AS source_column,"
               " c.foreign_key_target FROM ontology_catalog_columns c"
               " JOIN ontology_catalog_tables t ON t.tenant_id = c.tenant_id"
               " AND t.catalog_table_id = c.catalog_table_id"
               " WHERE %s AND c.is_foreign_key = 1" % tenantClause)
        params: List[Any] = list(tenantParams)
        if sourceId:
            sql += " AND c.source_id = ?"
            params.append(str(sourceId))
        with self._store._lock:
            rows = self._store._conn.execute(sql, tuple(params)).fetchall()
        edges: List[Dict[str, Any]] = []
        for row in rows:
            targetTable, _, targetColumn = str(row["foreign_key_target"]).partition(".")
            edges.append({"source_id": row["source_id"],
                          "source_table": row["source_table"],
                          "source_column": row["source_column"],
                          "target_table": targetTable,
                          "target_column": targetColumn})
        return edges

    def counts(self, tenantId: str) -> Dict[str, int]:
        tenant = str(tenantId or "default")
        with self._store._lock:
            tenantClause, tenantParams = tenant_sql_where(tenant)
            tables = int(self._store._conn.execute(
                "SELECT COUNT(*) FROM ontology_catalog_tables WHERE %s" % tenantClause,
                tenantParams).fetchone()[0])
            columns = int(self._store._conn.execute(
                "SELECT COUNT(*) FROM ontology_catalog_columns WHERE %s" % tenantClause,
                tenantParams).fetchone()[0])
            sources = int(self._store._conn.execute(
                "SELECT COUNT(DISTINCT source_id) FROM ontology_catalog_tables"
                " WHERE %s" % tenantClause, tenantParams).fetchone()[0])
        return {"tables": tables, "columns": columns, "sources": sources}

    def sourcesInCatalog(self, tenantId: str) -> List[str]:
        with self._store._lock:
            tenantClause, tenantParams = tenant_sql_where(str(tenantId or "default"))
            rows = self._store._conn.execute(
                "SELECT DISTINCT source_id FROM ontology_catalog_tables"
                " WHERE %s ORDER BY source_id" % tenantClause,
                tenantParams).fetchall()
        return [str(r["source_id"]) for r in rows]

    # ── 术语链接（只由 P1-2 审批流调用）────────────────────

    def linkTableTerm(self, tenantId: str, tableId: str, termId: str) -> None:
        with self._store._lock, self._store._conn:
            tenantClause, tenantParams = tenant_sql_where(str(tenantId or "default"))
            self._store._conn.execute(
                "UPDATE ontology_catalog_tables SET term_id = ?"
                " WHERE %s AND catalog_table_id = ?" % tenantClause,
                (str(termId or ""), *tenantParams, str(tableId or "")))

    def linkColumnTerm(self, tenantId: str, tableId: str, columnName: str,
                       termId: str) -> None:
        with self._store._lock, self._store._conn:
            tenantClause, tenantParams = tenant_sql_where(str(tenantId or "default"))
            self._store._conn.execute(
                "UPDATE ontology_catalog_columns SET term_id = ?"
                " WHERE %s AND catalog_table_id = ? AND column_name = ?" % tenantClause,
                (str(termId or ""), *tenantParams, str(tableId or ""),
                 str(columnName or "")))
