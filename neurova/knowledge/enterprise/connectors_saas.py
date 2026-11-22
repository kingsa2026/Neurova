# -*- coding: utf-8 -*-
"""SaaS REST 连接器族（U-conn 扩展批：对齐参照系连接器矩阵）。

六家 SaaS/湖仓 SQL 服务，全部走已在依赖清单的 httpx（零新增依赖——
2026-09-20 六项决策与 W10 同判），凭据走 NEUROVA_KB_SECRET 指针纪律
（描述符只放环境变量名，值不落明文、不进日志）：

- bigquery：BigQuery REST ``projects/*/queries``——Bearer 令牌 env 指针，
  页游标 pageToken；行是 ``f/v`` 嵌套形，按 schema.fields 展平成列名字典。
- databricks：SQL Statement Execution ``api/2.0/sql/statements``——
  warehouse_id + SQL 文本，结果 data_array 按描述符 columns 展平。
- salesforce：SOQL ``services/data/v59.0/query``——游标即 nextRecordsUrl
  原文（绝对路径，下一批直取）。
- servicenow：Table API ``api/now/table/{table}``——basic auth（用户/密码
  两个 env 指针），sysparm_offset 页游标。
- looker：Looker API——``login``（client_id/client_secret 两个 env 指针）
  换 access_token 后 ``queries/{id}/run/json`` 一次取全。
- airflow：Stable REST ``api/v1/dags/{dag_id}/dagRuns``——basic auth，
  limit/offset 页游标。

均实现既有 EnterpriseSourceAdapter Protocol（describeSchema/fetchBatch/
health/close），行→applyMapping→admission 主链不动。拉取失败诚实空批＋
日志留名（W10 同款），不吞成假成功。
"""

from __future__ import annotations

import base64
import json
import threading
from typing import Any, Dict, List, Optional, Tuple

import httpx

from neurova.core.logger import get_logger
from .protocols import resolveCredentialEnv

logger = get_logger(__name__)

#: 本族全部 sourceType（protocols.SOURCE_TYPES 的扩容段；闭集单一出处）
SAAS_SOURCE_TYPES = ("bigquery", "databricks", "salesforce", "servicenow",
                     "looker", "airflow")

_BIGQUERY_DEFAULT_BASE = "https://bigquery.googleapis.com"
_SALESFORCE_API_VERSION = "v59.0"


class SaaSRestAdapter:
    """SaaS REST 适配器基类：子类实现 _fetchRows（返回 (rows, nextToken)）。

    与湖仓基类（connectors_lakehouse.LakehouseRestAdapter）同构但独立成族：
    鉴权形态多样（Bearer 指针/basic/登录换 token），_headers 由子类按凭据
    形态拼装；describeSchema/health/close 语义与湖仓一致。
    """

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str) -> None:
        self._descriptor = dict(descriptor or {})
        self._sourceId = str(sourceId)
        self._tenantId = str(tenantId or "default")
        self._base = str(self._descriptor.get("base_url") or "").rstrip("/")
        self._token = self._envValue(str(self._descriptor.get("credential_env") or ""))

    def _envValue(self, envName: str) -> str:
        import os

        envName = str(envName or "").strip()
        return os.environ.get(envName, "") if envName else ""

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = "Bearer %s" % self._token
        return headers

    def _basicAuthHeaders(self) -> Dict[str, str]:
        """credentialEnv {username, password} → Basic 授权头（任一缺省回 Bearer）。"""
        creds = resolveCredentialEnv(self._descriptor, "credentialEnv")
        user = creds.get("username", "")
        password = creds.get("password", "")
        if user and password:
            encoded = base64.b64encode(
                ("%s:%s" % (user, password)).encode()).decode()
            return {"Authorization": "Basic %s" % encoded}
        if self._token:
            return {"Authorization": "Bearer %s" % self._token}
        return {}

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

    def _requestRows(self, url: str, params: Optional[Dict[str, Any]] = None,
                     jsonBody: Optional[Dict[str, Any]] = None) -> Any:
        if jsonBody is not None:
            resp = httpx.post(url, headers=self._headers(), json=jsonBody, timeout=30)
        else:
            resp = httpx.get(url, headers=self._headers(), params=params or {},
                             timeout=30)
        resp.raise_for_status()
        return resp.json()

    async def fetchBatch(self, cursor: Any, limit: int) -> Any:
        from .protocols import ChangeBatch, SourceCursor

        token = str(getattr(cursor, "token", "") or "") if cursor else ""
        try:
            rows, nextToken = self._fetchRows(token, max(1, int(limit)))
        except Exception as exc:  # noqa: BLE001 - REST 失败诚实空批＋日志留名
            logger.warning("%s: 拉取失败 %s: %s", self._descriptor.get("sourceType"),
                           self._base, exc)
            rows, nextToken = [], ""
        rows = rows if isinstance(rows, list) else []
        hasMore = bool(nextToken) or len(rows) >= max(1, int(limit))
        nextCursor = SourceCursor(token=str(nextToken or "")) \
            if hasMore and nextToken else None
        return ChangeBatch(rows=rows, nextCursor=nextCursor, hasMore=hasMore)

    def _fetchRows(self, token: str, limit: int) -> Tuple[List[Dict[str, Any]], str]:
        raise NotImplementedError


class BigQueryAdapter(SaaSRestAdapter):
    """BigQuery REST：jobs.query——Bearer 令牌 env 指针，pageToken 页游标。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str) -> None:
        super().__init__(descriptor, sourceId, tenantId)
        if not self._base:
            self._base = _BIGQUERY_DEFAULT_BASE
        self._projectId = str(self._descriptor.get("project_id") or "")
        self._query = str(self._descriptor.get("query") or "")

    def _fetchRows(self, token: str, limit: int) -> Tuple[List[Dict[str, Any]], str]:
        if not (self._projectId and self._query):
            return [], ""
        body: Dict[str, Any] = {"query": self._query, "maxResults": limit,
                                "useQueryCache": True}
        if token:
            body["pageToken"] = token
        payload = self._requestRows(
            "%s/projects/%s/queries" % (self._base, self._projectId),
            jsonBody=body)
        fields = [f.get("name") for f in (payload.get("schema") or {}).get("fields") or []]
        rows: List[Dict[str, Any]] = []
        for row in payload.get("rows") or []:
            cells = [cell.get("v") for cell in row.get("f") or []]
            rows.append({name: value for name, value in zip(fields, cells)})
        return rows, str(payload.get("pageToken") or "")


class DatabricksAdapter(SaaSRestAdapter):
    """Databricks SQL Statement Execution：warehouse_id + SQL 文本，
    data_array 按描述符 columns 展平。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str) -> None:
        super().__init__(descriptor, sourceId, tenantId)
        self._warehouseId = str(self._descriptor.get("warehouse_id") or "")
        self._query = str(self._descriptor.get("query") or "")
        self._columns = [str(c) for c in (self._descriptor.get("columns") or [])]

    def _fetchRows(self, token: str, limit: int) -> Tuple[List[Dict[str, Any]], str]:
        if not (self._warehouseId and self._query):
            return [], ""
        body: Dict[str, Any] = {"statement": self._query,
                                "warehouse_id": self._warehouseId,
                                "wait_timeout": "30s", "format": "JSON_ARRAY"}
        payload = self._requestRows("%s/api/2.0/sql/statements" % self._base,
                                    jsonBody=body)
        result = payload.get("result") or {}
        data = result.get("data_array") or []
        columns = self._columns or [
            c.get("name") for c in (result.get("manifest") or {}).get("schema")
            or []] or None
        rows: List[Dict[str, Any]] = []
        for row in data:
            if columns and len(columns) == len(row):
                rows.append({name: value for name, value in zip(columns, row)})
            else:
                rows.append({"c%d" % i: value for i, value in enumerate(row)})
        return rows, ""


class SalesforceAdapter(SaaSRestAdapter):
    """Salesforce SOQL：query 端点——游标即 nextRecordsUrl 原文（绝对路径）。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str) -> None:
        super().__init__(descriptor, sourceId, tenantId)
        self._soql = str(self._descriptor.get("soql") or "")

    def _fetchRows(self, token: str, limit: int) -> Tuple[List[Dict[str, Any]], str]:
        if not (self._base and self._soql):
            return [], ""
        if token:
            payload = self._requestRows("%s%s" % (self._base, token))
        else:
            payload = self._requestRows(
                "%s/services/data/%s/query" % (self._base, _SALESFORCE_API_VERSION),
                params={"q": self._soql})
        records = []
        for record in payload.get("records") or []:
            records.append({k: v for k, v in record.items() if k != "attributes"})
        return records, str(payload.get("nextRecordsUrl") or "")


class ServiceNowAdapter(SaaSRestAdapter):
    """ServiceNow Table API：sysparm_limit/sysparm_offset 页游标，basic auth。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str) -> None:
        super().__init__(descriptor, sourceId, tenantId)
        self._table = str(self._descriptor.get("table") or "")
        self._query = str(self._descriptor.get("query") or "")

    def _headers(self) -> Dict[str, str]:
        return {**super()._headers(), **self._basicAuthHeaders()}

    def _fetchRows(self, token: str, limit: int) -> Tuple[List[Dict[str, Any]], str]:
        if not (self._base and self._table):
            return [], ""
        offset = int(token) if token.isdigit() else 0
        params: Dict[str, Any] = {"sysparm_limit": limit,
                                  "sysparm_offset": offset}
        if self._query:
            params["sysparm_query"] = self._query
        payload = self._requestRows(
            "%s/api/now/table/%s" % (self._base, self._table), params=params)
        rows = payload.get("result") or []
        nextToken = str(offset + len(rows)) if len(rows) >= limit else ""
        return rows, nextToken


class LookerAdapter(SaaSRestAdapter):
    """Looker API：login（client_id/client_secret）换 token，queries/{id}/run/json。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str) -> None:
        super().__init__(descriptor, sourceId, tenantId)
        self._queryId = str(self._descriptor.get("query_id") or "")
        self._loginLock = threading.Lock()
        self._logged = False

    def _ensureLogin(self) -> None:
        if self._logged:
            return
        with self._loginLock:
            if self._logged:
                return
            creds = resolveCredentialEnv(self._descriptor, "credentialEnv")
            clientId = creds.get("client_id", "")
            clientSecret = creds.get("client_secret", "")
            if clientId and clientSecret and self._base:
                resp = httpx.post("%s/login" % self._base,
                                  data={"client_id": clientId,
                                        "client_secret": clientSecret},
                                  timeout=30)
                resp.raise_for_status()
                self._token = str(resp.json().get("access_token") or "")
            self._logged = True

    def _headers(self) -> Dict[str, str]:
        self._ensureLogin()
        return super()._headers()

    def _fetchRows(self, token: str, limit: int) -> Tuple[List[Dict[str, Any]], str]:
        if not (self._base and self._queryId):
            return [], ""
        payload = self._requestRows(
            "%s/queries/%s/run/json" % (self._base, self._queryId))
        rows = payload if isinstance(payload, list) else []
        return rows[:limit], ""


class AirflowAdapter(SaaSRestAdapter):
    """Airflow Stable REST：dagRuns 列表——basic auth，limit/offset 页游标。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str) -> None:
        super().__init__(descriptor, sourceId, tenantId)
        self._dagId = str(self._descriptor.get("dag_id") or "")

    def _headers(self) -> Dict[str, str]:
        return {**super()._headers(), **self._basicAuthHeaders()}

    def _fetchRows(self, token: str, limit: int) -> Tuple[List[Dict[str, Any]], str]:
        if not (self._base and self._dagId):
            return [], ""
        offset = int(token) if token.isdigit() else 0
        payload = self._requestRows(
            "%s/api/v1/dags/%s/dagRuns" % (self._base, self._dagId),
            params={"limit": limit, "offset": offset})
        rows = payload.get("dag_runs") or []
        nextToken = str(offset + len(rows)) if len(rows) >= limit else ""
        return rows, nextToken


#: sourceType → 适配器类（数据驱动闭集，ERP_VENDOR_ADAPTERS 同款单一出处）。
SAAS_ADAPTERS: Dict[str, type] = {
    "bigquery": BigQueryAdapter,
    "databricks": DatabricksAdapter,
    "salesforce": SalesforceAdapter,
    "servicenow": ServiceNowAdapter,
    "looker": LookerAdapter,
    "airflow": AirflowAdapter,
}
