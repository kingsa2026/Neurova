# -*- coding: utf-8 -*-
"""Agent 属主判定单源（Wave H-W0，三层技能库前置安全）

背景（三层库侦查坐实）：agent 的 owner_user_id 链（创建写入→workspace 落盘→
重启回填→chat 执行门）已通，但列表面/详情面/写口/中枢登记面各自缺位或
复制了不同口径的实现（chat 拒绝无主 vs package 公共可读语义相反）。三层技能
库落地后，"改他人 agent"等价于绕过他人私库隔离——本模块统一为唯一判定源。

口径（与 chat 现行执行门一致，显示对齐执行）：
- admin：全量（可见/可管）；
- 非 admin：仅 owner_user_id == 自己的 user_id；
- **无 owner 的 agent 仅 admin**（历史无主 agent 由管理员认领/管理；
  与 chat 执行门同源，消除"列表可见、对话被拒"的误导态）。
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from fastapi import HTTPException

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = ["agentOwnerById", "can_access_agent", "requireAgentOwner", "resolve_agent_owner"]


def can_access_agent(user_id: str, role: str, owner: Optional[str]) -> bool:
    """访问/管理判定单源：admin 全量；owner 匹配；无主仅 admin。"""
    if role == "admin":
        return True
    owner_s = str(owner or "").strip()
    if not owner_s:
        return False
    return owner_s == str(user_id or "").strip()


def resolve_agent_owner(agent_id: str, *, state_agent: Any = None, registered_cfg: Any = None) -> Optional[str]:
    """解析 agent 属主：运行实例 config 优先，中枢登记（agents.json/
    workspace agent_config.json 由 _save_agent_config 同步）回退。"""
    if state_agent is not None:
        cfg = getattr(state_agent, "config", None)
        owner = getattr(cfg, "owner_user_id", None) if cfg is not None else None
        if owner:
            return str(owner)
    if isinstance(registered_cfg, dict):
        owner = registered_cfg.get("owner_user_id") or (registered_cfg.get("config") or {}).get("owner_user_id")
        if owner:
            return str(owner)
    return None


def agentOwnerById(agent_id: str) -> Optional[str]:
    """按 agent_id 取属主：运行实例优先，中枢登记（agents.json / workspace 同步）回退。

    **取数也收在这一处**：此前渠道、技能池、agent 各面各自拼一遍"先查 state 再查
    登记"，同一契约多份取数实现 —— 其中任何一份漏了回退，就会把有主 agent 判成
    无主，而无主的判据是"仅 admin"，属主本人被自己挡在门外。
    """
    state_agent = None
    try:
        from neurova.api.endpoints import get_agent_instance

        state_agent = get_agent_instance(agent_id)
    except Exception as exc:  # noqa: BLE001 - 状态面不可用即按"无实例"走登记回退
        logger.debug("agent 实例查询失败 %s: %s", agent_id, exc)
    registered_cfg = None
    if state_agent is None:
        try:
            from neurova.api.endpoints.agent import get_agent_config_manager

            registered_cfg = get_agent_config_manager().get_agent(agent_id)
        except Exception as exc:  # noqa: BLE001 - 登记面不可用即按"无登记"走
            logger.debug("agent 登记查询失败 %s: %s", agent_id, exc)
    return resolve_agent_owner(agent_id, state_agent=state_agent, registered_cfg=registered_cfg)


def requireAgentOwner(agent_id: str, current_user: Any, *, action: str = "访问") -> None:
    """HTTP 门：admin 全量；非 admin 仅属主；**无主（含 `default`）仅 admin**。

    与 `can_access_agent` 同一判据，只是把"拒绝"落成 403。门的默认方向是
    **拒绝**：身份缺席（端点被直调而未传身份）按匿名处理，不让"忘了传身份"
    变成绕过口的旁路。
    """
    identity = current_user if isinstance(current_user, Mapping) else {}
    uid = str(identity.get("user_id") or "")
    role = str(identity.get("role") or "user")
    if can_access_agent(uid, role, agentOwnerById(agent_id)):
        return
    raise HTTPException(
        status_code=403,
        detail=f"无权{action}智能体『{agent_id}』（仅属主或管理员可操作）",
    )
