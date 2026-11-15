# -*- coding: utf-8 -*-
"""NL2SQL 问数 REST 面（P1-4 批一 / P2-3，2026-11-15）。

独立叶子（尺寸纪律），挂载走 `knowledge.py` 聚合器。

门控（缺省关，诚实拒绝）：
- `NEUROVA_NL2SQL_ENABLED` 未置 on 时 ask/suggest 一律 403 点名——能力存在
  但未开闸，不是 404 冒充不存在；
- ask / suggest-patterns 是治理动作（仅管理员）；history 登录可读（本租户）。

执行边界：只认适配器 `executeReadonly`（只读硬闸 + LIMIT 收敛在适配器层）；
无该能力的源只出计划（plan-only），响应如实标注。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service

router = APIRouter()

ENV_NL2SQL_ENABLED = "NEUROVA_NL2SQL_ENABLED"


class Nl2SqlAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    execute: bool = True
    max_rows: int = Field(default=200, ge=1, le=200)
    use_llm: bool = True


def _tenantOf(current_user: Dict[str, Any]) -> str:
    return str(current_user.get("tenant_id") or "default")


def _requireAdmin(current_user: Dict[str, Any]) -> None:
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403,
                            detail="问数是数据访问面，仅管理员可执行（批一门控）")


def _requireEnabled() -> None:
    flag = str(os.environ.get(ENV_NL2SQL_ENABLED) or "").strip().lower()
    if flag not in ("1", "true", "on", "yes"):
        raise HTTPException(
            status_code=403,
            detail="NL2SQL 未开闸（%s 未置 on）——能力默认关，见对照研究 P1-4 门控"
                   % ENV_NL2SQL_ENABLED)


def _service():
    from neurova.knowledge.enterprise.nl2sql import Nl2SqlService
    from neurova.knowledge.foundation import get_knowledge_fact_store

    return Nl2SqlService(get_knowledge_fact_store())


def _llmCallOrNull(request: Request, preferAgentId: str = "") -> Optional[Any]:
    """运行时 Agent 的 llm_client → prompt→文本；不可用回 None（诚实拒答）。"""
    try:
        from neurova.api.endpoints.knowledge_common import resolveAgentLlmClients
        from neurova.mem_core import run_async_safely

        clients = resolveAgentLlmClients(request,
                                         prefer_agent_id=preferAgentId or None)
        if not clients:
            return None

        def _call(prompt: str):
            last = ""
            for client in clients:
                try:
                    resp = run_async_safely(
                        client.chat([{"role": "user", "content": prompt}]))
                except Exception:  # noqa: BLE001 - 换下一个候选
                    continue
                content = getattr(resp, "content", "") or ""
                if content.startswith("[LLM Error]"):
                    last = content
                    continue
                return content
            return last

        return _call
    except Exception:  # noqa: BLE001 - 解析失败按无 LLM 处理
        return None


def _executorFor(tenant: str, sourceId: str) -> Optional[Any]:
    """源适配器 executeReadonly → 同步桥；非 SQL 族/建不了适配器 → None（只出计划）。"""
    from neurova.knowledge.enterprise.registry import buildAdapter, EnterpriseIngestor
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.mem_core import run_async_safely

    ingestor = EnterpriseIngestor(get_knowledge_fact_store())
    config = ingestor.loadConfig(tenant, sourceId)
    if config is None:
        raise LookupError("企业源未提交: %s" % sourceId)
    descriptor = dict(config["descriptor"])
    descriptor["tenantId"] = tenant
    descriptor["sourceId"] = sourceId
    try:
        adapter = buildAdapter(descriptor, sourceId, tenant)
    except Exception:  # noqa: BLE001 - 建不了适配器＝只出计划
        return None
    execute = getattr(adapter, "executeReadonly", None)
    if execute is None:
        return None
    return lambda sql, limit: run_async_safely(execute(sql, limit))


def _loadSourceId(source_id: str) -> str:
    sourceId = str(source_id or "").strip()
    if not sourceId:
        raise HTTPException(status_code=400, detail="source_id 不能为空")
    return sourceId


@router.post("/enterprise/sources/{source_id}/nl2sql")
async def askNl2SqlQuestion(
    source_id: str,
    body: Nl2SqlAskRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """自然语言问数（P1-4 批一，仅管理员 + env 门控）：答案带 SQL 与步骤。

    只读硬闸：生成 SQL 过只读校验与目录表白名单，行数按方言收敛；不可答
    如实拒答（refused），执行失败如实回传（error），历史逐次落账。
    """
    _requireEnabled()
    _requireAdmin(current_user)
    sourceId = _loadSourceId(source_id)
    tenant = _tenantOf(current_user)
    llmCall = _llmCallOrNull(request) if body.use_llm else None
    try:
        executor = _executorFor(tenant, sourceId)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    result = _service().answerQuestion(
        tenant, sourceId, body.question, llmCall=llmCall, executor=executor,
        askedBy=str(current_user.get("username") or ""),
        execute=bool(body.execute), maxRows=body.max_rows)
    return {"code": 0, "message": "success", "data": result}


@router.get("/enterprise/sources/{source_id}/nl2sql/history")
async def listNl2SqlHistory(
    source_id: str,
    limit: int = 50,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """问数历史（登录可读，本租户）：问题/SQL/状态/行数/错误的诚实审计。"""
    sourceId = _loadSourceId(source_id)
    items = _service().listHistory(_tenantOf(current_user), sourceId, limit=limit)
    return {"code": 0, "message": "success", "data": {"items": items,
                                                      "total": len(items)}}


@router.post("/enterprise/sources/{source_id}/nl2sql/suggest-patterns")
async def suggestNl2SqlPatterns(
    source_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """历史回灌（P2-3，仅管理员 + env 门控）：高频表组合 → sql_pattern 候选。

    产物是 pending 建议，批准后进 grounding 少样本；不自动执行任何 SQL。
    """
    _requireEnabled()
    _requireAdmin(current_user)
    sourceId = _loadSourceId(source_id)
    return {"code": 0, "message": "success",
            "data": _service().suggestPatternsFromHistory(_tenantOf(current_user),
                                                          sourceId)}
