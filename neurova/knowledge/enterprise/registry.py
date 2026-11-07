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
        field, _closed = VARIANT_CLOSED_SETS["file"]
        if not str(descriptor.get(field) or ""):
            raise MappingError("file 源缺 %s（csv/tsv/json/jsonl）" % field)
        from .connectors_file import FileRowAdapter

        return FileRowAdapter(descriptor, sourceId, tenantId)
    if sourceType in ("sql", "erp_api", "http_pull", "chat"):
        field, closed = VARIANT_CLOSED_SETS.get(
            sourceType, ("variant", ()))
        raise MappingError(
            "%s 连接器尚未接线：本批只落 file（缺 %s 分派或等后续批次）" % (sourceType, field))
    if sourceType == "event_stream":
        raise MappingError("event_stream 连接器缓办（立项方案 §2.2 候选 6 原判有效）")
    raise MappingError("sourceType %r 不在白名单" % sourceType)


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

    def listConfigs(self, tenantId: str = "default") -> List[Dict[str, Any]]:
        """本租户已提交过的源配置（描述符 + 游标 + 启用态）——读面，不触发任何网络。"""
        tenant = str(tenantId or "default")
        with self._store._lock:
            ids = [str(r["source_id"]) for r in self._store._conn.execute(
                "SELECT source_id FROM enterprise_source_configs WHERE tenant_id = ?"
                " ORDER BY source_id", (tenant,)).fetchall()]
        rows: List[Dict[str, Any]] = []
        for sourceId in ids:
            config = self.loadConfig(tenant, sourceId) or {}
            rows.append({"source_id": sourceId,
                         "descriptor": config.get("descriptor") or {},
                         "cursor": config.get("cursor") or "",
                         "enabled": bool(config.get("enabled"))})
        return rows

    def loadConfig(self, tenantId: str, sourceId: str) -> Optional[Dict[str, Any]]:
        row = self._store._conn.execute(
            "SELECT descriptor_json, cursor, enabled FROM enterprise_source_configs"
            " WHERE tenant_id = ? AND source_id = ?",
            (str(tenantId or "default"), str(sourceId or ""))).fetchone()
        if row is None:
            return None
        return {"descriptor": json.loads(row["descriptor_json"] or "{}"),
                "cursor": row["cursor"], "enabled": bool(row["enabled"])}

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
            if change.nextCursor is not None and not change.nextCursor.isEmpty():
                cursor = change.nextCursor
                self.saveCursor(tenantId, sourceId, str(cursor.token))
            if not change.hasMore:
                truncated = False
                break
        else:
            truncated = True
        return {"admitted": admitted, "rejected": rejected,
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
