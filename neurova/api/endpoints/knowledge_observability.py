# -*- coding: utf-8 -*-
"""默认关能力读数面（升级计划 §15.1「观测与开关」欠的服务端面）。

只做一件事：把 §13.1 那九项开关的**现值**一次报清楚，让前端的开关面板不再抄一张
静态表。九项的名册与解点在 `neurova.knowledge.defaultOffFlags`，本模块不读环境变量、
不解释语义，也不提供任何写入：

- 默认关是产品/成本/安全决定（§6「不打包全开」），不是断点；本页的职责是**可观测**，
  不是把开闸做成一个按钮；
- 因此本面只报开关态与归属模块，不回传任何环境变量的实际内容（判据⑤钉这一条）。

治理门：管理员可读，非管理员 403，未登录 401——服务器开关态不是公开面。
独立叶子：端点逻辑不塞 knowledge_ontology.py（尺寸纪律），挂载走 `knowledge.py` 聚合器。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.core.tenant_scope import resolve_tenant

router = APIRouter()


def _tenantOf(current_user: Dict[str, Any]) -> str:
    """操作者租户：探针读面的分区键（缺省 default）。"""
    return resolve_tenant(current_user)


@router.get("/observability/default-off")
async def getDefaultOffReadings(
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """九项默认关开关的现值形读数（登录且管理员）。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="默认关能力态是服务器配置面，仅管理员可读")

    from neurova.knowledge.defaultOffFlags import defaultOffReadings

    return {"code": 0, "message": "success", "data": {"items": defaultOffReadings()}}


@router.get("/ontology/cq-matrix")
async def getCqMatrix(
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """CQ 追溯现值读数（登录可读）：元数据照 specs 票面，status 为探针现值。

    与 default-off 不同门：能力现值不是服务器配置面（探针只查产品面符号，
    不读任何开关），本体的 CQ 目录对全部登录使用者可见——知识使用者/审计员
    也是票面里的角色。名册与探针在 `neurova/knowledge/ontology/cq_matrix.py`。
    """
    from neurova.knowledge.ontology.cq_matrix import cqTraceRows

    return {"code": 0, "message": "success", "data": {"items": cqTraceRows()}}


@router.get("/ontology/readiness")
async def getKnowledgeReadiness(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """复合就绪探针（P2-2/P2-3，登录可读）：knowledge/data/model 三判据。

    术语/事实/目录/源现值一次报清；只读，不提供启停动作。model_ready 是
    **可选**模型能力体检（P2-3）：env `NEUROVA_ONTOLOGY_MODEL_PROBE` 默认关
    （关=disabled，零网络零成本）；开了才对 LLM 客户端面发一次最小探针，
    失败如实报因。事实源在 `neurova/knowledge/ontology/readiness.py`。
    """
    import os

    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.readiness import knowledgeReadiness

    store = get_knowledge_fact_store()
    modelProbe = None
    if str(os.environ.get("NEUROVA_ONTOLOGY_MODEL_PROBE") or "").strip().lower() \
            in ("1", "true", "on"):
        def modelProbe() -> Dict[str, Any]:
            from neurova.api.endpoints.knowledge_common import resolveAgentLlmClients
            from neurova.mem_core import run_async_safely

            clients = resolveAgentLlmClients(request)
            if not clients:
                return {"ok": False, "detail": "no LLM client configured"}
            for client in clients:
                try:
                    resp = run_async_safely(
                        client.chat([{"role": "user", "content": "ping"}]))
                except Exception:  # noqa: BLE001 - 换下一个候选
                    continue
                content = getattr(resp, "content", "") or ""
                if content.startswith("[LLM Error]"):
                    continue
                return {"ok": True, "detail": "pong"}
            return {"ok": False, "detail": "all LLM clients failed probe"}

    return {"code": 0, "message": "success",
            "data": knowledgeReadiness(store, _tenantOf(current_user),
                                       modelProbe=modelProbe)}


@router.get("/ontology/audit")
async def getOntologyAudit(
    source_id: str = "",
    stale_days: int = 7,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """数据驱动本体缺口审计（P1-2，仅管理员）：目录/候选队列的缺口与漂移。

    五类信号：uncovered（表无术语链接）/ broken_reference（外键指向目录外表）/
    clash（一术语链接多表）/ stale（pending 超期未审）/ ambiguity（同源同名表）。
    零模型调用、纯只读；每条带跨轮稳定 fingerprint 与建议动作。
    判据单一出处 `neurova/knowledge/ontology/audit.py::auditOntologyCoverage`。
    """
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403,
                            detail="本体缺口审计是治理读数面，仅管理员可读")
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.audit import auditOntologyCoverage

    store = get_knowledge_fact_store()
    out = auditOntologyCoverage(store, _tenantOf(current_user),
                                sourceId=str(source_id or "").strip(),
                                staleDays=max(0, int(stale_days)))
    return {"code": 0, "message": "success", "data": out}


class AnswerabilityRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    agent_id: str = ""
    use_llm: bool = False


@router.post("/ontology/answerability")
async def checkOntologyAnswerability(
    body: AnswerabilityRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """实体覆盖预检（P1-3，登录可读）：coverage 低就反问澄清，别硬答。

    只读探针：抽实体（use_llm 可选，缺省确定性分词）→ 对术语/事实主体做
    词面覆盖匹配 → 命中占比。判据单一出处
    `neurova/knowledge/ontology/answerability.py`。
    """
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.answerability import assessAnswerability

    store = get_knowledge_fact_store()
    tenant = _tenantOf(current_user)
    llmCall = None
    if body.use_llm:
        try:
            from neurova.api.endpoints.knowledge_common import resolveAgentLlmClients
            from neurova.mem_core import run_async_safely

            clients = resolveAgentLlmClients(request, prefer_agent_id=body.agent_id or None)

            def _call(prompt: str):
                for client in clients:
                    try:
                        resp = run_async_safely(
                            client.chat([{"role": "user", "content": prompt}]))
                    except Exception:  # noqa: BLE001 - 换下一个候选
                        continue
                    content = getattr(resp, "content", "") or ""
                    if content.startswith("[LLM Error]"):
                        continue
                    return content
                return ""

            llmCall = _call if clients else None
        except Exception:  # noqa: BLE001 - LLM 不可用回退确定性分词
            llmCall = None
    result = assessAnswerability(store, body.question, tenantId=tenant,
                                 agentId=body.agent_id or "default",
                                 llmCall=llmCall, threshold=body.threshold)
    return {"code": 0, "message": "success", "data": result}
