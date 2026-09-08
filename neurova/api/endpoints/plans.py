from __future__ import annotations

"""Plans API —— 计划模式端点（ZCode 计划模式对齐）

交互式计划工作流的 HTTP 面：
1. POST /api/v1/plans/sessions                     — 发起计划会话（首轮澄清问题）
2. GET  /api/v1/plans/sessions/{session_id}        — 会话状态
3. POST /api/v1/plans/sessions/{session_id}/answers    — 提交回答/补充（不限轮）
4. POST /api/v1/plans/sessions/{session_id}/decision   — 审批（approve 返回
   execute_prompt，含计划全文，前端走聊天原链路执行）
5. GET  /api/v1/plans/documents?agent_id=…         — 计划文档列表
6. GET  /api/v1/plans/documents/{name}?agent_id=…  — 计划文档预览（MD 渲染数据源）

隔离语义：会话按 user 隔离（非本人 404）；agent 访问沿用聊天端点同款规则
（admin 全量 / 普通用户仅属主 / 无属主仅 admin）；文档按 agent 隔离。
"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger
from neurova.plan_mode.errors import (
    PlanDocError,
    PlanDocNotFound,
    PlanError,
    PlanLLMError,
    PlanStateError,
)
from neurova.plan_mode.plan_docs import PlanDocStore
from neurova.plan_mode.plan_session import PlanSessionManager

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class StartPlanRequest(BaseModel):
    """发起计划会话"""

    agent_id: str = Field(default="default", description="Agent ID")
    request: str = Field(..., min_length=1, description="原始需求描述")


class AnswerItem(BaseModel):
    """单条回答"""

    id: str = Field(default="", description="问题 ID")
    selected: List[str] = Field(default_factory=list, description="选中选项")
    custom: str = Field(default="", description="自由补充文本")


class SubmitAnswersRequest(BaseModel):
    """提交一轮回答/补充"""

    answers: List[AnswerItem] = Field(default_factory=list, description="回答列表")
    supplement: str = Field(default="", description="自由补充")


class PlanDecisionRequest(BaseModel):
    """审批决定"""

    action: str = Field(..., description="approve | reject")
    note: str = Field(default="", description="备注")


# ---------------------------------------------------------------------------
# 依赖（模块级便于测试 patch）
# ---------------------------------------------------------------------------


def _get_agent(agent_id: str):
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _user_can_access_agent(user_id: str, agent_id: str, role: str = "user") -> bool:
    """与 chat 端点同款规则：admin 全量 / 属主 / 无属主仅 admin。"""
    if role == "admin":
        return True
    agent = _get_agent(agent_id)
    if not agent:
        return False
    owner_user_id = getattr(agent.config, "owner_user_id", None)
    if not owner_user_id:
        return False
    return owner_user_id == user_id


def _get_doc_store() -> PlanDocStore:
    from neurova.plan_mode.plan_docs import get_plan_doc_store

    return get_plan_doc_store()


def _get_session_manager() -> PlanSessionManager:
    from neurova.plan_mode.plan_session import get_plan_session_manager

    return get_plan_session_manager()


def _build_llm_bridge(agent: Any):
    """把 agent 的 MultiModelLLMClient 桥成 plan 模块的 llm_call(prompt)->str。

    LLM 未配置时抛 PlanLLMError（端点映射 503）。
    """
    llm_client = getattr(agent, "llm_client", None)
    if llm_client is None:
        raise PlanLLMError("Agent 未配置 LLM 客户端，无法进入计划模式")

    async def llm_call(prompt: str) -> str:
        model = getattr(getattr(agent, "config", None), "llm_model", None)
        response = await llm_client.chat([{"role": "user", "content": prompt}], model=model)
        if isinstance(response, dict):
            return str(response.get("content") or "")
        return str(getattr(response, "content", "") or "")

    return llm_call


def _envelope(data: Any, request: Request) -> Dict[str, Any]:
    return {
        "code": 0,
        "message": "success",
        "data": data,
        "request_id": getattr(request.state, "request_id", str(uuid.uuid4())),
    }


def _error(status: int, code: int, message: str, request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", str(uuid.uuid4())),
        },
    )


# ---------------------------------------------------------------------------
# 会话端点
# ---------------------------------------------------------------------------


@router.post("/sessions")
async def start_plan_session(
    http_request: Request,
    body: StartPlanRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """发起计划会话：出首轮澄清问题。"""
    user_id = current_user.get("user_id", "")
    role = current_user.get("role", "user")
    if not _user_can_access_agent(user_id, body.agent_id, role):
        agent = _get_agent(body.agent_id)
        return _error(404 if not agent else 403, 4030 if agent else 3000,
                      f"Agent '{body.agent_id}' not found" if not agent
                      else "Permission denied: you don't have access to this Agent", http_request)

    try:
        agent = _get_agent(body.agent_id)
        llm_call = _build_llm_bridge(agent)
        session = await _get_session_manager().create(
            agent_id=body.agent_id, user_id=user_id, request=body.request, llm_call=llm_call
        )
        return _envelope({"session": session.to_dict()}, http_request)
    except PlanLLMError as e:
        return _error(503, 5030, str(e), http_request)
    except PlanError as e:
        return _error(400, 4001, str(e), http_request)
    except Exception as e:  # noqa: BLE001
        logger.error("计划会话发起失败: %s", e, exc_info=True)
        return _error(500, 5000, f"Plan session failed: {e}", http_request)


@router.get("/sessions/{session_id}")
async def get_plan_session(
    session_id: str,
    http_request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """读取会话状态（非本人/不存在/过期一律 404，不泄漏存在性）。"""
    user_id = current_user.get("user_id", "")
    session = _get_session_manager().get(session_id, user_id)
    if session is None:
        return _error(404, 3000, "Plan session not found", http_request)
    return _envelope({"session": session.to_dict()}, http_request)


@router.post("/sessions/{session_id}/answers")
async def submit_answers(
    session_id: str,
    body: SubmitAnswersRequest,
    http_request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """提交一轮回答/自由补充 → 出下一轮问题或生成计划文档。"""
    user_id = current_user.get("user_id", "")
    session = _get_session_manager().get(session_id, user_id)
    if session is None:
        return _error(404, 3000, "Plan session not found", http_request)
    try:
        data = await session.submit_answers(
            answers=[a.model_dump() for a in body.answers], supplement=body.supplement
        )
        return _envelope({"session": data}, http_request)
    except PlanStateError as e:
        return _error(400, 4001, str(e), http_request)
    except PlanLLMError as e:
        return _error(503, 5030, str(e), http_request)
    except Exception as e:  # noqa: BLE001
        logger.error("计划问答推进失败: %s", e, exc_info=True)
        return _error(500, 5000, f"Plan answers failed: {e}", http_request)


@router.post("/sessions/{session_id}/decision")
async def decide_plan(
    session_id: str,
    body: PlanDecisionRequest,
    http_request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """审批决定。approve 返回 execute_prompt（含计划全文）。"""
    user_id = current_user.get("user_id", "")
    session = _get_session_manager().get(session_id, user_id)
    if session is None:
        return _error(404, 3000, "Plan session not found", http_request)
    try:
        data = await session.decide(body.action, note=body.note)
        return _envelope({"session": data, "execute_prompt": session.execute_prompt}, http_request)
    except PlanStateError as e:
        return _error(400, 4001, str(e), http_request)
    except PlanDocError as e:
        return _error(400, 4002, str(e), http_request)
    except Exception as e:  # noqa: BLE001
        logger.error("计划审批失败: %s", e, exc_info=True)
        return _error(500, 5000, f"Plan decision failed: {e}", http_request)


# ---------------------------------------------------------------------------
# 计划文档端点
# ---------------------------------------------------------------------------


@router.get("/documents")
async def list_plan_documents(
    http_request: Request,
    agent_id: str = Query(default="default"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出 agent 工作目录 docs/plan/ 下的计划文档（最新在前）。"""
    user_id = current_user.get("user_id", "")
    role = current_user.get("role", "user")
    if not _user_can_access_agent(user_id, agent_id, role):
        return _error(403, 4030, "Permission denied: you don't have access to this Agent", http_request)
    try:
        documents = _get_doc_store().list_documents(agent_id)
        return _envelope({"documents": documents}, http_request)
    except Exception as e:  # noqa: BLE001
        logger.error("计划文档列表失败: %s", e, exc_info=True)
        return _error(500, 5000, f"Plan documents failed: {e}", http_request)


@router.get("/documents/{name:path}")
async def read_plan_document(
    name: str,
    http_request: Request,
    agent_id: str = Query(default="default"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """读取计划文档全文（前端 MD 预览数据源）。"""
    user_id = current_user.get("user_id", "")
    role = current_user.get("role", "user")
    if not _user_can_access_agent(user_id, agent_id, role):
        return _error(403, 4030, "Permission denied: you don't have access to this Agent", http_request)
    try:
        store = _get_doc_store()
        content = store.read(agent_id, name)
        documents = store.list_documents(agent_id)
        meta = next((d for d in documents if d["name"] == name), {"name": name})
        return _envelope({**meta, "content": content}, http_request)
    except PlanDocNotFound:
        return _error(404, 3000, "Plan document not found", http_request)
    except PlanDocError as e:
        return _error(400, 4002, str(e), http_request)
    except Exception as e:  # noqa: BLE001
        logger.error("计划文档读取失败: %s", e, exc_info=True)
        return _error(500, 5000, f"Plan document failed: {e}", http_request)
