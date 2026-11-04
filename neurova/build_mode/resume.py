"""构建交互回答后的服务端续跑（§12.4）。

回答落库后由服务端自动拉起 Agent 回合，不再要求前端再发一条续跑消息。
续跑仍走 `agent.chat` 原管线：会话消息落盘、AGENT_REPLY 广播到
`SessionSyncManager`，前端在同一条会话上被动收到结果。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional

from neurova.core.logger import get_logger

from .build_session import BuildSession, BuildSessionManager, get_build_session_manager

logger = get_logger(__name__)

_RESUME_TASKS: set = set()


def buildResumePrompt(session: BuildSession, interaction: Dict[str, Any]) -> str:
    """生成服务端续跑提示；secret 答案只报「已配置」，绝不带值。"""
    question = interaction.get("question") or {}
    answer = interaction.get("answer") or {}
    if question.get("kind") == "secret":
        answerText = "凭据已配置" if answer.get("configured") else "未提供凭据"
    else:
        parts = [str(item) for item in (answer.get("selected") or []) if str(item).strip()]
        custom = str(answer.get("custom") or "").strip()
        if custom:
            parts.append(custom)
        answerText = " / ".join(parts) or "未填写"
    plan = (session.build_plan or {}).get("summary") or "按已确认问答继续"
    return "\n".join(
        [
            f"构建会话 {session.session_id} 的交互已回答。",
            f"需求：{session.request}",
            f"构建计划：{plan}",
            f"问题：{question.get('question') or ''}",
            f"回答：{answerText}",
            "请继续构建；遇到新疑问用 ask_user 面板，不要自行假设。",
        ]
    )


def _defaultAgentProvider(agent_id: str):
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


async def _publishBuildEvent(
    syncManager,
    *,
    sessionId: str,
    eventType: Any,
    payload: Dict[str, Any],
    userId: str = "",
    agentId: str = "",
) -> None:
    try:
        from neurova.sync.session_sync_manager import (
            EventType,
            SessionEvent,
            get_session_sync_manager,
        )

        manager = syncManager or get_session_sync_manager()
        register = getattr(manager, "register_or_create_session", None)
        if callable(register):
            register(
                session_id=sessionId,
                user_id=userId or "anonymous",
                agent_id=agentId or "default",
                metadata={"source": "build_resume"},
            )
        event = SessionEvent(
            event_type=eventType,
            session_id=sessionId,
            source_channel="build",
            payload=dict(payload),
        )
        await manager.broadcast_event(sessionId, event)
    except Exception as exc:  # noqa: BLE001 - 广播失败不改变续跑结果
        logger.warning("构建续跑事件广播失败: %s", exc)


async def resumeBuildInteraction(
    sessionId: str,
    interactionId: str,
    *,
    agentProvider: Optional[Callable[[str], Any]] = None,
    sessionSyncManager=None,
    manager: Optional[BuildSessionManager] = None,
) -> Dict[str, Any]:
    """回答后自动拉起 Agent 回合；返回 started/status/chat_session_id。"""
    manager = manager or get_build_session_manager()
    session = manager.get(sessionId)
    if session is None:
        return {"started": False, "reason": "not_found"}
    interaction = next(
        (
            item
            for item in session.interactions
            if item.get("interaction_id") == interactionId
        ),
        None,
    )
    if interaction is None:
        return {"started": False, "reason": "interaction_not_found"}
    resumePrompt = buildResumePrompt(session, interaction)
    chatSessionId = str(interaction.get("chat_session_id") or "").strip()
    if not chatSessionId:
        return {
            "started": False,
            "reason": "no_chat_session",
            "resume_prompt": resumePrompt,
        }

    provider = agentProvider or _defaultAgentProvider
    agent = provider(session.agent_id)
    if agent is None:
        from neurova.sync.session_sync_manager import EventType

        await _publishBuildEvent(
            sessionSyncManager,
            sessionId=chatSessionId,
            eventType=EventType.BUILD_RESUME_FAILED,
            payload={
                "build_session_id": sessionId,
                "interaction_id": interactionId,
                "error": f"Agent 不存在: {session.agent_id}",
                "resume_prompt": resumePrompt,
            },
            userId=session.user_id,
            agentId=session.agent_id,
        )
        return {
            "started": True,
            "status": "failed",
            "error": f"Agent 不存在: {session.agent_id}",
            "chat_session_id": chatSessionId,
            "resume_prompt": resumePrompt,
        }

    from neurova.core.build_context import (
        resetCurrentBuildSessionId,
        setCurrentBuildSessionId,
    )
    from neurova.core.identity_context import set_request_user_id

    setCurrentBuildSessionId(sessionId)
    set_request_user_id(session.user_id or None)
    try:
        response = await agent.chat(
            user_input=resumePrompt,
            session_id=chatSessionId,
            metadata={
                "build_session_id": sessionId,
                "build_resume": True,
                "user_id": session.user_id,
                "agent_id": session.agent_id,
            },
        )
    except Exception as exc:  # noqa: BLE001 - 失败要如实广播，不伪造完成
        from neurova.sync.session_sync_manager import EventType

        logger.warning("构建续跑 Agent 回合失败: %s", exc)
        await _publishBuildEvent(
            sessionSyncManager,
            sessionId=chatSessionId,
            eventType=EventType.BUILD_RESUME_FAILED,
            payload={
                "build_session_id": sessionId,
                "interaction_id": interactionId,
                "error": str(exc),
                "resume_prompt": resumePrompt,
            },
            userId=session.user_id,
            agentId=session.agent_id,
        )
        return {
            "started": True,
            "status": "failed",
            "error": str(exc),
            "chat_session_id": chatSessionId,
            "resume_prompt": resumePrompt,
        }
    finally:
        resetCurrentBuildSessionId()
        set_request_user_id(None)

    refreshed = manager.get(sessionId) or session
    pending = [item for item in refreshed.interactions if item.get("status") == "pending"]
    if pending:
        from neurova.sync.session_sync_manager import EventType

        last = pending[-1]
        question = last.get("question") or {}
        await _publishBuildEvent(
            sessionSyncManager,
            sessionId=chatSessionId,
            eventType=EventType.BUILD_INTERACTION,
            payload={
                "build_session_id": sessionId,
                "interaction_id": last.get("interaction_id"),
                "question": question.get("question"),
                "kind": question.get("kind"),
                "options": question.get("options") or [],
                "multi": bool(question.get("multi")),
                "allow_custom": bool(question.get("allow_custom")),
                "why": question.get("why") or "",
                "impact": question.get("impact") or "",
                "secret_key": question.get("secret_key") or "",
                "timeout_seconds": question.get("timeout_seconds") or 600,
            },
            userId=session.user_id,
            agentId=session.agent_id,
        )

    reply = ""
    if isinstance(response, dict):
        reply = str(response.get("text") or "")
    elif response is not None:
        reply = str(response)
    return {
        "started": True,
        "status": "completed",
        "chat_session_id": chatSessionId,
        "resume_prompt": resumePrompt,
        "reply_chars": len(reply),
        "pending_interaction": pending[-1].get("interaction_id") if pending else "",
    }


def startBuildResume(sessionId: str, interactionId: str) -> bool:
    """在请求事件循环里启动后台续跑；无运行中 loop 返回 False 由调用方降级。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    task = loop.create_task(resumeBuildInteraction(sessionId, interactionId))
    _RESUME_TASKS.add(task)
    task.add_done_callback(_RESUME_TASKS.discard)
    return True


__all__ = [
    "buildResumePrompt",
    "resumeBuildInteraction",
    "startBuildResume",
]
