# -*- coding: utf-8 -*-
"""ChannelRouter —— 渠道入站消息统一路由到 agent 并回发（对齐 QwenPaw process 注入）。

背景（"下消息通路"缺失环）：ChannelManager 此前没有任何常驻消息处理器，飞书/钉钉/
微信等渠道把消息收进来后 `_dispatch_message` 找不到 handler → 无人调用 agent →
无回复。QwenPaw 的做法是给所有渠道注入统一的 `process`（agent 调用）+ 各渠道用
`resolve_session_id` 得到稳定会话键。NV 复用既有 `ChannelManager.add_message_handler`
与 `resolve_session_scope_id`，用**一个**常驻 handler 打通：

  入站 ChannelMessage →（agent_id 来自装配期 metadata）→ get_agent_instance(agent_id)
  → agent.chat(user_input, session_id=resolve_session_scope_id(msg),
     metadata={user_id=发送者, source_channel=渠道, role=user})
  → 返回回复文本 → manager._dispatch_message 自动 send_message 回发到该渠道该会话。

会话键固定（同一 agent+渠道+群/私聊 → 同一 session），保证多轮上下文连续；群共享/
按发送者隔离由 resolve_session_scope_id 单点裁决（share_session_in_group）。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from neurova.channels.base import ChannelMessage

logger = logging.getLogger(__name__)

# 默认 agent 查找回退（延迟 import 避免 channels↔api 循环依赖）
def _default_agent_lookup(agent_id: str):
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def make_handler(manager, agent_lookup: Optional[Callable[[str], Any]] = None) -> Callable:
    """构造渠道→agent 处理器。agent_lookup(agent_id)->Agent|None 可注入（测试用）。"""
    lookup = agent_lookup or _default_agent_lookup

    async def _handler(message: ChannelMessage) -> Optional[str]:
        content = (message.content or "").strip()
        if not content:
            return None
        agent_id = str(message.metadata.get("agent_id") or "default")
        agent = lookup(agent_id)
        if agent is None:
            logger.warning("ChannelRouter: agent『%s』不存在，%s 消息未处理", agent_id, message.channel_type)
            return None
        session_id = manager.resolve_session_scope_id(message)
        meta: Dict[str, Any] = {
            "user_id": message.sender_id or f"channel:{message.channel_type}",
            "role": "user",
            "source_channel": message.channel_type,
            "channel": message.channel_type,
        }
        try:
            resp = await agent.chat(user_input=content, session_id=session_id, metadata=meta)
        except Exception:
            logger.exception("ChannelRouter: agent.chat 失败（channel=%s agent=%s）", message.channel_type, agent_id)
            return None
        if isinstance(resp, dict):
            text = resp.get("text") or ""
        else:
            text = str(resp or "")
        text = text.strip()
        return text or None

    return _handler


def install_channel_router(manager, agent_lookup: Optional[Callable[[str], Any]] = None) -> None:
    """在 ChannelManager 上注册统一路由处理器（幂等）。priority=50 低于审批类临时
    处理器（priority=10），保证审批回复先被专用 handler 拦截。"""
    if getattr(manager, "_channel_router_installed", False):
        return
    manager.add_message_handler(make_handler(manager, agent_lookup), priority=50)
    manager._channel_router_installed = True
    logger.info("ChannelRouter 已注册（渠道入站统一路由到 agent）")
