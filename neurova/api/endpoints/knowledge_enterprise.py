# -*- coding: utf-8 -*-
"""企业数据源描述符提交面（B14 §14.3 的 REST 入口）。

这里只做三件事：编译期校验描述符、落库配置、如实回显状态。真实连接器
（DB / ERP API / 事件流）另立项——本模块不提供任何「假装已连接」的调用：

- `enabled` 默认 False（关闸态，摄取路径零调用零网络）；
- `adapter_registered` 读进程内唯一适配器注册表，未注册即 False——
  「配置存下来了」与「源能连上了」是两个不相冒充的读数。

独立路由模块：端点逻辑不塞 knowledge_ontology.py（尺寸纪律），挂载走
`knowledge.py` 聚合器，与 `/ontology*` 同级先于 detail_router。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service

router = APIRouter()


class EnterpriseSourceWriteRequest(BaseModel):
    source_id: str = ""
    descriptor: Dict[str, Any] = Field(default_factory=dict)
    # 默认关闸：提交描述符 ≠ 开始摄取；要真跑批必须显式置 True 且适配器已注册。
    enabled: bool = False


class EnterpriseMediaTriggerRequest(BaseModel):
    msg_id: str = ""


def _tenantOf(current_user: Dict[str, Any]) -> str:
    return str(current_user.get("tenant_id") or "default")


def _parts():
    from neurova.knowledge.enterprise.registry import (
        EnterpriseIngestor,
        getSourceRegistry,
    )
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    store = get_knowledge_fact_store()
    # ingestor 的 registry 形参是**术语**注册表（谓词/客体合法性在那张表上判）；
    # 适配器注册表另有单点，只用来回显「这个 source 今天能不能连」。
    return (EnterpriseIngestor(store, registry=OntologyTermRegistry(store)),
            getSourceRegistry(), store)


def _ingestedCount(store: Any, sourceId: str) -> int:
    """已获取数据量（页面列表列）：按断言来源归因计数。

    每条被准入的源行写 knowledge_assertions（actor_id='source:<id>'，
    registry.ingestBatch:163-166），计数即该连接器累计准入行数——是读数，
    不是缓存；未摄取过的源如实为 0。
    """
    try:
        row = store._conn.execute(
            "SELECT COUNT(*) AS n FROM knowledge_assertions WHERE actor_id = ?",
            ("source:%s" % str(sourceId or ""),)).fetchone()
        return int(row["n"] if row is not None else 0)
    except Exception:  # noqa: BLE001 - 计数失败不挡列表，如实 0
        return 0


def _view(sourceId: str, config: Dict[str, Any], adapters: Any,
          store: Any = None) -> Dict[str, Any]:
    view = {
        "source_id": sourceId,
        "descriptor": config.get("descriptor") or {},
        "cursor": config.get("cursor") or "",
        "enabled": bool(config.get("enabled")),
        "adapter_registered": adapters.get(sourceId) is not None,
        # 页面重设计配套批：添加/更新时间与已获取数据量进回显
        "created_at": str(config.get("created_at") or ""),
        "updated_at": str(config.get("updated_at") or ""),
        "ingested_count": _ingestedCount(store, sourceId) if store is not None else 0,
    }
    return view


@router.get("/enterprise/sources")
async def listEnterpriseSources(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """已提交源列表（登录可读）：只读配置表，不触碰任何外部系统。"""
    ingestor, adapters, store = _parts()
    rows = [_view(row["source_id"], row, adapters, store)
            for row in ingestor.listConfigs(_tenantOf(current_user))]
    return {"code": 0, "message": "success",
            "data": {"items": rows, "total": len(rows)}}


@router.get("/enterprise/sources/{source_id}")
async def getEnterpriseSource(
    source_id: str,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """单源回显（登录可读）：未提交过 404。"""
    ingestor, adapters, store = _parts()
    tenant = _tenantOf(current_user)
    config = ingestor.loadConfig(tenant, str(source_id or "").strip())
    if config is None:
        raise HTTPException(status_code=404, detail="企业源未提交: %s" % source_id)
    return {"code": 0, "message": "success",
            "data": _view(str(source_id or "").strip(), config, adapters, store)}


@router.post("/enterprise/sources")
async def submitEnterpriseSource(
    body: EnterpriseSourceWriteRequest,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """提交映射描述符（治理动作，仅管理员）：编译期校验先判，非法整条拒且零落库。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(
            status_code=403, detail="企业源描述符提交是治理动作，仅管理员可执行")
    sourceId = str(body.source_id or "").strip()
    if not sourceId:
        raise HTTPException(status_code=400, detail="source_id 不能为空")

    ingestor, adapters, _store = _parts()
    tenant = _tenantOf(current_user)
    descriptor = dict(body.descriptor or {})
    descriptor["tenantId"] = tenant
    descriptor["sourceId"] = sourceId
    try:
        ingestor.saveConfig(tenant, sourceId, descriptor, enabled=bool(body.enabled))
    except ValueError as exc:  # MappingError 是 ValueError 子类：带定位的拒因原样出去
        raise HTTPException(status_code=400, detail=str(exc))
    config = ingestor.loadConfig(tenant, sourceId) or {}
    return {"code": 0, "message": "success", "data": _view(sourceId, config, adapters)}


@router.post("/enterprise/sources/{source_id}/ingest")
async def triggerEnterpriseIngest(
    source_id: str,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """手动触发一轮拉取（批 C1，拍板项 2A，仅管理员）：enabled=False 零读取。

    语义＝「现在跑一轮」：loadConfig → 适配器（未注册经唯一工厂构造）→
    fetchBatch 循环 → ingestBatch 唯一咽喉 → 游标逐批持久化。工厂抛错 400
    带定位（缺变体/未接线族）；拉取/写账异常如实 500，不吞成空轮。
    """
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(
            status_code=403, detail="企业源触发摄取是治理动作，仅管理员可执行")
    sourceId = str(source_id or "").strip()
    if not sourceId:
        raise HTTPException(status_code=400, detail="source_id 不能为空")
    ingestor, adapters, store = _parts()
    tenant = _tenantOf(current_user)
    try:
        result = await ingestor.runOnceAsync(tenant, sourceId)
    except ValueError as exc:  # MappingError 是 ValueError 子类：带定位的拒因原样出去
        raise HTTPException(status_code=400, detail=str(exc))
    config = ingestor.loadConfig(tenant, sourceId) or {}
    return {"code": 0, "message": "success",
            "data": {"result": result, "source": _view(sourceId, config, adapters, store)}}


@router.post("/enterprise/sources/{source_id}/media")
async def triggerEnterpriseMediaFetch(
    source_id: str,
    body: EnterpriseMediaTriggerRequest,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """手动触发单条附件取回（批 C7c 第三块，方案 §10-甲裁定，仅管理员）。

    语义＝「取回这一条」：存档面源＋消息体携带 sdkfileid → 通道层
    GetMediaData 分片续传取字节 → 暂存 dataLanding(tmp, archive-media) →
    投影回写 media_staged_path（「已采集」机器可判，与「有引用」不互冒充）。

    - 非存档源 400（媒体触发面仅 chatSource=archive）；
    - 凭据未就绪 409（配置面/原生库/Secret/私钥哪档缺点名）；
    - 无记录或无附件引用 404（诚实读数，不假装有附件）；
    - 引用过期/取回失败 502 原话（ArchiveMediaUnavailable 与一般失败分开读数，
      方案 §10 附带约束：引用有效期与存档窗口同族，「有引用」≠「可检索」）。
    """
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(
            status_code=403, detail="企业源附件取回是治理动作，仅管理员可执行")
    sourceId = str(source_id or "").strip()
    msgId = str(body.msg_id or "").strip()
    if not sourceId or not msgId:
        raise HTTPException(status_code=400, detail="source_id 与 msg_id 不能为空")
    ingestor, _adapters, _store = _parts()
    tenant = _tenantOf(current_user)
    config = ingestor.loadConfig(tenant, sourceId)
    if config is None:
        raise HTTPException(status_code=404, detail="source 配置不存在")
    descriptor = dict(config["descriptor"])
    if (str(descriptor.get("sourceType") or "") != "chat"
            or str(descriptor.get("chatSource") or "") != "archive"):
        raise HTTPException(
            status_code=400, detail="媒体触发面仅存档源可用（chatSource=archive）")
    from neurova.channels import wecom_archive

    agentId = str(descriptor.get("agentId") or "default")
    contexts = wecom_archive._archiveWorkerContexts(agentId)
    context = contexts[0] if contexts else None
    if not context or not context.get("ready"):
        reason = str((context or {}).get("reason") or "企微通道未装配")
        raise HTTPException(status_code=409, detail="存档凭据未就绪：%s" % reason)
    archiveDb = wecom_archive.resolveArchiveDbPath(descriptor)
    sdk = wecom_archive.buildArchiveSdkForContext(context)
    try:
        outcome = wecom_archive.stageArchiveMedia(archiveDb, msgId, sdk)
    except wecom_archive.ArchiveMediaUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except wecom_archive.ArchiveSdkError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        sdk.close()
    if outcome.get("status") == "no_media":
        raise HTTPException(status_code=404, detail="该消息无附件引用（msg_id=%s）" % msgId)
    return {"code": 0, "message": "success", "data": outcome}


@router.get("/enterprise/sources/{source_id}/health")
async def getEnterpriseSourceHealth(
    source_id: str,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """连接健康探测（页面重设计配套批，仅管理员）：适配器 health() 三态如实回显。

    探测是**只读动作**：buildAdapter 构造但不注册——不改变
    "适配器已注册"读数的语义；工厂错（缺变体/未接线）与探测异常统一
    status=error＋reason 原话；配置不存在 404。
    """
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(
            status_code=403, detail="企业源连接探测会触碰外部系统，仅管理员可执行")
    sourceId = str(source_id or "").strip()
    if not sourceId:
        raise HTTPException(status_code=400, detail="source_id 不能为空")
    ingestor, _adapters, _store = _parts()
    probe = await ingestor.probeHealth(_tenantOf(current_user), sourceId)
    if probe is None:
        raise HTTPException(status_code=404, detail="企业源未提交: %s" % source_id)
    return {"code": 0, "message": "success", "data": {"source_id": sourceId, **probe}}


@router.delete("/enterprise/sources/{source_id}")
async def deleteEnterpriseSource(
    source_id: str,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """删除连接器（页面重设计配套批，仅管理员）：只删配置＋摘除进程内适配器，
    **已摄取事实/断言保留**——擦除设施闭集不含 source: 前缀，级联清除另立项；
    响应与前端删除确认均如实说明这一点，不谎报"连数据一起删了"。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(
            status_code=403, detail="企业源删除是治理动作，仅管理员可执行")
    sourceId = str(source_id or "").strip()
    if not sourceId:
        raise HTTPException(status_code=400, detail="source_id 不能为空")
    ingestor, adapters, _store = _parts()
    tenant = _tenantOf(current_user)
    deleted = ingestor.deleteConfig(tenant, sourceId)
    if not deleted:
        raise HTTPException(status_code=404, detail="企业源未提交: %s" % source_id)
    adapters.unregister(sourceId)
    return {"code": 0,
            "message": "连接器配置已删除；已获取的知识数据保留",
            "data": {"source_id": sourceId}}
