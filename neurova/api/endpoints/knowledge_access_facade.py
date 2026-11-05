"""四动词统一门面（B3）：`/v1/knowledge/access/{query|analyze|validate|use}`。

升级计划 §4 拍板项 3（选 A）＋ §2 纪律咬合：门面是**接线不是第二实现**——
每个动词把请求原样转交给一处既有处理函数，本模块零业务逻辑、零 schema、
零存储；旧路由保持直接入口，两处消费同一实现（教义第 7 条）。

  query    → knowledge_core.search_knowledge        （条目/事实可见域检索）
  analyze  → semantic_search_api.analyze_query       （查询特征分析与权重建议）
  validate → knowledge_ontology.validateOntologyCandidates（B2 dry-run，只读）
  use      → knowledge_core.record_fact_adoption     （采纳结果显式写回）

鉴权与治理门（admin、租户隔离、409/404 语义）全部由被转交的处理函数自带，
门面不复制也不放宽——use 的 403 来自 record_fact_adoption 本身。未声明的动词
没有隐式处理面，天然 404。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request

from neurova.api.auth import get_current_user_or_service
from neurova.api.endpoints.knowledge_common import KnowledgeSearchRequest

router = APIRouter()


@router.post("/access/query")
async def accessQuery(
    request: Request,
    body: KnowledgeSearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
    agent_id: Optional[str] = Query(default=None, description="来源 agent 过滤"),
    scope: str = Query(default="all", description="范围：all/public/private/shared"),
):
    """query 动词：转发既有检索处理函数（同一可见域、同一响应形状）。"""
    from neurova.api.endpoints.knowledge_core import search_knowledge

    return await search_knowledge(
        request=request, body=body, current_user=current_user,
        agent_id=agent_id, scope=scope)


@router.post("/access/analyze")
async def accessAnalyze(body: Dict[str, Any]):
    """analyze 动词：转发 `/v1/semantic-search/analyze` 的查询特征分析。"""
    from neurova.api.endpoints.semantic_search_api import analyze_query

    return await analyze_query(body)


@router.post("/access/validate")
async def accessValidate(
    body: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """validate 动词：转发 B2 本体 dry-run（纯只读，violation 不抛异常）。"""
    from neurova.api.endpoints.knowledge_ontology import (
        OntologyValidateRequest,
        validateOntologyCandidates,
    )

    return await validateOntologyCandidates(
        body=OntologyValidateRequest.model_validate(body), current_user=current_user)


@router.post("/access/use/{fact_id}")
async def accessUse(
    request: Request,
    fact_id: str,
    body: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """use 动词：转发事实采纳写回（治理门由被转交方自带，仅管理员）。"""
    from neurova.api.endpoints.knowledge_core import (
        FactAdoptionRequest,
        record_fact_adoption,
    )

    return await record_fact_adoption(
        request=request, fact_id=fact_id,
        body=FactAdoptionRequest.model_validate(body), current_user=current_user)
