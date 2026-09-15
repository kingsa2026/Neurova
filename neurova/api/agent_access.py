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

from typing import Any, Optional

__all__ = ["can_access_agent", "resolve_agent_owner"]


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
