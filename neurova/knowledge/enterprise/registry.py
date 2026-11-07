"""企业源注册与 admission 接线（B14 §14.2/§14.3）。

- registry：sourceType 白名单注册表；默认不注册任何真实适配器。
- ingestBatch：fake adapter → mapping.apply → AdmissionRequest → admission gate
  （唯一写口；坏一行只退它自己，逐条 finding 留名）；游标在 source batch 完成
  后推进，source batch 级失败不推进；重放幂等靠内容键去重。
- 默认关闸：enabled=False 的 source 零调用零网络。
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional

from .protocols import EnterpriseSourceAdapter, SOURCE_TYPES
from .schema_mapping import MappingError, applyMapping, validateDescriptor

_SCHEMA_V34_ENTERPRISE = None  # DDL 由 schema_mapping._SCHEMA_V34 持有，foundation_schema 引用


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
