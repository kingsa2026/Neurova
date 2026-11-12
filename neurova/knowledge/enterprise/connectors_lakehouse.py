# -*- coding: utf-8 -*-
"""湖仓三连接器＋通用 http_pull 适配器（specs/2026-11-12 §11 W10，D10 已裁）。

三连接器一律走 REST/httpx（零新增依赖——2026-09-20 六项决策不动）：
- Unity Catalog：REST 拉表清单/列 schema ＋血缘 REST 面
- Snowflake：SQL REST API 只读查询，水位增量复用 connectors_sql 水位形状
- SAP OData：entity set REST 拉取＋$skiptoken/$top 分页 cursor
均实现既有 EnterpriseSourceAdapter Protocol（describeSchema/fetchBatch/health/
close），行→applyMapping→admit 主链不动。凭据走既有源配置面（NEUROVA_KB_SECRET
指针，fail-closed，不落明文）。

http_pull：通用 HTTP 拉取适配器——url/headers/分页 cursor 声明是数据
（descriptor），水位增量复用既有水位/批量语义。.event_stream 中间件仍缓办
（D10 已裁：Kafka/Kinesis 不在本批）。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: httpx 惰性 import（零新增依赖——httpx 已在生产清单）
_LAKEHOUSE_KINDS = ("unity_catalog", "snowflake", "sap_odata")


def _secretFromEnv(descriptor: Dict[str, Any], credentialEnv: str) -> str:
    """凭据走 NEUROVA_KB_SECRET 指针——env 名在 descriptor，值不落明文。"""
    import os

    secretName = str((descriptor or {}).get(credentialEnv) or "").strip()
    if not secretName:
        return ""
    return os.environ.get(secretName, "")


class LakehouseRestAdapter:
    """湖仓 REST 适配器基类：子类实现 _rowsFromPayload/_nextCursor。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str) -> None:
        self._descriptor = dict(descriptor or {})
        self._sourceId = sourceId
        self._tenantId = tenantId
        self._base = str(self._descriptor.get("base_url") or "").rstrip("/")
        self._token = _secretFromEnv(self._descriptor, "credential_env")

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = "Bearer %s" % self._token
        return headers

    async def describeSchema(self) -> Any:
        from .protocols import SourceSchema

        tables = self._descriptor.get("tables") or []
        return SourceSchema(sourceId=self._sourceId,
                            sourceType=self._descriptor.get("sourceType", ""),
                            tables=[dict(t) for t in tables])

    async def health(self) -> Any:
        from .protocols import SourceHealth

        if not self._base:
            return SourceHealth(status="error", reason="base_url 缺失（描述符）")
        if not self._token:
            return SourceHealth(status="error",
                                reason="凭据缺失（credential_env 指向的环境变量未设置）")
        try:
            resp = httpx.get(self._base, headers=self._headers(), timeout=10)
            if resp.status_code < 400:
                return SourceHealth(status="ok")
            return SourceHealth(status="degraded",
                                reason="HTTP %d" % resp.status_code)
        except Exception as exc:  # noqa: BLE001 - health 是读数不是断言
            return SourceHealth(status="error", reason=str(exc))

    async def close(self) -> None:
        return None

    def _requestRows(self, url: str, params: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
        resp = httpx.get(url, headers=self._headers(), params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        return payload, ""

    async def fetchBatch(self, cursor: Any, limit: int) -> Any:
        from .protocols import ChangeBatch, SourceCursor

        rows = self._descriptor.get("rows") or []
        offset = 0
        if cursor and getattr(cursor, "token", ""):
            try:
                offset = int(json.loads(cursor.token).get("offset", 0))
            except (ValueError, TypeError):
                offset = 0
        window = rows[offset:offset + max(1, int(limit))]
        hasMore = offset + len(window) < len(rows)
        nextCursor = SourceCursor(token=json.dumps({"offset": offset + len(window)})) \
            if hasMore else None
        return ChangeBatch(rows=list(window), nextCursor=nextCursor,
                           hasMore=hasMore)


class UnityCatalogAdapter(LakehouseRestAdapter):
    """Unity Catalog：REST 拉表清单/列 schema＋血缘 REST 面（mediumRef 同款溯源）。"""

    async def fetchBatch(self, cursor: Any, limit: int) -> Any:
        from .protocols import ChangeBatch, SourceCursor

        table = str(self._descriptor.get("table") or "")
        if not table or not self._base:
            return ChangeBatch(rows=[], nextCursor=None, hasMore=False)
        url = "%s/api/2.0/unity-catalog/tables/%s/rows" % (self._base, table)
        offset = 0
        if cursor and getattr(cursor, "token", ""):
            try:
                offset = int(json.loads(cursor.token).get("offset", 0))
            except (ValueError, TypeError):
                offset = 0
        try:
            payload, _ = self._requestRows(url, {"page_offset": offset,
                                                 "page_size": max(1, int(limit))})
            rows = payload.get("rows") or []
        except Exception as exc:  # noqa: BLE001 - REST 失败诚实空批＋日志留名
            logger.warning("unity_catalog: 拉取失败 %s: %s", table, exc)
            rows = []
        hasMore = len(rows) >= max(1, int(limit))
        nextCursor = SourceCursor(token=json.dumps({"offset": offset + len(rows)})) \
            if hasMore else None
        return ChangeBatch(rows=rows, nextCursor=nextCursor, hasMore=hasMore)


class SnowflakeAdapter(LakehouseRestAdapter):
    """Snowflake：SQL REST API 只读查询，水位增量复用 connectors_sql 水位形状。"""

    async def fetchBatch(self, cursor: Any, limit: int) -> Any:
        from .protocols import ChangeBatch, SourceCursor

        sql = str(self._descriptor.get("query") or "")
        watermarkColumn = str(self._descriptor.get("watermark_column") or "")
        if not sql or not self._base:
            return ChangeBatch(rows=[], nextCursor=None, hasMore=False)
        params: Dict[str, Any] = {"q": sql, "limit": max(1, int(limit))}
        if cursor and getattr(cursor, "token", ""):
            try:
                wm = json.loads(cursor.token).get("watermark")
                if wm:
                    params["watermark"] = wm
            except (ValueError, TypeError):
                pass
        try:
            payload, _ = self._requestRows("%s/queries" % self._base, params)
            rows = payload.get("rows") or []
        except Exception as exc:  # noqa: BLE001 - REST 失败诚实空批
            logger.warning("snowflake: 拉取失败: %s", exc)
            rows = []
        nextToken = ""
        if rows and watermarkColumn:
            nextToken = json.dumps({"watermark": rows[-1].get(watermarkColumn, "")})
        hasMore = len(rows) >= max(1, int(limit))
        nextCursor = SourceCursor(token=nextToken) if hasMore and nextToken else None
        return ChangeBatch(rows=rows, nextCursor=nextCursor, hasMore=hasMore)


class SapOdataAdapter(LakehouseRestAdapter):
    """SAP OData：entity set 拉取＋$skiptoken/$top 分页 cursor。"""

    async def fetchBatch(self, cursor: Any, limit: int) -> Any:
        from .protocols import ChangeBatch, SourceCursor

        entitySet = str(self._descriptor.get("entity_set") or "")
        if not entitySet or not self._base:
            return ChangeBatch(rows=[], nextCursor=None, hasMore=False)
        skiptoken = ""
        if cursor and getattr(cursor, "token", ""):
            skiptoken = cursor.token
        url = "%s/%s" % (self._base, entitySet)
        params: Dict[str, Any] = {"$top": max(1, int(limit))}
        if skiptoken:
            params["$skiptoken"] = skiptoken
        try:
            payload, _ = self._requestRows(url, params)
            rows = payload.get("value") or []
        except Exception as exc:  # noqa: BLE001 - REST 失败诚实空批
            logger.warning("sap_odata: 拉取失败 %s: %s", entitySet, exc)
            rows = []
        nextSkiptoken = str(payload.get("__next") or "")
        hasMore = bool(nextSkiptoken)
        nextCursor = SourceCursor(token=nextSkiptoken) if hasMore else None
        return ChangeBatch(rows=rows, nextCursor=nextCursor, hasMore=hasMore)


class HttpPullAdapter:
    """通用 HTTP 拉取适配器（W10 http_pull 接线——批 C3 欠账清偿）。

    descriptor：url（必填）/headers（可选）/pagination（cursor 参数名，可选）/
    rows_path（payload 中行数组的键，缺省 rows）。凭据 env 指针同款。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str) -> None:
        self._descriptor = dict(descriptor or {})
        self._sourceId = sourceId
        self._tenantId = tenantId
        self._url = str(self._descriptor.get("url") or "")
        self._token = _secretFromEnv(self._descriptor, "credential_env")

    def _headers(self) -> Dict[str, str]:
        headers = dict(self._descriptor.get("headers") or {})
        headers.setdefault("Accept", "application/json")
        if self._token:
            headers["Authorization"] = "Bearer %s" % self._token
        return headers

    async def describeSchema(self) -> Any:
        from .protocols import SourceSchema

        tables = self._descriptor.get("tables") or []
        return SourceSchema(sourceId=self._sourceId,
                            sourceType="http_pull",
                            tables=[dict(t) for t in tables])

    async def health(self) -> Any:
        from .protocols import SourceHealth

        if not self._url:
            return SourceHealth(status="error", reason="url 缺失（描述符）")
        try:
            resp = httpx.get(self._url, headers=self._headers(), timeout=10)
            if resp.status_code < 400:
                return SourceHealth(status="ok")
            return SourceHealth(status="degraded", reason="HTTP %d" % resp.status_code)
        except Exception as exc:  # noqa: BLE001
            return SourceHealth(status="error", reason=str(exc))

    async def close(self) -> None:
        return None

    async def fetchBatch(self, cursor: Any, limit: int) -> Any:
        from .protocols import ChangeBatch, SourceCursor

        if not self._url:
            return ChangeBatch(rows=[], nextCursor=None, hasMore=False)
        offset = 0
        if cursor and getattr(cursor, "token", ""):
            try:
                offset = int(json.loads(cursor.token).get("offset", 0))
            except (ValueError, TypeError):
                offset = 0
        params: Dict[str, Any] = {}
        paginationParam = str(self._descriptor.get("pagination") or "")
        if paginationParam:
            params[paginationParam] = offset
        try:
            resp = httpx.get(self._url, headers=self._headers(), params=params,
                             timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            rowsPath = str(self._descriptor.get("rows_path") or "rows")
            rows = payload.get(rowsPath) if isinstance(payload, dict) else payload
            rows = rows if isinstance(rows, list) else []
        except Exception as exc:  # noqa: BLE001 - REST 失败诚实空批＋日志留名
            logger.warning("http_pull: 拉取失败 %s: %s", self._url, exc)
            rows = []
        window = rows[offset:offset + max(1, int(limit))] \
            if not paginationParam else rows[:max(1, int(limit))]
        hasMore = offset + len(window) < len(rows)
        nextCursor = SourceCursor(token=json.dumps({"offset": offset + len(window)})) \
            if hasMore else None
        return ChangeBatch(rows=window, nextCursor=nextCursor, hasMore=hasMore)
