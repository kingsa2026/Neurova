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


def nl2sqlGateOpen() -> bool:
    """总闸读数（单一事实源）：``NEUROVA_NL2SQL_ENABLED`` ∈ {1,true,on,yes} 即开。

    REST 面（403 点名）与蜂群两面（工具面/MCP 面结构化拒绝）读同一份判定，
    总闸语义（默认关）不因新增消费方漂移。
    """
    flag = str(os.environ.get(ENV_NL2SQL_ENABLED) or "").strip().lower()
    return flag in ("1", "true", "on", "yes")


def _requireEnabled() -> None:
    if not nl2sqlGateOpen():
        raise HTTPException(
            status_code=403,
            detail="NL2SQL 未开闸（%s 未置 on）——能力默认关，见对照研究 P1-4 门控"
                   % ENV_NL2SQL_ENABLED)


def _service():
    from neurova.knowledge.enterprise.nl2sql import Nl2SqlService
    from neurova.knowledge.foundation import get_knowledge_fact_store

    return Nl2SqlService(get_knowledge_fact_store())


def llmCallFromClients(clients: Optional[Any]) -> Optional[Any]:
    """llm_client 候选列 → prompt→文本同步桥（蜂群两面与 REST 面共用）。

    逐个尝试：调用异常或 ``[LLM Error]`` 文本换下一个候选；全部失败回
    最后一次错误文本（管线按不可解析诚实拒答）。空候选列 → None。
    """
    usable = [c for c in (clients or []) if c is not None]
    if not usable:
        return None

    def _call(prompt: str) -> str:
        from neurova.mem_core import run_async_safely

        last = ""
        for client in usable:
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


def _llmCallOrNull(request: Request, preferAgentId: str = "") -> Optional[Any]:
    """运行时 Agent 的 llm_client → prompt→文本；不可用回 None（诚实拒答）。"""
    try:
        from neurova.api.endpoints.knowledge_common import resolveAgentLlmClients

        clients = resolveAgentLlmClients(request,
                                         prefer_agent_id=preferAgentId or None)
        return llmCallFromClients(clients)
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


# ── 蜂群只读分析档可复用入口（P2-2 车道D）─────────────────────────────────

def _resolveDefaultSourceId(tenant: str, sourceId: str) -> str:
    """source_id 缺省解析：本租户目录里恰好一个源时自动选定。

    多源要求指名（诚实报可选项）；零源如实报未摄取。显式传入的 source_id
    原样返回——其租户归属由 ``_executorFor`` 的 loadConfig（按租户查）把关。
    """
    sourceId = str(sourceId or "").strip()
    if sourceId:
        return sourceId
    from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore
    from neurova.knowledge.foundation import get_knowledge_fact_store

    sources = SchemaCatalogStore(get_knowledge_fact_store()).sourcesInCatalog(tenant)
    if len(sources) == 1:
        return sources[0]
    if not sources:
        raise LookupError("本租户暂无可用企业数据源（先完成 schema 目录摄取）")
    raise LookupError("本租户有多个数据源，需指名 source_id（可选: %s）"
                      % ", ".join(sources[:10]))


def runReadonlyDataQuestion(tenant: str, sourceId: str, question: str,
                            llmCall: Optional[Any], askedBy: str = "",
                            maxRows: int = 200) -> Dict[str, Any]:
    """只读问数可复用入口（成员工具面 / 反向 MCP 面共用，P2-2）。

    - 总闸语义与 REST 面完全一致（``nl2sqlGateOpen`` 单源判定）：关 → 结构化
      ``capability_disabled``（调用方转译为工具错误，不抛裸异常）；
    - 租户隔离在源配置层（loadConfig 本租户查无即 source_not_found）；
    - 只读强制在连接器层（``connectors_sql.assertReadonlySelect``），不靠提示词；
    - 其余走既有 ask 管线（目录 grounding → 生成 → 校验 → 只读执行 → 落账），
      LLM 生成照常记 usage（既有 cost 链自动覆盖）。
    """
    tenant = str(tenant or "default")
    if not nl2sqlGateOpen():
        return {"answerable": False, "status": "capability_disabled",
                "source_id": str(sourceId or ""),
                "error": "NL2SQL 未开闸（%s 未置 on）——能力默认关" % ENV_NL2SQL_ENABLED}
    try:
        resolvedId = _resolveDefaultSourceId(tenant, sourceId)
        executor = _executorFor(tenant, resolvedId)
    except LookupError as exc:
        return {"answerable": False, "status": "source_not_found",
                "source_id": str(sourceId or ""), "error": str(exc)}
    result = _service().answerQuestion(
        tenant, resolvedId, question, llmCall=llmCall, executor=executor,
        askedBy=str(askedBy or ""), execute=True, maxRows=maxRows)
    result["source_id"] = resolvedId
    return result


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
