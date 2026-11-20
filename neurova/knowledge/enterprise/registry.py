"""企业源注册与 admission 接线（B14 §14.2/§14.3）。

- registry：sourceType 白名单注册表；默认不注册任何真实适配器。
- ingestBatch：fake adapter → mapping.apply → AdmissionRequest → admission gate
  （唯一写口；坏一行只退它自己，逐条 finding 留名）；游标在 source batch 完成
  后推进，source batch 级失败不推进；重放幂等靠内容键去重。
- 默认关闸：enabled=False 的 source 零调用零网络。
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Dict, List, Optional

from .protocols import ChangeBatch, EnterpriseSourceAdapter, SourceCursor, SOURCE_TYPES
from .schema_mapping import (
    MappingError,
    VARIANT_CLOSED_SETS,
    applyMapping,
    validateDescriptor,
)

_SCHEMA_V34_ENTERPRISE = None  # DDL 由 schema_mapping._SCHEMA_V34 持有，foundation_schema 引用

#: runOnce 单轮拉取的批数上限：拉完 hasMore=False 自然收，超上限如实报告截断
_RUN_ONCE_MAX_BATCHES = 20
#: fetchBatch 单批行数上限（方案 §4：具名常量、默认温和）
_FETCH_BATCH_LIMIT = 200

#: v56（可靠性方案 D1，2026-11-19）：企业源同步历史——每轮拉取（手动/interval，
#: 成功/失败/跳过）落一行，回答「上次同步何时、拉了多少、为何失败」。
#: 只追加不删（审计纪律）；写入单点 = runOnceAsync（三条拉取链的公共必经路）。
_SCHEMA_V56_SYNC_HISTORY = """
CREATE TABLE IF NOT EXISTS enterprise_sync_history (
    history_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    trigger_kind TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'ok',
    reason TEXT NOT NULL DEFAULT '',
    batches INTEGER NOT NULL DEFAULT 0,
    admitted INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    rows_skipped INTEGER NOT NULL DEFAULT 0,
    entries_written INTEGER NOT NULL DEFAULT 0,
    truncated INTEGER NOT NULL DEFAULT 0,
    cursor_before TEXT NOT NULL DEFAULT '',
    cursor_after TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_enterprise_sync_history
    ON enterprise_sync_history(tenant_id, source_id, started_at);
"""

#: v57：企业源租户级共享策略（可靠性方案 §8.3-P2，2026-11-19 拍板全量实施）——
#: enterprise_source_configs 加 share_tenants_json（目标租户 id 列表，JSON 数组）。
#: 投影式复制：连接器凭据属源租户，目标租户不独立拉取——源租户每轮拉取成功后，
#: 同一批断言投影到目标租户分区（qualifier.shared_from 血缘注记，内容键按租户分区各自幂等）。
_SCHEMA_V57_SHARE_TENANTS = """
ALTER TABLE enterprise_source_configs
    ADD COLUMN share_tenants_json TEXT NOT NULL DEFAULT '[]';
"""

#: D3 单源单飞：`(tenant_id, source_id)` → 进程内锁。非阻塞 try-acquire，
#: 拿不到＝同源已有一轮在跑，第二轮如实 `already_running` 跳过（不排队、不并发双拉）。
#: 进程内锁覆盖单体单进程部署；多 worker 互斥不在本批（方案 §2 非目标）。
_syncLocks: Dict[tuple, threading.Lock] = {}
_syncLocksGuard = threading.Lock()

#: 运行时单源跟随（D2）用的调度器引用：registerIntervalSyncs 注册时记下，
#: setSyncInterval/saveConfig 改间隔或启停时据此即时注册/摘除单源 job。
_activeScheduler: Optional[Any] = None


def _syncLockFor(tenantId: str, sourceId: str) -> threading.Lock:
    key = (str(tenantId or "default"), str(sourceId or ""))
    with _syncLocksGuard:
        if key not in _syncLocks:
            _syncLocks[key] = threading.Lock()
        return _syncLocks[key]


def _recordSyncHistory(store: Any, tenantId: str, sourceId: str, triggerKind: str,
                       status: str, startedAt: str, reason: str = "",
                       batches: int = 0, admitted: int = 0, rejected: int = 0,
                       rowsSkipped: int = 0, entriesWritten: int = 0,
                       truncated: bool = False, cursorBefore: str = "",
                       cursorAfter: str = "") -> None:
    """同步历史落一行（D1，fail-soft）：写失败只记日志，绝不影响同步主流程。"""
    import uuid as _uuid

    from neurova.core.time_utils import nowIso as _now

    try:
        finished = _now()
        with store._lock, store._conn:
            store._conn.execute(
                "INSERT INTO enterprise_sync_history (history_id, tenant_id, source_id,"
                " trigger_kind, status, reason, batches, admitted, rejected,"
                " rows_skipped, entries_written, truncated, cursor_before, cursor_after,"
                " duration_ms, started_at, finished_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("esync_%s" % _uuid.uuid4().hex[:12], str(tenantId or "default"),
                 str(sourceId or ""), str(triggerKind or "manual"), str(status),
                 str(reason or "")[:500], int(batches), int(admitted), int(rejected),
                 int(rowsSkipped), int(entriesWritten), 1 if truncated else 0,
                 str(cursorBefore or ""), str(cursorAfter or ""),
                 int((__import__("datetime").datetime
                      .fromisoformat(finished)
                      - __import__("datetime").datetime.fromisoformat(startedAt))
                     .total_seconds() * 1000) if startedAt else None,
                 str(startedAt or finished), finished),
            )
    except Exception as exc:  # noqa: BLE001 - 历史落账失败不拖垮同步主流程
        try:
            from neurova.core.logger import get_logger

            get_logger(__name__).warning(
                "同步历史落账失败（%s/%s）：%s", tenantId, sourceId, exc)
        except Exception:  # noqa: BLE001
            pass


def listSyncTenants(store: Any = None) -> List[str]:
    """D2：声明了 interval（enabled 且 seconds>0）的全部租户——调度覆盖不再限 default。"""
    if store is None:
        from ..foundation import get_knowledge_fact_store

        store = get_knowledge_fact_store()
    with store._lock:
        rows = store._conn.execute(
            "SELECT DISTINCT tenant_id FROM enterprise_source_configs"
            " WHERE enabled = 1 AND sync_interval_seconds > 0 ORDER BY tenant_id"
        ).fetchall()
    return [str(r["tenant_id"]) for r in rows]


def buildAdapter(descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str = "default") -> EnterpriseSourceAdapter:
    """(sourceType, 变体) → 适配器实例的唯一工厂。

    变体字段在编译期「给了就收口、不给不拒」（存量 B14 判据不破），但工厂按需
    强制要求——缺变体的描述符到不了运行时。新适配器批次（SQL 直连/ERP/聊天）
    在此接线，全部惰性 import（可选驱动 fail-soft 纪律）。
    """
    sourceType = str(descriptor.get("sourceType") or "")
    if sourceType == "file":
        return _requireVariant(descriptor, sourceId, tenantId, "file",
                               "FileRowAdapter", "connectors_file")
    if sourceType == "sql":
        return _requireVariant(descriptor, sourceId, tenantId, "sql",
                               "SqlDirectAdapter", "connectors_sql")
    if sourceType == "erp_api":
        # W11 vendor 数据化（specs/2026-11-12 §12）：kind→适配器工厂表是数据
        import importlib

        module = importlib.import_module("neurova.knowledge.enterprise.connectors_erp")
        vendor = str(descriptor.get("vendor") or "")
        adapters = getattr(module, "ERP_VENDOR_ADAPTERS", {})
        adapterClass = adapters.get(vendor)
        if adapterClass is None:
            return _requireVariant(descriptor, sourceId, tenantId, "erp_api",
                                   "ErpRestAdapter", "connectors_erp")
        return adapterClass(descriptor, sourceId, tenantId)
    if sourceType == "chat":
        return _requireVariant(descriptor, sourceId, tenantId, "chat",
                               "ChatChannelAdapter", "connectors_chat")
    if sourceType == "http_pull":
        # W10（specs/2026-11-12 §11）：通用 HTTP 拉取接线——批 C3 欠账同批清
        import importlib

        module = importlib.import_module("neurova.knowledge.enterprise.connectors_lakehouse")
        return module.HttpPullAdapter(descriptor, sourceId, tenantId)
    if sourceType in ("unity_catalog", "snowflake", "sap_odata"):
        # W10 湖仓三连接器（REST 面，零新增依赖）
        import importlib

        module = importlib.import_module("neurova.knowledge.enterprise.connectors_lakehouse")
        adapterClass = {"unity_catalog": module.UnityCatalogAdapter,
                        "snowflake": module.SnowflakeAdapter,
                        "sap_odata": module.SapOdataAdapter}[sourceType]
        return adapterClass(descriptor, sourceId, tenantId)
    if sourceType == "event_stream":
        raise MappingError("event_stream 连接器缓办（立项方案 §2.2 候选 6 原判有效）")
    raise MappingError("sourceType %r 不在白名单" % sourceType)


def _requireVariant(descriptor: Dict[str, Any], sourceId: str, tenantId: str,
                    sourceType: str, adapterName: str,
                    moduleName: str) -> EnterpriseSourceAdapter:
    """变体强制＋适配器类惰性分派的共用半边。

    适配器类名一律惰性 import（可选驱动 fail-soft 纪律——SQL 驱动缺失
    不挡工厂构造，health 时点名；本批只落 file，其余三族由各自批次落模块）。
    """
    if sourceType not in VARIANT_CLOSED_SETS:
        raise MappingError("sourceType %r 未声明变体闭集" % sourceType)
    field, _closed = VARIANT_CLOSED_SETS[sourceType]
    if not str(descriptor.get(field) or ""):
        raise MappingError("%s 源缺 %s（闭集：%s）"
                           % (sourceType, field, " / ".join(_closed)))
    import importlib

    module = importlib.import_module("neurova.knowledge.enterprise.%s" % moduleName)
    adapterClass = getattr(module, adapterName)
    return adapterClass(descriptor, sourceId, tenantId)


class EnterpriseSourceRegistry:
    """sourceType 白名单注册表：默认空表；真实适配器接入只能走 register。"""

    def __init__(self) -> None:
        self._adapters: Dict[str, EnterpriseSourceAdapter] = {}

    def register(self, sourceId: str, sourceType: str,
                 adapter: EnterpriseSourceAdapter) -> None:
        if sourceType not in SOURCE_TYPES:
            raise ValueError(
                "sourceType %r 不在白名单（%s）" % (sourceType, " / ".join(SOURCE_TYPES)))
        self._adapters[str(sourceId or "").strip()] = adapter

    def get(self, sourceId: str) -> Optional[EnterpriseSourceAdapter]:
        return self._adapters.get(str(sourceId or "").strip())

    def unregister(self, sourceId: str) -> None:
        """进程内适配器摘除（DELETE 配置后的配套动作；幂等）。"""
        self._adapters.pop(str(sourceId or "").strip(), None)

    def sources(self) -> List[str]:
        return sorted(self._adapters)


_sourceRegistry: Optional[EnterpriseSourceRegistry] = None
_sourceRegistryLock = threading.RLock()


def getSourceRegistry() -> EnterpriseSourceRegistry:
    """进程内唯一适配器注册表（DCL 单例）。

    默认空表——真实连接器（DB/ERP API/事件流）另立项，只有实现 Protocol 后经
    `register` 进来才算「已接入」。REST 面读这一张表回显 `adapter_registered`，
    于是「配置存了」与「源能连了」是两个不相冒充的读数。
    """
    global _sourceRegistry
    if _sourceRegistry is None:
        with _sourceRegistryLock:
            if _sourceRegistry is None:
                _sourceRegistry = EnterpriseSourceRegistry()
    return _sourceRegistry


class EnterpriseIngestor:
    """fake adapter → mapping → admission 的接线面（同步写，调用方放 worker 线程）。"""

    def __init__(self, store: Any, registry: Any = None,
                 gateFactory: Any = None) -> None:
        self._store = store
        self._registry = registry
        from neurova.knowledge.foundation.admission import productionAdmissionGate

        self._gateFactory = gateFactory or (lambda st: productionAdmissionGate(st))
        self._lock = threading.RLock()

    def ingestBatch(self, descriptor: Dict[str, Any], rows: List[Dict[str, Any]],
                    cursorToken: str = "", tenantOverride: str = "",
                    originTenant: str = "") -> Dict[str, Any]:
        """一批源行 → 映射 → 批量准入。返回 {admitted, rejected, findings}。

        - 每行一条 AdmissionRequest（activityKind=import，mediumRef=source:<id>:<cursor>）；
        - 坏一行只退它自己（admitBatch 语义），finding 留名；
        - 幂等：内容键去重由咽喉承担，重放不产生重复事实；
        - tenantOverride/originTenant（P2 投影式复制）：把同一批断言投影到目标
          租户分区——租户取 override，qualifier.shared_from 注记血缘；
          内容键按租户分区各自幂等。
        """
        tenantId = str(tenantOverride or descriptor.get("tenantId") or "default")
        sourceId = str(descriptor.get("sourceId") or "")
        from neurova.knowledge.foundation.admission import AdmissionRequest

        gate = self._gateFactory(self._store)
        requests: List[AdmissionRequest] = []
        # missing=skip（P2-1，2026-11-19）：object 派生值为空的行整行跳过并如实
        # 留名，不拖累同批其他行（admitBatch 语义不变）。
        skipped: List[Dict[str, Any]] = []
        for index, row in enumerate(rows):
            mapped = applyMapping(descriptor, row, self._registry, tenantId=tenantId)
            if mapped is None:
                skipped.append({"index": index, "reason": "missing_object"})
                continue
            statement = "%s %s %s" % (mapped["subjectLabel"], mapped["predicateTermId"],
                                      mapped["objectTerm"])
            qualifier = dict(mapped.get("qualifier") or {})
            if originTenant:
                qualifier["shared_from"] = originTenant
            requests.append(AdmissionRequest(
                agentId=str(descriptor.get("agentId") or "default"),
                tenantId=tenantId,
                subjectLabel=mapped["subjectLabel"],
                predicateTermId=mapped["predicateTermId"],
                objectTerm=mapped["objectTerm"],
                content=statement,
                qualifier=qualifier,
                validFrom=mapped["validFrom"],
                validUntil=mapped["validUntil"],
                sourceCreatedAt=mapped.get("sourceCreatedAt"),
                sourceModifiedAt=mapped.get("sourceModifiedAt"),
                assertions=[{"actorType": "importer",
                             "actorId": "source:%s" % sourceId,
                             "mediumRef": "source:%s:%s" % (sourceId, cursorToken),
                             "statementText": statement,
                             # 行级血缘（P3-1b 写入方接线）：span 记批内行序，
                             # 与 mediumRef 的 cursor 一起可回溯到源批次的具体一行
                             "sourceSpan": {"row": index}}],
                activityKind="import",
                activityBasis="enterprise.ingestBatch（source=%s cursor=%s）"
                              % (sourceId, cursorToken),
            ))

        admitted = 0
        rejections: List[Dict[str, Any]] = []
        for finding in gate.admitBatch(requests):
            if finding.get("ok"):
                admitted += 1
            else:
                rejections.append({"index": finding.get("index"),
                                   "finding": finding.get("finding")})
        return {"admitted": admitted, "rejected": len(rejections),
                "rejections": rejections, "skipped": skipped, "cursor": cursorToken}

    def saveConfig(self, tenantId: str, sourceId: str, descriptor: Dict[str, Any],
                   enabled: bool = False) -> None:
        """描述符落库（v34 enterprise_source_configs）；编译期校验先判。"""
        validateDescriptor(descriptor, self._registry, tenantId=tenantId)
        stamp = self._now()
        with self._store._lock, self._store._conn:
            existing = self._store._conn.execute(
                "SELECT created_at, share_tenants_json FROM enterprise_source_configs"
                " WHERE tenant_id = ? AND source_id = ?",
                (str(tenantId or "default"), str(sourceId or ""))).fetchone()
            self._store._conn.execute(
                "INSERT OR REPLACE INTO enterprise_source_configs (source_id, tenant_id,"
                " descriptor_json, cursor, enabled, created_at, updated_at,"
                " share_tenants_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (str(sourceId or ""), str(tenantId or "default"),
                 json.dumps(descriptor, ensure_ascii=False, sort_keys=True),
                 "", 1 if enabled else 0,
                 existing["created_at"] if existing else stamp, stamp,
                 # INSERT OR REPLACE 会把未声明列清成默认值——共享策略是治理配置，
                 # 保存描述符不得顺手清掉它（显式带旧值回填）。
                 (existing["share_tenants_json"] if existing else "[]") or "[]"),
            )
        # D2 运行时跟随：按落库后的 enabled/间隔现值即时注册/摘除单源 job
        # （INSERT OR REPLACE 会把未声明列清零，故以现值而非入参为准）。
        _followUpSyncJob(tenantId, sourceId, store=self._store)

    def setShareTenants(self, tenantId: str, sourceId: str,
                        tenantIds: List[str]) -> List[str]:
        """P2：声明源的租户级共享策略（v57 列；投影式复制的目标租户清单）。

        不能共享给源所属租户自身；空清单＝清空（停止共享）。目标租户存在性
        由端点层经部门根组树校验（repo 层不依赖 auth 面）。
        """
        ownTenant = str(tenantId or "default")
        if self.loadConfig(ownTenant, sourceId) is None:
            raise LookupError("source 配置不存在: %s" % sourceId)
        cleaned: List[str] = []
        for tid in tenantIds or []:
            tid = str(tid or "").strip()
            if not tid:
                continue
            if tid == ownTenant:
                raise ValueError("不能共享给源所属租户自身")
            if tid not in cleaned:
                cleaned.append(tid)
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "UPDATE enterprise_source_configs SET share_tenants_json = ?,"
                " updated_at = ? WHERE tenant_id = ? AND source_id = ?",
                (json.dumps(cleaned, ensure_ascii=False), self._now(),
                 ownTenant, str(sourceId or "")))
        return cleaned

    def setSyncInterval(self, tenantId: str, sourceId: str, seconds: int) -> None:
        """W3：声明源的 interval 同步间隔（v44 列；0＝不持续同步）。

        D2 运行时跟随：落库后即时注册/摘除单源 job（调度器可用时），改完即生效。
        """
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "UPDATE enterprise_source_configs SET sync_interval_seconds = ?,"
                " updated_at = ? WHERE tenant_id = ? AND source_id = ?",
                (max(0, int(seconds)), self._now(),
                 str(tenantId or "default"), str(sourceId or "")))
        _followUpSyncJob(tenantId, sourceId, store=self._store)

    def listConfigs(self, tenantId: str = "default") -> List[Dict[str, Any]]:
        """本租户已提交过的源配置（描述符 + 游标 + 启用态）——读面，不触发任何网络。"""
        tenant = str(tenantId or "default")
        with self._store._lock:
            ids = [str(r["source_id"]) for r in self._store._conn.execute(
                "SELECT source_id FROM enterprise_source_configs WHERE tenant_id = ?"
                " ORDER BY source_id", (tenant,)).fetchall()]
        rows: List[Dict[str, Any]] = []
        for sourceId in ids:
            config = self.loadConfig(tenantId, sourceId) or {}
            rows.append({"source_id": sourceId,
                         "descriptor": config.get("descriptor") or {},
                         "cursor": config.get("cursor") or "",
                         "enabled": bool(config.get("enabled")),
                         "sync_interval_seconds": int(config.get("sync_interval_seconds") or 0),
                         "share_tenants": config.get("share_tenants") or [],
                         "created_at": config.get("created_at") or "",
                         "updated_at": config.get("updated_at") or ""})
        return rows

    def loadConfig(self, tenantId: str, sourceId: str) -> Optional[Dict[str, Any]]:
        row = self._store._conn.execute(
            "SELECT descriptor_json, cursor, enabled, created_at, updated_at,"
            " sync_interval_seconds, share_tenants_json"
            " FROM enterprise_source_configs"
            " WHERE tenant_id = ? AND source_id = ?",
            (str(tenantId or "default"), str(sourceId or ""))).fetchone()
        if row is None:
            return None
        return {"descriptor": json.loads(row["descriptor_json"] or "{}"),
                "cursor": row["cursor"], "enabled": bool(row["enabled"]),
                "sync_interval_seconds": int(row["sync_interval_seconds"] or 0),
                "share_tenants": json.loads(row["share_tenants_json"] or "[]"),
                "created_at": row["created_at"] or "",
                "updated_at": row["updated_at"] or ""}

    def deleteConfig(self, tenantId: str, sourceId: str) -> bool:
        """删除连接器配置行（页面重设计配套批）：只删配置，不碰已摄取事实/断言
        ——擦除设施闭集不含 `source:` 前缀，级联清除是另一个立项；调用方如实回显。"""
        with self._store._lock, self._store._conn:
            cursor = self._store._conn.execute(
                "DELETE FROM enterprise_source_configs WHERE tenant_id = ? AND source_id = ?",
                (str(tenantId or "default"), str(sourceId or "")))
            deleted = cursor.rowcount > 0
        return deleted

    async def probeHealth(self, tenantId: str, sourceId: str) -> Optional[Dict[str, Any]]:
        """连接健康探测（页面"连接状态"列与向导"测试连接"的数据源）。

        loadConfig → buildAdapter（**不注册**——探测是只读动作，不改变
        "适配器已注册"读数的语义）→ await health()（**协程**——health 是
        async 契约，不 await 会把协程对象读成 error/空 reason，live-verify
        实测踩过）。配置不存在返回 None；工厂错（缺变体/未接线）与探测
        异常统一归一为 status=error＋reason 原话。
        """
        config = self.loadConfig(tenantId, sourceId)
        if config is None:
            return None
        descriptor = dict(config["descriptor"])
        descriptor["tenantId"] = tenantId
        descriptor["sourceId"] = sourceId
        try:
            adapter = buildAdapter(descriptor, sourceId, tenantId)
            health = await adapter.health()
            return {"status": str(getattr(health, "status", "error") or "error"),
                    "reason": str(getattr(health, "reason", "") or "")}
        except Exception as exc:  # noqa: BLE001 - 探测失败如实归一为 error＋原话
            return {"status": "error", "reason": str(exc)}

    def saveCursor(self, tenantId: str, sourceId: str, token: str) -> None:
        """游标单列持久化（不碰描述符与 enabled；失败由调用方决定重试）。"""
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "UPDATE enterprise_source_configs SET cursor = ?, updated_at = ?"
                " WHERE tenant_id = ? AND source_id = ?",
                (str(token or ""), self._now(),
                 str(tenantId or "default"), str(sourceId or "")),
            )

    async def runOnceAsync(self, tenantId: str, sourceId: str,
                           triggerKind: str = "manual") -> Dict[str, Any]:
        """手动/interval 触发一轮拉取（拍板项 2A）：loadConfig → 适配器 →
        fetchBatch 循环 → ingestBatch → 游标逐批持久化。

        - triggerKind（D1）：manual | interval——历史落账的触发来源；
        - 单飞（D3）：同源已有一轮在跑 → `already_running` 如实跳过（不排队）；
        - enabled=False 或配置不存在 → skipped（零读取零网络，关闸语义原样）；
        - 适配器未注册则经唯一工厂 buildAdapter 构造并注册（配置存了 ≠ 源能连了，
          两者仍是分开的读数；工厂抛错如实冒泡，不吞成空轮）；
        - 游标在 source batch **成功后**逐批推进（ingestBatch 抛错 → 本轮中止 →
          游标停在上一成功批 → 下轮必然重试，方案 §4 失败不推进语义）；
        - 超过 _RUN_ONCE_MAX_BATCHES 批仍 hasMore → 如实报 truncated=True；
        - 每轮结果落 `enterprise_sync_history`（D1，fail-soft）。
        """
        tenant = str(tenantId or "default")
        source = str(sourceId or "")
        startedAt = self._now()
        cursorBefore = ""
        lock = _syncLockFor(tenant, source)
        if not lock.acquire(blocking=False):
            self._recordHistorySafe(tenant, source, triggerKind, "skipped",
                                    startedAt, reason="already_running")
            return {"skipped": True, "reason": "already_running"}
        try:
            return await self._runOnceLocked(
                tenant, source, triggerKind, startedAt, cursorBefore)
        finally:
            lock.release()

    async def _runOnceLocked(self, tenantId: str, sourceId: str, triggerKind: str,
                             startedAt: str, cursorBefore: str) -> Dict[str, Any]:
        config = self.loadConfig(tenantId, sourceId)
        if config is None:
            self._recordHistorySafe(tenantId, sourceId, triggerKind, "skipped",
                                    startedAt, reason="source 配置不存在")
            return {"skipped": True, "reason": "source 配置不存在"}
        if not config.get("enabled"):
            self._recordHistorySafe(tenantId, sourceId, triggerKind, "skipped",
                                    startedAt, reason="source 未启用（默认关）")
            return {"skipped": True, "reason": "source 未启用（默认关）"}
        cursorBefore = str(config.get("cursor") or "")
        descriptor = dict(config["descriptor"])
        descriptor["tenantId"] = tenantId
        descriptor["sourceId"] = sourceId
        registry = getSourceRegistry()
        adapter = registry.get(sourceId)
        if adapter is None:
            adapter = buildAdapter(descriptor, sourceId, tenantId)
            registry.register(sourceId, str(descriptor.get("sourceType") or ""), adapter)

        cursor = SourceCursor(str(config.get("cursor") or ""))
        admitted = 0
        rejected = 0
        rowsSkipped = 0
        entries = {"written": 0, "duplicated": 0, "skipped": 0}
        batches = 0
        truncated = False
        # P2 投影式复制：源租户每轮拉到的批，同批投影到 share_tenants 目标租户分区
        # （qualifier.shared_from 血缘注记；内容键按租户分区各自幂等，重拉零重复）。
        shareTo = [str(t).strip() for t in (config.get("share_tenants") or [])
                   if str(t or "").strip()]
        projectedCounts: Dict[str, int] = {}
        projectionErrors: Dict[str, str] = {}
        try:
            while batches < _RUN_ONCE_MAX_BATCHES:
                change = await adapter.fetchBatch(cursor or None, _FETCH_BATCH_LIMIT)
                batches += 1
                if change.rows:
                    result = self.ingestBatch(
                        descriptor, change.rows, cursorToken=str(cursor.token or ""))
                    admitted += int(result.get("admitted") or 0)
                    rejected += int(result.get("rejected") or 0)
                    rowsSkipped += len(result.get("skipped") or [])
                    for targetTenant in shareTo:
                        try:
                            projected = self.ingestBatch(
                                descriptor, change.rows,
                                cursorToken=str(cursor.token or ""),
                                tenantOverride=targetTenant, originTenant=tenantId)
                            projectedCounts[targetTenant] = (
                                projectedCounts.get(targetTenant, 0)
                                + int(projected.get("admitted") or 0))
                        except Exception as exc:  # noqa: BLE001 - 投影失败不回滚源轮，
                            # 但必须点名（静默丢数据=教义第 2 条）；下轮重拉按内容键幂等补齐
                            projectionErrors[targetTenant] = str(exc)
                            from neurova.core.logger import get_logger

                            get_logger(__name__).error(
                                "企业源投影到目标租户失败（%s/%s → %s）：%s",
                                tenantId, sourceId, targetTenant, exc)
                    # 正文分档能力钩子（批 C7c，§14-C）：适配器若提供 writeArchiveEntries
                    # （现仅存档面聊天源），行集在 facts 之外另承正文进条目链——
                    # registry 不感知 chat 细节，只认能力面。
                    entryWriter = getattr(adapter, "writeArchiveEntries", None)
                    if entryWriter is not None:
                        entryOutcome = await entryWriter(change.rows, tenantId=tenantId)
                        if entryOutcome.get("applied", True):
                            for key in ("written", "duplicated", "skipped"):
                                entries[key] += int(entryOutcome.get(key) or 0)
                if change.nextCursor is not None and not change.nextCursor.isEmpty():
                    cursor = change.nextCursor
                    self.saveCursor(tenantId, sourceId, str(cursor.token))
                if not change.hasMore:
                    truncated = False
                    break
            else:
                truncated = True
        except Exception as exc:
            self._recordHistorySafe(tenantId, sourceId, triggerKind, "error",
                                    startedAt, reason=str(exc), batches=batches,
                                    admitted=admitted, rejected=rejected,
                                    rowsSkipped=rowsSkipped,
                                    entriesWritten=entries.get("written", 0),
                                    truncated=truncated, cursorBefore=cursorBefore,
                                    cursorAfter=str(cursor.token or ""))
            raise
        self._recordHistorySafe(tenantId, sourceId, triggerKind, "ok", startedAt,
                                batches=batches, admitted=admitted, rejected=rejected,
                                rowsSkipped=rowsSkipped,
                                entriesWritten=entries.get("written", 0),
                                truncated=truncated, cursorBefore=cursorBefore,
                                cursorAfter=str(cursor.token or ""))
        return {"admitted": admitted, "rejected": rejected,
                "entries": entries,
                "batches": batches, "truncated": truncated,
                "cursor": str(cursor.token or ""),
                "projected": projectedCounts, **({"projection_errors": projectionErrors}
                                                 if projectionErrors else {})}

    def _recordHistorySafe(self, tenantId: str, sourceId: str, triggerKind: str,
                           status: str, startedAt: str, reason: str = "",
                           batches: int = 0, admitted: int = 0, rejected: int = 0,
                           rowsSkipped: int = 0, entriesWritten: int = 0,
                           truncated: bool = False, cursorBefore: str = "",
                           cursorAfter: str = "") -> None:
        _recordSyncHistory(self._store, tenantId, sourceId, triggerKind, status,
                           startedAt, reason=reason, batches=batches,
                           admitted=admitted, rejected=rejected,
                           rowsSkipped=rowsSkipped, entriesWritten=entriesWritten,
                           truncated=truncated, cursorBefore=cursorBefore,
                           cursorAfter=cursorAfter)

    def runOnce(self, tenantId: str, sourceId: str) -> Dict[str, Any]:
        """同步壳：无事件循环的调用方（测试/worker 线程）用；循环内请 await runOnceAsync。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "runOnce 不能在事件循环内调用（FastAPI 端点请 await runOnceAsync）")
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.runOnceAsync(tenantId, sourceId))
        finally:
            loop.close()

    @staticmethod
    def _now() -> str:
        import datetime

        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def ingestIfEnabled(self, tenantId: str, sourceId: str,
                        rows: List[Dict[str, Any]], cursorToken: str = "") -> Dict[str, Any]:
        """默认关闸：enabled=False 的 source 零调用（直接回 skipped）。"""
        config = self.loadConfig(tenantId, sourceId)
        if config is None or not config.get("enabled"):
            return {"skipped": True, "reason": "source 未启用（默认关）"}
        descriptor = dict(config["descriptor"])
        descriptor["tenantId"] = tenantId
        descriptor["sourceId"] = sourceId
        return self.ingestBatch(descriptor, rows, cursorToken=cursorToken
                                or config.get("cursor") or "")


def registerIntervalSyncs(scheduler: Any, store: Any = None,
                          tenantId: Optional[str] = None) -> int:
    """W3 持续同步 + D2 全租户覆盖：为声明了 sync_interval_seconds>0 的启用源
    向既有调度器注册 interval job——job 触发调既有 runOnceAsync（trigger=interval），
    零新同步逻辑；不新造调度器（scheduler 需带 addSystemJob 公开面）。

    tenantId 缺省 = 遍历 `listSyncTenants()` 的**全部租户**（修复只覆盖 default
    的隔离缺口）；显式传租户则只注册该租户（既有测试语义不变）。返回注册条数。
    """
    global _activeScheduler
    if scheduler is None or not hasattr(scheduler, "addSystemJob"):
        return 0
    _activeScheduler = scheduler
    factStore = store
    if factStore is None:
        from ..foundation import get_knowledge_fact_store

        factStore = get_knowledge_fact_store()
    tenants = [str(tenantId or "default")] if tenantId else listSyncTenants(factStore)
    registered = 0
    for tenant in tenants:
        registered += _registerTenantJobs(scheduler, factStore, tenant)
    return registered


def _registerTenantJobs(scheduler: Any, factStore: Any, tenantId: str) -> int:
    """单租户的启用源逐个注册 interval job（jobId 带租户段，跨租户不互顶）。"""
    ingestor = EnterpriseIngestor(factStore)
    registered = 0
    for config in ingestor.listConfigs(tenantId=tenantId):
        seconds = int(config.get("sync_interval_seconds") or 0)
        if not config.get("enabled") or seconds <= 0:
            continue
        sourceId = str(config.get("source_id") or "")
        _registerOneJob(scheduler, factStore, tenantId, sourceId, seconds)
        registered += 1
    return registered


def _registerOneJob(scheduler: Any, factStore: Any, tenantId: str, sourceId: str,
                    seconds: int) -> None:
    def _job(tenantId=tenantId, sourceId=sourceId, factStore=factStore):
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                EnterpriseIngestor(factStore).runOnceAsync(
                    tenantId, sourceId, triggerKind="interval"))
        finally:
            loop.close()

    scheduler.addSystemJob(_job, jobId="kb_enterprise_sync_%s_%s" % (tenantId, sourceId),
                           seconds=seconds)


def syncSourceJob(scheduler: Any, tenantId: str, sourceId: str,
                  store: Any = None) -> bool:
    """D2 运行时跟随：按当前配置**注册或摘除**单源 interval job。

    enabled 且 seconds>0 → 注册（replace_existing 幂等）；否则摘除（无此 job
    时幂等静默）。返回注册与否。同时把调度器记入模块引用，供后续跟随复用。
    """
    global _activeScheduler
    _activeScheduler = scheduler
    factStore = store
    if factStore is None:
        from ..foundation import get_knowledge_fact_store

        factStore = get_knowledge_fact_store()
    jobId = "kb_enterprise_sync_%s_%s" % (tenantId, sourceId)
    config = EnterpriseIngestor(factStore).loadConfig(tenantId, sourceId) or {}
    seconds = int(config.get("sync_interval_seconds") or 0)
    if not config.get("enabled") or seconds <= 0:
        if hasattr(scheduler, "removeSystemJob"):
            scheduler.removeSystemJob(jobId)
        return False
    _registerOneJob(scheduler, factStore, tenantId, sourceId, seconds)
    return True


def _followUpSyncJob(tenantId: str, sourceId: str, store: Any = None) -> None:
    """D2 运行时跟随入口：调度器在场时按**落库现值**即时注册/摘除单源 job。

    fail-soft：跟随失败只记日志，绝不影响配置写面。
    """
    scheduler = _activeScheduler
    if scheduler is None:
        return
    try:
        syncSourceJob(scheduler, tenantId, sourceId, store=store)
    except Exception as exc:  # noqa: BLE001 - 跟随失败点名，不拖垮配置写面
        try:
            from neurova.core.logger import get_logger

            get_logger(__name__).warning(
                "单源同步 job 跟随失败（%s/%s）：%s", tenantId, sourceId, exc)
        except Exception:  # noqa: BLE001
            pass


#: P1-3（2026-11-21 拍板 D-E）：企业源摄取「启动钩子 + 24h 巡检补跑」双保险。
#: 巡检窗口小时数走 env（默认 24）；日巡检 job 挂既有调度器，不新造第二台。
STALE_HOURS_ENV = "NEUROVA_ENTERPRISE_SYNC_STALE_HOURS"
_DEFAULT_STALE_HOURS = 24.0
ENTERPRISE_SYNC_AUDIT_JOB_ID = "enterprise-sync-staleness-audit"
ENTERPRISE_SYNC_AUDIT_SECONDS = 86400


def _staleWindowHours() -> float:
    """巡检窗口（小时）：每次调用现读 env，改配置即时生效；非法值回落默认 24。"""
    import os

    raw = (os.environ.get(STALE_HOURS_ENV) or "").strip()
    if not raw:
        return _DEFAULT_STALE_HOURS
    try:
        return max(0.0, float(raw))
    except ValueError:
        return _DEFAULT_STALE_HOURS


def _lastSuccessStartedAt(store: Any, tenantId: str, sourceId: str) -> Optional[str]:
    """该源在 enterprise_sync_history 里最近一条成功记录的 started_at（无则 None）。"""
    with store._lock:
        row = store._conn.execute(
            "SELECT started_at FROM enterprise_sync_history"
            " WHERE tenant_id = ? AND source_id = ? AND status = 'ok'"
            " ORDER BY started_at DESC, history_id DESC LIMIT 1",
            (str(tenantId or "default"), str(sourceId or ""))).fetchone()
    return str(row["started_at"]) if row is not None else None


def auditEnterpriseSyncStaleness(triggerKind: str = "audit",
                                 store: Any = None) -> Dict[str, Any]:
    """P1-3 巡检补跑：源「配置了同步但近期无成功」时的兜底拉取。

    遍历 listSyncTenants() 每租户每个启用源，查 enterprise_sync_history 最近
    一条成功记录；距今超过窗口（NEUROVA_ENTERPRISE_SYNC_STALE_HOURS，默认 24h）
    或从未成功 → 调既有 runOnceAsync(tenant, source, triggerKind) 补跑
    （内部自带单飞/失败落账/关闸语义，本函数零新同步逻辑）。

    - triggerKind：落账的触发来源（启动钩子传 "startup"，日巡检传 "audit"；
      trigger_kind 为 TEXT 列，新取值免迁移，admin 同步历史读面天然可见）；
    - fail-soft：单源异常记 failed 计数并点名，不阻断其余源；
    - 返回 {checked, triggered, skipped, failed}：checked=审计到的启用源数，
      triggered=发起补跑数，skipped=窗口内已有成功而跳过数，failed=补跑抛错数。
    """
    import datetime as _datetime

    if store is None:
        from ..foundation import get_knowledge_fact_store

        store = get_knowledge_fact_store()
    now = _datetime.datetime.now(_datetime.timezone.utc)
    windowHours = _staleWindowHours()
    checked = triggered = skipped = failed = 0
    ingestor = EnterpriseIngestor(store)
    for tenant in listSyncTenants(store):
        for config in ingestor.listConfigs(tenantId=tenant):
            if not config.get("enabled"):
                continue
            sourceId = str(config.get("source_id") or "")
            if not sourceId:
                continue
            checked += 1
            lastOk = _lastSuccessStartedAt(store, tenant, sourceId)
            if lastOk:
                try:
                    ageHours = (now - _datetime.datetime.fromisoformat(lastOk)
                                ).total_seconds() / 3600.0
                    if ageHours <= windowHours:
                        skipped += 1
                        continue
                except ValueError:
                    pass  # 历史时间戳不可解析 → 视同过期，如实补跑
            try:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(
                        ingestor.runOnceAsync(tenant, sourceId,
                                              triggerKind=triggerKind))
                finally:
                    loop.close()
                triggered += 1
            except Exception as exc:  # noqa: BLE001 - 单源失败不阻断其余源
                failed += 1
                try:
                    from neurova.core.logger import get_logger

                    get_logger(__name__).warning(
                        "企业源巡检补跑失败（%s/%s）：%s", tenant, sourceId, exc)
                except Exception:  # noqa: BLE001
                    pass
    return {"checked": checked, "triggered": triggered,
            "skipped": skipped, "failed": failed}


def registerEnterpriseSyncAuditJob(scheduler: Any,
                                   seconds: int = ENTERPRISE_SYNC_AUDIT_SECONDS) -> bool:
    """P1-3 日巡检注册口：经既有调度器 addSystemJob 挂周期 job（不另起线程）。

    job 体调 auditEnterpriseSyncStaleness("audit")；addSystemJob 对同 jobId
    replace_existing，重复注册幂等。无 addSystemJob 面的调度器如实回 False。
    """
    if scheduler is None or not hasattr(scheduler, "addSystemJob"):
        return False

    def _auditJob():
        auditEnterpriseSyncStaleness("audit")

    scheduler.addSystemJob(_auditJob, jobId=ENTERPRISE_SYNC_AUDIT_JOB_ID,
                           seconds=seconds)
    return True
