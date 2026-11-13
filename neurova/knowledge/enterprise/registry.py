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
                    cursorToken: str = "") -> Dict[str, Any]:
        """一批源行 → 映射 → 批量准入。返回 {admitted, rejected, findings}。

        - 每行一条 AdmissionRequest（activityKind=import，mediumRef=source:<id>:<cursor>）；
        - 坏一行只退它自己（admitBatch 语义），finding 留名；
        - 幂等：内容键去重由咽喉承担，重放不产生重复事实。
        """
        tenantId = str(descriptor.get("tenantId") or "default")
        sourceId = str(descriptor.get("sourceId") or "")
        from neurova.knowledge.foundation.admission import AdmissionRequest

        gate = self._gateFactory(self._store)
        requests: List[AdmissionRequest] = []
        for row in rows:
            mapped = applyMapping(descriptor, row, self._registry, tenantId=tenantId)
            statement = "%s %s %s" % (mapped["subjectLabel"], mapped["predicateTermId"],
                                      mapped["objectTerm"])
            requests.append(AdmissionRequest(
                agentId=str(descriptor.get("agentId") or "default"),
                tenantId=tenantId,
                subjectLabel=mapped["subjectLabel"],
                predicateTermId=mapped["predicateTermId"],
                objectTerm=mapped["objectTerm"],
                content=statement,
                qualifier=mapped["qualifier"],
                validFrom=mapped["validFrom"],
                validUntil=mapped["validUntil"],
                sourceCreatedAt=mapped.get("sourceCreatedAt"),
                sourceModifiedAt=mapped.get("sourceModifiedAt"),
                assertions=[{"actorType": "importer",
                             "actorId": "source:%s" % sourceId,
                             "mediumRef": "source:%s:%s" % (sourceId, cursorToken),
                             "statementText": statement}],
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
                "rejections": rejections, "cursor": cursorToken}

    def saveConfig(self, tenantId: str, sourceId: str, descriptor: Dict[str, Any],
                   enabled: bool = False) -> None:
        """描述符落库（v34 enterprise_source_configs）；编译期校验先判。"""
        validateDescriptor(descriptor, self._registry, tenantId=tenantId)
        stamp = self._now()
        with self._store._lock, self._store._conn:
            existing = self._store._conn.execute(
                "SELECT created_at FROM enterprise_source_configs"
                " WHERE tenant_id = ? AND source_id = ?",
                (str(tenantId or "default"), str(sourceId or ""))).fetchone()
            self._store._conn.execute(
                "INSERT OR REPLACE INTO enterprise_source_configs (source_id, tenant_id,"
                " descriptor_json, cursor, enabled, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (str(sourceId or ""), str(tenantId or "default"),
                 json.dumps(descriptor, ensure_ascii=False, sort_keys=True),
                 "", 1 if enabled else 0,
                 existing["created_at"] if existing else stamp, stamp),
            )

    def setSyncInterval(self, tenantId: str, sourceId: str, seconds: int) -> None:
        """W3：声明源的 interval 同步间隔（v44 列；0＝不持续同步）。"""
        with self._store._lock, self._store._conn:
            self._store._conn.execute(
                "UPDATE enterprise_source_configs SET sync_interval_seconds = ?,"
                " updated_at = ? WHERE tenant_id = ? AND source_id = ?",
                (max(0, int(seconds)), self._now(),
                 str(tenantId or "default"), str(sourceId or "")))

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
                         "created_at": config.get("created_at") or "",
                         "updated_at": config.get("updated_at") or ""})
        return rows

    def loadConfig(self, tenantId: str, sourceId: str) -> Optional[Dict[str, Any]]:
        row = self._store._conn.execute(
            "SELECT descriptor_json, cursor, enabled, created_at, updated_at,"
            " sync_interval_seconds"
            " FROM enterprise_source_configs"
            " WHERE tenant_id = ? AND source_id = ?",
            (str(tenantId or "default"), str(sourceId or ""))).fetchone()
        if row is None:
            return None
        return {"descriptor": json.loads(row["descriptor_json"] or "{}"),
                "cursor": row["cursor"], "enabled": bool(row["enabled"]),
                "sync_interval_seconds": int(row["sync_interval_seconds"] or 0),
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

    async def runOnceAsync(self, tenantId: str, sourceId: str) -> Dict[str, Any]:
        """手动触发一轮拉取（拍板项 2A）：loadConfig → 适配器 → fetchBatch 循环
        → ingestBatch → 游标逐批持久化。

        - enabled=False 或配置不存在 → skipped（零读取零网络，关闸语义原样）；
        - 适配器未注册则经唯一工厂 buildAdapter 构造并注册（配置存了 ≠ 源能连了，
          两者仍是分开的读数；工厂抛错如实冒泡，不吞成空轮）；
        - 游标在 source batch **成功后**逐批推进（ingestBatch 抛错 → 本轮中止 →
          游标停在上一成功批 → 下轮必然重试，方案 §4 失败不推进语义）；
        - 超过 _RUN_ONCE_MAX_BATCHES 批仍 hasMore → 如实报 truncated=True。
        """
        config = self.loadConfig(tenantId, sourceId)
        if config is None:
            return {"skipped": True, "reason": "source 配置不存在"}
        if not config.get("enabled"):
            return {"skipped": True, "reason": "source 未启用（默认关）"}
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
        entries = {"written": 0, "duplicated": 0, "skipped": 0}
        batches = 0
        truncated = False
        while batches < _RUN_ONCE_MAX_BATCHES:
            change = await adapter.fetchBatch(cursor or None, _FETCH_BATCH_LIMIT)
            batches += 1
            if change.rows:
                result = self.ingestBatch(
                    descriptor, change.rows, cursorToken=str(cursor.token or ""))
                admitted += int(result.get("admitted") or 0)
                rejected += int(result.get("rejected") or 0)
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
        return {"admitted": admitted, "rejected": rejected,
                "entries": entries,
                "batches": batches, "truncated": truncated,
                "cursor": str(cursor.token or "")}

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
                          tenantId: str = "default") -> int:
    """W3 持续同步（specs/2026-11-12 §5；D3 interval 最小闭合）：为声明了
    sync_interval_seconds>0 的启用源向既有调度器注册 interval job——job 触发
    调既有 runOnceAsync 处理函数，零新同步逻辑；不新造调度器（scheduler 需带
    addSystemJob 公开面）。返回注册条数。"""
    if scheduler is None or not hasattr(scheduler, "addSystemJob"):
        return 0
    factStore = store
    if factStore is None:
        from ..foundation import get_knowledge_fact_store

        factStore = get_knowledge_fact_store()
    ingestor = EnterpriseIngestor(factStore)
    registered = 0
    for config in ingestor.listConfigs(tenantId=tenantId):
        seconds = int(config.get("sync_interval_seconds") or 0)
        if not config.get("enabled") or seconds <= 0:
            continue
        sourceId = str(config.get("source_id") or "")

        def _job(sourceId=sourceId, tenantId=tenantId):
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    EnterpriseIngestor(factStore).runOnceAsync(tenantId, sourceId))
            finally:
                loop.close()

        scheduler.addSystemJob(_job, jobId="kb_enterprise_sync_%s" % sourceId,
                               seconds=seconds)
        registered += 1
    return registered
