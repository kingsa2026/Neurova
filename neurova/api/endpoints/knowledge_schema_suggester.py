# -*- coding: utf-8 -*-
"""schema 建议器 REST 面（P1-2，2026-11-15）。

独立叶子：端点逻辑不塞 knowledge_ontology.py（尺寸纪律），挂载走
`knowledge.py` 聚合器（与 knowledge_enterprise/knowledge_observability 同款）。

- run 是治理动作（仅管理员）：产出的是**候选**，不直接改本体；
- 审批走本面（术语建议）；关系候选复用 `/ontology/relation-candidates/*`
  既有审批端点（B8 面），本模块不另造第二套关系审批；
- LLM 精化可选（use_llm，缺省关——确定性基线永远先成立）；join 探针可选
  （probe，缺省关；仅 SQL 族源可用，经适配器 executeReadonly 只读口）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service

router = APIRouter()


class SchemaSuggestionRunRequest(BaseModel):
    source_id: str = ""
    use_llm: bool = False
    probe: bool = False
    max_workers: int = Field(default=3, ge=1, le=8)


def _tenantOf(current_user: Dict[str, Any]) -> str:
    return str(current_user.get("tenant_id") or "default")


def _requireAdmin(current_user: Dict[str, Any]) -> None:
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403,
                            detail="schema 建议是治理动作，仅管理员可执行")


def _suggester():
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.schema_suggester import SchemaSuggester

    store = get_knowledge_fact_store()
    return SchemaSuggester(store)


def _llmCallOrNull(request: Request, tenant: str) -> Optional[Any]:
    """运行时 Agent 的 llm_client → prompt→文本 调用器；不可用回 None（纯规则）。"""
    try:
        from neurova.api.endpoints.knowledge_common import resolveAgentLlmClients
        from neurova.mem_core import run_async_safely

        clients = resolveAgentLlmClients(request)
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
    except Exception:  # noqa: BLE001 - 解析失败按无 LLM 处理（纯规则建议照常产出）
        return None


def _probeRunnerFactory(tenant: str):
    """join 探针执行器工厂：按源构造适配器，只认实现 executeReadonly 的 SQL 族。"""
    from neurova.knowledge.enterprise.registry import buildAdapter, EnterpriseIngestor
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.mem_core import run_async_safely

    ingestor = EnterpriseIngestor(get_knowledge_fact_store())

    def factory(sourceId: str):
        config = ingestor.loadConfig(tenant, sourceId)
        if config is None:
            return None
        descriptor = dict(config["descriptor"])
        descriptor["tenantId"] = tenant
        descriptor["sourceId"] = sourceId
        try:
            adapter = buildAdapter(descriptor, sourceId, tenant)
        except Exception:  # noqa: BLE001 - 建不了适配器＝无探针，建议照常产出
            return None
        execute = getattr(adapter, "executeReadonly", None)
        if execute is None:
            return None

        def runner(sql: str):
            return run_async_safely(execute(sql, 1))

        return runner

    return factory


@router.get("/ontology/schema-suggestions")
async def listSchemaSuggestions(
    status: str = "pending",
    source_id: str = "",
    kind: str = "",
    limit: int = 100,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """术语建议清单（登录可读）：status/source_id/kind 过滤。"""
    try:
        items = _suggester().listSuggestions(
            _tenantOf(current_user), status=status,
            sourceId=str(source_id or "").strip(), kind=str(kind or "").strip(),
            limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "success", "data": {"items": items,
                                                      "total": len(items)}}


@router.post("/ontology/schema-suggestions/run")
async def runSchemaSuggestions(
    body: SchemaSuggestionRunRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """跑一轮建议（仅管理员）：目录 → 术语建议 + 关系候选。

    use_llm/probe 都缺省关：纯规则建议零 LLM 零探针；开 LLM 失败回退规则；
    探针只对命名规约推断的外键边做 join 证实，失败如实未证实。
    """
    _requireAdmin(current_user)
    tenant = _tenantOf(current_user)
    suggester = _suggester()
    llmCall = _llmCallOrNull(request, tenant) if body.use_llm else None
    probeFactory = _probeRunnerFactory(tenant) if body.probe else None
    if body.source_id.strip():
        outcome = suggester.runForSource(
            tenant, body.source_id.strip(), llmCall=llmCall,
            probeRunner=probeFactory(body.source_id.strip()) if probeFactory else None)
        return {"code": 0, "message": "success", "data": {"sources": [outcome]}}
    outcome = suggester.runForAllSources(tenant, llmCall=llmCall,
                                         probeRunnerFactory=probeFactory,
                                         maxWorkers=body.max_workers)
    return {"code": 0, "message": "success", "data": outcome}


@router.post("/ontology/schema-suggestions/{suggestion_id}/approve")
async def approveSchemaSuggestion(
    suggestion_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """批准术语建议（仅管理员）：登记概念术语 + 回填目录 term_id 链接。"""
    _requireAdmin(current_user)
    try:
        result = _suggester().decideSuggestion(
            _tenantOf(current_user), str(suggestion_id or "").strip(),
            "approved", reviewedBy=str(current_user.get("username") or ""))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"code": 0, "message": "success", "data": result}


@router.post("/ontology/schema-suggestions/{suggestion_id}/reject")
async def rejectSchemaSuggestion(
    suggestion_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """拒绝建议（仅管理员）：留审计行，同目标不再重生。"""
    _requireAdmin(current_user)
    try:
        result = _suggester().decideSuggestion(
            _tenantOf(current_user), str(suggestion_id or "").strip(),
            "rejected", reviewedBy=str(current_user.get("username") or ""))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"code": 0, "message": "success", "data": result}


class FamilyDetectRequest(BaseModel):
    source_id: str = Field(min_length=1)


@router.post("/ontology/schema-families/detect")
async def detectSchemaFamilies(
    body: FamilyDetectRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """同构表副本聚族（P3-2，仅管理员）：OLD_/NEW_ 前缀孪生表 → family 候选。

    确定性算法（列名集合 Jaccard≥0.8，历史表除外），产物是 pending 建议；
    显式触发，无自动跑批。
    """
    _requireAdmin(current_user)
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.schema_families import suggestFamilies

    store = get_knowledge_fact_store()
    suggester = _suggester()
    result = suggestFamilies(suggester, suggester._catalog,
                             _tenantOf(current_user), body.source_id.strip())
    return {"code": 0, "message": "success", "data": result}
