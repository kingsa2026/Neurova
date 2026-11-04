"""带外审批执行后的自动续跑轮（候选 C3 批次 1）。

缺口实锤（2026-11-05 摸底，spec 见 docs/specs/2026-11-05-审批带外执行后自动续跑轮设计.md）：
带外批准（原轮已收尾 / 进程重启后人工批准）重放执行后，工具终态只进
``tool_coordinator._pending_hints`` 晚到队列——「下一轮才被读到」；没有人再说话，
结果就沉在队列里，用户批准后拿不到任何主动汇报。

本模块在带外重放完成后自动拉起一轮续跑，形态复用 ``build_mode/resume.py``
（§12.4）的服务端拉起：identity 单通道（§6-163）→ ``agent.chat`` 原管线
（会话落盘 / AGENT_REPLY 广播照走）。

范围裁定（spec §4 不做清单）：
- 不做帧级快照/任意断点恢复——审批域恢复诉求已被「带外重放 + 续跑轮」闭环，
  帧树机器属投机面（修复教义第 1 条）；
- 续跑轮走正常 run ledger 准入，不绕闸；
- 默认关（``governance_settings.approval_continuation_enabled``，工单 015 口径：
  默认值＝现网语义；env ``NEUROVA_APPROVAL_CONTINUATION`` 显式 0/1 最优先）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_CONTINUATION_TASKS: set = set()


def _continuationEnabled() -> bool:
    from neurova.security.governance_settings import resolve_flag

    return resolve_flag("approval_continuation_enabled", "NEUROVA_APPROVAL_CONTINUATION")


def _defaultAgentProvider(agent_id: str):
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def buildContinuationPrompt(
    request_id: str, tool_name: str, success: bool, error: str = ""
) -> str:
    """续跑提示词：点名审批号/工具/成败与错误摘要；要求继续原任务并如实汇报，
    结果不足时明说缺什么——不编造（修复教义第 2 条：诚实形态）。"""
    if success:
        outcome = "执行成功"
    else:
        outcome = "执行失败" + (f"（{error}）" if error else "")
    return "\n".join(
        [
            f"审批 {request_id} 的工具 {tool_name} 已由人工批准并带外执行完毕：{outcome}。",
            "本次工具调用的晚到终态已随本轮上下文注入。",
            "请基于该结果继续完成原任务，并向用户汇报进展与结论；"
            "若结果不足以继续，如实说明缺什么，不要编造。",
        ]
    )


async def runApprovalContinuation(
    *,
    request_id: str,
    agent_id: str,
    user_id: str,
    session_id: str,
    tool_name: str,
    success: bool,
    error: str = "",
    agentProvider: Optional[Any] = None,
) -> Dict[str, Any]:
    """拉起一轮续跑并等它收尾。返回 started/status（失败如实带 error，不伪造完成）。"""
    if not _continuationEnabled():
        return {"started": False, "reason": "disabled"}
    if not str(session_id or "").strip():
        # 无会话归属不拉起：晚到通路同款纪律（宁可点名拒绝，不塞进别人的上下文）
        return {"started": False, "reason": "no_session"}
    provider = agentProvider or _defaultAgentProvider
    agent = provider(str(agent_id or "default"))
    if agent is None:
        return {"started": False, "reason": "agent_not_ready", "agent_id": agent_id}

    from neurova.core.identity_context import set_request_user_id

    set_request_user_id(str(user_id) if user_id else None)
    try:
        await agent.chat(
            user_input=buildContinuationPrompt(request_id, tool_name, success, error),
            session_id=str(session_id),
            metadata={
                "approval_continuation": True,
                "approval_request_id": request_id,
                "user_id": str(user_id or ""),
                "agent_id": str(agent_id or ""),
            },
        )
    except Exception as exc:  # noqa: BLE001 - 续跑失败如实返回，不伪造完成
        logger.warning("审批续跑轮失败: %s (request=%s)", exc, request_id)
        return {"started": True, "status": "failed", "error": str(exc)}
    finally:
        set_request_user_id(None)
    return {"started": True, "status": "completed"}


def startApprovalContinuation(
    *,
    request_id: str,
    agent_id: str,
    user_id: str,
    session_id: str,
    tool_name: str,
    success: bool,
    error: str = "",
) -> bool:
    """在当前事件循环里启动后台续跑；无运行 loop 返回 False（调用方降级为仅投递）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False

    async def _run() -> None:
        await runApprovalContinuation(
            request_id=request_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id,
            tool_name=tool_name,
            success=success,
            error=error,
        )

    task = loop.create_task(_run())
    _CONTINUATION_TASKS.add(task)
    task.add_done_callback(_CONTINUATION_TASKS.discard)
    return True


__all__ = [
    "buildContinuationPrompt",
    "runApprovalContinuation",
    "startApprovalContinuation",
]
