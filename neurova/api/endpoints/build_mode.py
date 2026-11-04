"""Build API —— 构建会话的 HTTP 面（N0）。

1. POST /api/v1/build/sessions                       — 一句话需求 → 首轮澄清
2. GET  /api/v1/build/sessions/{id}                  — 会话状态
3. POST /api/v1/build/sessions/{id}/answers          — 提交回答（含 secret）
4. POST /api/v1/build/sessions/{id}/approve          — 批次批准，返回 batch_id
5. POST /api/v1/build/sessions/{id}/interactions/{iid}/answer — 构建中提问回答
6. POST /api/v1/build/sessions/{id}/cancel           — 取消
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user
from neurova.build_mode.build_session import (
    BuildSessionError,
    get_build_session_manager,
)
from neurova.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()


class StartBuildRequest(BaseModel):
    request: str = Field(..., min_length=1, description="用户的一句话需求")
    agent_id: str = Field(default="default")
    target_kind: str = Field(default="", description="web | app | game | workflow")
    target_id: str = Field(default="", description="修改既有目标时的 id")


class AnswerItem(BaseModel):
    id: str = ""
    selected: List[str] = Field(default_factory=list)
    custom: str = ""
    secret_value: str = ""


class SubmitAnswersRequest(BaseModel):
    answers: List[AnswerItem] = Field(default_factory=list)
    supplement: str = ""


class ApproveRequest(BaseModel):
    note: str = ""


class InteractionAnswerRequest(BaseModel):
    selected: List[str] = Field(default_factory=list)
    custom: str = ""
    secret_value: str = ""


def _get_agent(agent_id: str):
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _user_can_access_agent(user_id: str, agent_id: str, role: str = "user") -> bool:
    if role == "admin":
        return True
    agent = _get_agent(agent_id)
    if not agent:
        return False
    owner = getattr(getattr(agent, "config", None), "owner_user_id", None)
    return bool(owner) and owner == user_id


def _build_llm_bridge(agent: Any):
    llm_client = getattr(agent, "llm_client", None)
    if llm_client is None:
        raise BuildSessionError("Agent 未配置 LLM 客户端，无法进入构建模式", "llm_failed")

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


def _require_owner(session, current_user: Dict[str, Any]) -> None:
    if current_user.get("role") == "admin":
        return
    if str(session.user_id) != str(current_user.get("user_id") or ""):
        raise HTTPException(status_code=404, detail="构建会话不存在")


def _error(exc: BuildSessionError) -> HTTPException:
    status = 404 if exc.code == "not_found" else (503 if exc.code == "llm_failed" else 400)
    return HTTPException(status_code=status, detail=str(exc))


@router.post("/sessions")
async def start_build_session(
    http_request: Request,
    body: StartBuildRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    user_id = str(current_user.get("user_id") or "")
    role = str(current_user.get("role") or "user")
    if not _user_can_access_agent(user_id, body.agent_id, role):
        raise HTTPException(status_code=403, detail="无权访问该 Agent")
    agent = _get_agent(body.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    try:
        llm_call = _build_llm_bridge(agent)
        session = await get_build_session_manager().create(
            body.request,
            agent_id=body.agent_id,
            user_id=user_id,
            target_kind=body.target_kind,
            target_id=body.target_id,
            llm_call=llm_call,
        )
    except BuildSessionError as exc:
        raise _error(exc)
    return _envelope({"session": session.toDict()}, http_request)


@router.get("/sessions/{session_id}")
async def get_build_session(
    session_id: str,
    http_request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    session = get_build_session_manager().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="构建会话不存在")
    _require_owner(session, current_user)
    return _envelope({"session": session.toDict()}, http_request)


@router.post("/sessions/{session_id}/answers")
async def submit_build_answers(
    session_id: str,
    http_request: Request,
    body: SubmitAnswersRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    manager = get_build_session_manager()
    session = manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="构建会话不存在")
    _require_owner(session, current_user)
    agent = _get_agent(session.agent_id)
    try:
        llm_call = _build_llm_bridge(agent) if agent is not None else None
        session = await manager.answer(
            session_id,
            [item.model_dump() for item in body.answers],
            supplement=body.supplement,
            llm_call=llm_call,
        )
    except BuildSessionError as exc:
        raise _error(exc)
    return _envelope({"session": session.toDict()}, http_request)


@router.post("/sessions/{session_id}/approve")
async def approve_build_session(
    session_id: str,
    http_request: Request,
    body: ApproveRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    manager = get_build_session_manager()
    session = manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="构建会话不存在")
    _require_owner(session, current_user)
    approver = str(current_user.get("username") or current_user.get("user_id") or "")
    try:
        session = manager.approve(session_id, approver)
        session = manager.markBuilding(session_id)
    except BuildSessionError as exc:
        raise _error(exc)
    return _envelope({"session": session.toDict()}, http_request)


@router.post("/sessions/{session_id}/interactions/{interaction_id}/answer")
async def answer_build_interaction(
    session_id: str,
    interaction_id: str,
    http_request: Request,
    body: InteractionAnswerRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    manager = get_build_session_manager()
    session = manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="构建会话不存在")
    _require_owner(session, current_user)
    try:
        session = manager.answerInteraction(session_id, interaction_id, body.model_dump())
    except BuildSessionError as exc:
        raise _error(exc)
    return _envelope(
        {
            "session": session.toDict(),
            "interaction_id": interaction_id,
        },
        http_request,
    )


@router.post("/sessions/{session_id}/cancel")
async def cancel_build_session(
    session_id: str,
    http_request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    manager = get_build_session_manager()
    session = manager.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="构建会话不存在")
    _require_owner(session, current_user)
    try:
        session = manager.cancel(session_id)
    except BuildSessionError as exc:
        raise _error(exc)
    return _envelope({"session": session.toDict()}, http_request)
