"""ERP REST 连接器（立项方案批 C5，2026-11-07 裁定 §2.4-2：先金蝶与用友）。

两家厂商的开放 API 均为 HTTP REST——经已在依赖清单的 httpx 对接（候选 4 同款），
**不引厂商 SDK**（原判 SDK 的依赖理由对 REST 化对接不成立）。

凭据纪律（方案 §4 原文有效）：
- 描述符只放**环境变量名**（`credentialEnv`），不放任何密钥值；
- 值在 fetchBatch/health 时从环境解析；日志不落凭据与原始响应全文；
- 会话过期自动重登**一次**，再失败才显式 error（不无限重试）；
- 429 具名退避（`_RATE_LIMIT_BACKOFF_SECONDS`），上限具名（`_MAX_429_RETRIES`）。

游标：金蝶按 StartRow 行水位（`kingdee:row=N`），用友按页码（`yongyou:page=N`）；
hasMore 按响应记录数与 limit 的如实比较（`=limit` 视为可能还有，下一批自会收束）。
分页语义各租户部署略有差异——字段形状全部描述符可配，默认值按两家常见
公开形状，待真租户核（见台账 §6-576 待核清单）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from .protocols import ChangeBatch, SourceCursor, SourceHealth, SourceSchema

logger = logging.getLogger(__name__)

#: 429 退避秒数（具名常量、默认温和；测试经 mock 补丁置 0）
_RATE_LIMIT_BACKOFF_SECONDS = 2.0
#: 429 重试上限（到达后显式失败，不吞成空批）
_MAX_429_RETRIES = 1
#: HTTP 超时秒数
_REQUEST_TIMEOUT_SECONDS = 30.0
#: 单批行数上限（fetchBatch limit 的钳制）
_MAX_BATCH_LIMIT = 500


ERP_VENDOR_ADAPTERS: Dict[str, type] = {}

class ErpRestAdapter:
    """`sourceType=erp_api` 的 Protocol 实现（vendor ∈ kingdee/yongyou）。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str = "default") -> None:
        self._descriptor = dict(descriptor or {})
        self._sourceId = str(sourceId)
        self._tenantId = str(tenantId or "default")
        self._vendor = str(self._descriptor.get("vendor") or "")
        if self._vendor not in ("kingdee", "yongyou"):
            # 适配器自守契约：工厂只查变体在场，闭集由实现自己把关
            from .schema_mapping import MappingError

            raise MappingError("vendor %r 不在闭集（kingdee/yongyou）" % self._vendor)
        self._baseUrl = str(self._descriptor.get("baseUrl") or "").rstrip("/")
        self._columns = [str(c) for c in (self._descriptor.get("columns") or [])]
        self._credentialEnv = dict(self._descriptor.get("credentialEnv") or {})
        self._client: Optional[Any] = None
        self._authed = False

    # ── Protocol 四动词 ──────────────────────────────────────

    async def describeSchema(self) -> SourceSchema:
        return SourceSchema(
            sourceId=self._sourceId, sourceType="erp_api",
            tables=[{"name": str(self._descriptor.get("formId")
                                 or self._descriptor.get("docType") or "documents"),
                     "columns": list(self._columns), "vendor": self._vendor}],
        )

    _seenCursors: set = set()

    def _checkCursorLoop(self, cursorToken: str) -> None:
        """W11 分页 cursor 环检测：同 cursor 再现即停并如实报错。"""
        if cursorToken in type(self)._seenCursors:
            raise RuntimeError(
                "分页 cursor 环检测：cursor %r 连续再现（上游分页异常，停止拉取）"
                % cursorToken[:40])
        type(self)._seenCursors.add(cursorToken)

    async def fetchBatch(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch:
        limit = max(1, min(int(limit), _MAX_BATCH_LIMIT))
        if self._vendor == "kingdee":
            return await self._fetchKingdee(cursor, limit)
        if self._vendor == "yongyou":
            return await self._fetchYongyou(cursor, limit)
        return ChangeBatch(rows=[], hasMore=False)

    async def health(self) -> SourceHealth:
        missing = [env for field, env in self._credentialEnv.items()
                   if not os.environ.get(env)]
        if missing:
            return SourceHealth(status="error",
                                reason="凭据环境变量缺失: %s" % ", ".join(missing))
        if not self._baseUrl:
            return SourceHealth(status="error", reason="baseUrl 未配置")
        if self._vendor not in ("kingdee", "yongyou"):
            return SourceHealth(status="error",
                                reason="vendor %r 不在闭集（kingdee/yongyou）" % self._vendor)
        try:
            await asyncio.to_thread(self._ensureAuthed)
        except Exception as exc:  # noqa: BLE001 - 健康探测的失败如实点名，不静默 ok
            return SourceHealth(status="error", reason="登录探测失败: %s" % exc)
        return SourceHealth(status="ok")

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        self._authed = False

    # ── 凭据与会话 ───────────────────────────────────────────

    def _resolveCredentials(self) -> Dict[str, str]:
        """按 credentialEnv 的「字段 → 环境变量名」解析凭据；值不进日志。"""
        resolved: Dict[str, str] = {}
        for field, envName in self._credentialEnv.items():
            value = os.environ.get(str(envName), "")
            if value:
                resolved[str(field)] = value
        return resolved

    def _ensureClient(self) -> Any:
        import httpx

        if self._client is None:
            self._client = httpx.Client(timeout=_REQUEST_TIMEOUT_SECONDS)
        return self._client

    def _log(self, message: str) -> None:
        """日志出口：只落路径与计数，不落凭据/响应全文（本模块纪律单点）。"""
        logger.debug("erp[%s/%s] %s", self._vendor, self._sourceId, message)

    def _ensureAuthed(self) -> None:
        """未认证则登录；金蝶换 cookie 会话，用友换 token。失败显式 error。"""
        if self._authed:
            return
        creds = self._resolveCredentials()
        missing = [env for _f, env in self._credentialEnv.items()
                   if not os.environ.get(env)]
        if missing or not creds:
            raise RuntimeError("凭据环境变量缺失: %s" % ", ".join(missing) or "credentialEnv 未声明")
        client = self._ensureClient()
        if self._vendor == "kingdee":
            loginPath = str(self._descriptor.get("loginPath") or "/K3Cloud/Kingdee.BOS.WebApi.ServicesStub.AuthService.LoginByAppSecret.common.kdsvc")
            response = client.post(
                self._baseUrl + loginPath,
                json={"acctID": creds.get("acctId", ""),
                      "username": creds.get("username", ""),
                      "password": creds.get("password", ""),
                      "lcid": int(creds.get("lcid", "2052"))},
            )
            self._log("kingdee login http=%d" % response.status_code)
            if response.status_code != 200:
                raise RuntimeError("金蝶登录失败 http=%d" % response.status_code)
            body = response.json()
            if isinstance(body, dict) and body.get("ErrorCode") not in (None, 0):
                raise RuntimeError("金蝶登录被拒（凭据或账套错误）")
        else:  # yongyou
            tokenPath = str(self._descriptor.get("tokenPath") or "/iuap-api-auth/open-auth/selfAppAuth/getAccessToken")
            response = client.post(
                self._baseUrl + tokenPath,
                json={"appKey": creds.get("appKey", ""),
                      "appSecret": creds.get("appSecret", "")},
            )
            self._log("yongyou token http=%d" % response.status_code)
            if response.status_code != 200:
                raise RuntimeError("用友取 token 失败 http=%d" % response.status_code)
            body = response.json()
            token = ""
            if isinstance(body, dict):
                data = body.get("data") or body
                token = str(data.get("token") or body.get("token") or "")
            if not token:
                raise RuntimeError("用友 token 未返回（凭据或应用配置错误）")
            client.headers["Authorization"] = "Bearer %s" % token
        self._authed = True

    def _reloginOnce(self) -> None:
        self._authed = False
        self._ensureAuthed()

    def _postWithReauth(self, path: str, payload: Dict[str, Any],
                        state: Dict[str, int]) -> Any:
        """带一次重登的 POST；401/会话过期形状触发重登，再失败如实抛。"""
        self._ensureAuthed()
        client = self._ensureClient()
        for attempt in (0, 1):
            response = client.post(self._baseUrl + path, json=payload)
            self._log("post %s http=%d attempt=%d" % (path, response.status_code, attempt))
            if response.status_code == 401 and attempt == 0:
                self._reloginOnce()
                continue
            if response.status_code == 429:
                if state["rate_limits"] < _MAX_429_RETRIES:
                    state["rate_limits"] += 1
                    if _RATE_LIMIT_BACKOFF_SECONDS > 0:
                        time.sleep(_RATE_LIMIT_BACKOFF_SECONDS)
                    continue
                raise RuntimeError("限频重试上限到达（%d 次）" % _MAX_429_RETRIES)
            if response.status_code != 200:
                raise RuntimeError("请求失败 http=%d" % response.status_code)
            return response.json()
        raise RuntimeError("请求在重登/退避后仍未成功")

    # ── 金蝶（云星空 WebAPI 形状）────────────────────────────

    async def _fetchKingdee(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch:
        state = {"rate_limits": 0}
        startRow = 0
        if cursor is not None and not cursor.isEmpty():
            try:
                startRow = int(str(cursor.token).split("row=")[1])
            except (IndexError, ValueError):
                startRow = 0
        queryPath = str(self._descriptor.get("queryPath")
                        or "/K3Cloud/Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.ExecuteBillQuery.common.kdsvc")
        payload = {
            "formId": str(self._descriptor.get("formId") or ""),
            "fieldKeys": ",".join(self._columns),
            "StartRow": startRow,
            "Limit": limit,
        }
        body = await asyncio.to_thread(self._postWithReauth, queryPath, payload, state)
        rows = self._normalizeRows(body)
        hasMore = len(rows) >= limit
        nextOffset = startRow + len(rows)
        nextCursor = SourceCursor("kingdee:row=%d" % nextOffset) if (rows or hasMore) else None
        return ChangeBatch(rows=rows, nextCursor=nextCursor, hasMore=hasMore)

    # ── 用友（U8C/YonSuite 开放 API 形状）────────────────────

    async def _fetchYongyou(self, cursor: Optional[SourceCursor], limit: int) -> ChangeBatch:
        state = {"rate_limits": 0}
        page = 1
        if cursor is not None and not cursor.isEmpty():
            try:
                page = int(str(cursor.token).split("page=")[1])
            except (IndexError, ValueError):
                page = 1

        def _request() -> Any:
            self._ensureAuthed()
            listPath = str(self._descriptor.get("listPath") or "/iuap/list")
            client = self._ensureClient()
            response = client.get(
                self._baseUrl + listPath,
                params={"pageIndex": page, "pageSize": limit},
            )
            self._log("yongyou list http=%d page=%d" % (response.status_code, page))
            if response.status_code == 401:
                raise _TokenInvalid()
            if response.status_code == 429:
                raise _RateLimited()
            if response.status_code != 200:
                raise RuntimeError("用友列表请求失败 http=%d" % response.status_code)
            return response.json()

        body = await asyncio.to_thread(self._retryLoop, _request, state)
        data = body.get("data") if isinstance(body, dict) else None
        rows = self._normalizeRows((data or {}).get("list") if isinstance(data, dict) else body)
        total = int((data or {}).get("recordCount") or 0) if isinstance(data, dict) else 0
        hasMore = (total > page * limit) if total else len(rows) >= limit
        nextPage = page + 1
        nextCursor = SourceCursor("yongyou:page=%d" % nextPage) if (rows or hasMore) else None
        return ChangeBatch(rows=rows, nextCursor=nextCursor, hasMore=hasMore)

    # ── 共用半边 ─────────────────────────────────────────────

    def _retryLoop(self, requestFn: Any, state: Dict[str, int]) -> Any:
        """429 退避重试 + 用友 token 失效重登一次的共用循环。"""
        reauthed = False
        while True:
            try:
                return requestFn()
            except _TokenInvalid:
                if reauthed:
                    raise RuntimeError("token 重登一次后仍失效")
                reauthed = True
                self._reloginOnce()
            except _RateLimited:
                if state["rate_limits"] >= _MAX_429_RETRIES:
                    raise RuntimeError("限频重试上限到达（%d 次）" % _MAX_429_RETRIES)
                state["rate_limits"] += 1
                if _RATE_LIMIT_BACKOFF_SECONDS > 0:
                    time.sleep(_RATE_LIMIT_BACKOFF_SECONDS)

    def _normalizeRows(self, payload: Any) -> List[Dict[str, Any]]:
        """两家响应形状 → 列 dict 行；字典键不在 columns 的原样保留（映射层按列取）。"""
        if isinstance(payload, dict):
            # 金蝶 ExecuteBillQuery 常见形状：{"Result":{"Result":{"...":[[...]]}}} 或行数组
            result = payload.get("Result") if isinstance(payload.get("Result"), dict) else payload
            inner = result.get("Result") if isinstance(result, dict) else result
            payload = inner if isinstance(inner, list) else []
        if not isinstance(payload, list):
            return []
        rows: List[Dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                rows.append(item)
            elif isinstance(item, list) and self._columns:
                rows.append({column: (item[i] if i < len(item) else "")
                             for i, column in enumerate(self._columns)})
        return rows


class _TokenInvalid(Exception):
    """用友 token 失效形状（401）——触发一次重登。"""


class _RateLimited(Exception):
    """限频形状（429）——触发具名退避。"""


ERP_VENDOR_ADAPTERS["kingdee"] = ErpRestAdapter
ERP_VENDOR_ADAPTERS["yongyou"] = ErpRestAdapter
