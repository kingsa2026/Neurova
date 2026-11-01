# -*- coding: utf-8 -*-
"""渠道准入判定——「这条入站消息能不能交给 agent」的唯一实现。

此前判定散在 `channel_router`（只认 closed、漏 whitelist、缺省 `or "open"`）与
各适配器自己的副本里（Discord 同一文件两份），且未知策略一律当放行。本模块把
判定收成一处，失败方向统一朝拒绝：

- `open`（或未配置）放行——既有产品默认，不翻；
- `closed` 拒绝；
- `whitelist` 只放名单内的人，**名单为空即拒绝**；
- 其余任何值（含拼写错误）**拒绝**并点名原因。

缺省值 `open` 只适用于「整条策略都没配」；一旦配了策略，判据必须被真正执行。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set, Tuple

OPEN_STRATEGY = "open"
CLOSED_STRATEGY = "closed"
WHITELIST_STRATEGY = "whitelist"
CHAT_STRATEGIES = (OPEN_STRATEGY, CLOSED_STRATEGY, WHITELIST_STRATEGY)

_GROUP_CHAT_TYPES = ("group", "guild", "channel", "group_chat")


def normalizeWhitelist(value: Any) -> Set[str]:
    """配置面两种形态归一：逗号串（UI 输入）与列表/集合（JSON 配置）。"""
    if value is None:
        return set()
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if isinstance(value, Iterable):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def chatAccessDecision(
    chatType: str, cfg: Dict[str, Any], senderId: Optional[str]
) -> Tuple[bool, str]:
    """返回 (是否放行, 原因)。原因只用于日志/排障，不构成第二套状态机。"""
    isGroup = str(chatType or "").strip().lower() in _GROUP_CHAT_TYPES
    key = "group_chat_strategy" if isGroup else "private_chat_strategy"
    raw = cfg.get(key)
    strategy = OPEN_STRATEGY if raw is None or str(raw).strip() == "" else str(raw).strip().lower()

    if strategy == OPEN_STRATEGY:
        return True, "open"
    if strategy == CLOSED_STRATEGY:
        return False, "closed"
    if strategy == WHITELIST_STRATEGY:
        allowed = str(senderId or "").strip() in normalizeWhitelist(cfg.get("whitelist_users"))
        return allowed, "whitelist" if allowed else "whitelist_denied"
    return False, f"unknown_strategy:{strategy}"
