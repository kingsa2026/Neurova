# -*- coding: utf-8 -*-
"""Ossie 风格语义模型互操作 REST 面（P2-4，2026-11-15）。

独立叶子（尺寸纪律），挂载走 `knowledge.py` 聚合器。
导出登录可读（与 export.* 家族同门）；导入是治理动作（仅管理员），
**缺省 dry-run 零落库**，apply=true 才经本体流水线整批成版。
"""

from __future__ import annotations

from typing import Any, Dict

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.core.tenant_scope import resolve_tenant

router = APIRouter()


class OssieImportRequest(BaseModel):
    document: str = Field(min_length=1, description="YAML 文档原文")
    apply: bool = False
    reason: str = ""


def _tenantOf(current_user: Dict[str, Any]) -> str:
    return resolve_tenant(current_user)


def _requireAdmin(current_user: Dict[str, Any]) -> None:
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403,
                            detail="语义模型导入是治理动作，仅管理员可执行")


@router.get("/ontology/export.ossie.yaml")
async def exportOssieYaml(
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """导出语义模型文档（登录可读）：术语/规则/形状一份 YAML。"""
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.ossie import exportOssie

    document = exportOssie(get_knowledge_fact_store(), _tenantOf(current_user))
    body = yaml.safe_dump(document, allow_unicode=True, sort_keys=False)
    return Response(content=body, media_type="application/yaml")


@router.post("/ontology/import-ossie")
async def importOssieYaml(
    body: OssieImportRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """导入语义模型文档（仅管理员）：缺省 dry-run，apply=true 整批成版。"""
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.ossie import importOssie

    try:
        result = importOssie(get_knowledge_fact_store(), body.document,
                             tenantId=_tenantOf(current_user), apply=body.apply,
                             createdBy=str(current_user.get("user_id") or ""),
                             reason=body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail="YAML 解析失败: %s" % exc)
    return {"code": 0, "message": "success", "data": result}
