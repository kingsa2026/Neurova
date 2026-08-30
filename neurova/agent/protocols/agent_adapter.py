"""
Agent → ACP 协议适配层

把运行时 Agent 实例（app_state["agents"] 注册中心）包装为 ACP 消息处理器，
使 Agent 能通过 ACPRuntime 收发 TASK_ASSIGNMENT 等标准消息——
AgentTeam.orchestrate 的消息式编排由此获得真实执行体。

职责：
1. register_runtime_agents(): 扫描 Agent 注册中心，逐个包装并注册到 ACPRuntime
2. make_agent_handler(): 构造单个 Agent 的消息处理器（action 分发 → agent.chat）

设计约束（AGENTS.md）:
- 延迟导入注册中心，避免循环依赖
- handler 内异常隔离：失败返回 TASK_RESULT(error) 而非抛出
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def make_agent_handler(agent: Any) -> Any:
    """构造单个 Agent 的 ACP 消息处理器

    处理 TASK_ASSIGNMENT：action="chat"（默认）→ agent.chat(task)，
    返回 TASK_RESULT 响应消息（correlation_id 关联）。
    """

    async def handler(message: Any) -> Any:
        from neurova.agent.protocols.message_protocol import AgentMessage, MessageType

        action = (message.action or "chat").lower()
        params = message.params or {}
        task = params.get("task") or message.data.get("task") or str(message.data or "")

        reply_payload: Dict[str, Any]
        try:
            if action in ("chat", "task", "task_assignment"):
                if not task:
                    raise ValueError("task 不能为空")
                response = await agent.chat(task, metadata={"source": "acp"})
                reply_payload = {
                    "success": True,
                    "action": action,
                    "result": response.get("text", "") if isinstance(response, dict) else str(response),
                }
            elif action == "status":
                cfg = getattr(agent, "config", None)
                reply_payload = {
                    "success": True,
                    "action": action,
                    "result": {
                        "name": getattr(cfg, "name", ""),
                        "model": getattr(getattr(cfg, "llm_config", None), "model", ""),
                    },
                }
            else:
                reply_payload = {"success": False, "action": action, "error": f"未知 action: {action}"}
        except Exception as e:  # noqa: BLE001 - handler 故障隔离为失败响应
            logger.warning("ACP handler 执行失败 (%s/%s): %s", message.receiver_id, action, e)
            reply_payload = {"success": False, "action": action, "error": str(e)}

        return AgentMessage(
            type=MessageType.TASK_RESULT,
            sender_id=message.receiver_id,
            sender_name=message.receiver_name,
            receiver_id=message.sender_id,
            receiver_name=message.sender_name,
            action=action,
            data=reply_payload,
            correlation_id=message.correlation_id,
        )

    return handler


def register_runtime_agents(agent_ids: Optional[list] = None) -> Dict[str, Any]:
    """把 Agent 注册中心中的实例注册到 ACPRuntime

    Args:
        agent_ids: 指定注册的 Agent ID 列表；None 注册全部

    Returns:
        {"registered": [agent_id...], "count": N}
    """
    from neurova.agent.protocols.acp_runtime import get_acp_runtime
    from neurova.api.endpoints import get_app_state

    runtime = get_acp_runtime()
    state = get_app_state() or {}
    agents: Dict[str, Any] = state.get("agents", {}) or {}

    registered = []
    for aid, agent in agents.items():
        if agent is None:
            continue
        if agent_ids is not None and aid not in agent_ids:
            continue
        runtime.register_agent(aid, make_agent_handler(agent))
        registered.append(aid)

    logger.info("ACP 运行时 Agent 注册完成: %s", registered)
    return {"registered": registered, "count": len(registered)}


__all__ = ["make_agent_handler", "register_runtime_agents"]
