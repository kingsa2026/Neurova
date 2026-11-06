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
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service

router = APIRouter()


class EnterpriseSourceWriteRequest(BaseModel):
    source_id: str = ""
    descriptor: Dict[str, Any] = Field(default_factory=dict)
    # 默认关闸：提交描述符 ≠ 开始摄取；要真跑批必须显式置 True 且适配器已注册。
    enabled: bool = False


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
            getSourceRegistry())


def _view(sourceId: str, config: Dict[str, Any], adapters: Any) -> Dict[str, Any]:
    return {
        "source_id": sourceId,
        "descriptor": config.get("descriptor") or {},
        "cursor": config.get("cursor") or "",
        "enabled": bool(config.get("enabled")),
        "adapter_registered": adapters.get(sourceId) is not None,
    }


@router.get("/enterprise/sources")
async def listEnterpriseSources(
    current_user: Dict = Depends(get_current_user_or_service),
):
    """已提交源列表（登录可读）：只读配置表，不触碰任何外部系统。"""
    ingestor, adapters = _parts()
    rows = [_view(row["source_id"], row, adapters)
            for row in ingestor.listConfigs(_tenantOf(current_user))]
    return {"code": 0, "message": "success",
            "data": {"items": rows, "total": len(rows)}}


@router.get("/enterprise/sources/{source_id}")
async def getEnterpriseSource(
    source_id: str,
    current_user: Dict = Depends(get_current_user_or_service),
):
    """单源回显（登录可读）：未提交过 404。"""
    ingestor, adapters = _parts()
    tenant = _tenantOf(current_user)
    config = ingestor.loadConfig(tenant, str(source_id or "").strip())
    if config is None:
        raise HTTPException(status_code=404, detail="企业源未提交: %s" % source_id)
    return {"code": 0, "message": "success",
            "data": _view(str(source_id or "").strip(), config, adapters)}


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

    ingestor, adapters = _parts()
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
