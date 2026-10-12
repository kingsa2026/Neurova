"""memory_scope — 协作群聊记忆的会话作用域：打标 + 检索可见性过滤。

隔离目标（设计见 docs/superpowers/specs/2026-09-20-collaboration-memory-isolation-design.md）：
- 每条记忆按来源打 `metadata["chat_scope"]`：普通/单聊 = "direct"（缺省亦视为 direct，
  兼容全部历史记忆）；协作群聊 = "room:<room_id>"（room_id 为协作 project id）。
- 可见性规则：
  · 单聊轮 → 仅召回 direct（群聊记忆绝不泄入单聊，不污染正常单聊）。
  · 群 R 轮 → 召回 direct + room:R（读单聊基线更懂你；其它群互不可见 → 群群隔离）。

纯函数、零外部依赖，供 chat_pipeline（读）与 post_chat_pipeline（写）共用，便于单测。
"""
from __future__ import annotations

from typing import Any, Dict, List, Set

DIRECT_SCOPE = "direct"
#: 渠道群聊作用域前缀。与协作房间 `room:` 并列而**不同职**：房间里的听众是同一批登录
#: 用户，群里的听众是外部第三方身份（飞书/telegram 的 open_id），所以群轮默认不召回个人记忆。
CHANNEL_GROUP_PREFIX = "chgrp:"


def turnScopeContext(metadata, session_id: str = "") -> Dict[str, Any]:
    """一轮的作用域入参：写侧、读侧、上下文池打标三处**共用这一份**。

    三处各推一遍是本格要防的裂脑形态（工单 §6-127 批 3）：记忆打了 `chgrp:` 而池 chunk
    仍打 `direct`，群内容反而比改前更不可见，而且没有任何一格会红。渠道群判据是
    `chat_type == "group"` 且带 `source_channel` + `chat_id`（三者由 `channel_router` 备齐），
    协作轮优先——两边同时成立时按协作处理，不叠加成第三种作用域。
    """
    md = metadata or {}
    collab = md.get("turn_origin") == "collaboration"
    channel = str(md.get("source_channel") or "")
    chatId = str(md.get("chat_id") or "")
    channelGroup = ((not collab) and str(md.get("chat_type") or "") == "group"
                    and bool(channel and chatId))
    return {
        "collab": collab,
        "room_id": (session_id or "") if collab else "",
        "channel_group": channelGroup,
        "channel": channel if channelGroup else "",
        "chat_id": chatId if channelGroup else "",
    }


def _channelGroupTag(channel_group: bool, channel: str, chat_id: str) -> str:
    return f"{CHANNEL_GROUP_PREFIX}{channel}:{chat_id}" if (channel_group and channel and chat_id) else ""


def scope_tag_for_turn(*, collab: bool = False, room_id: str = "", channel_group: bool = False,
                       channel: str = "", chat_id: str = "") -> str:
    """本轮写入应打的记忆作用域标签。"""
    if collab and room_id:
        return f"room:{room_id}"
    return _channelGroupTag(channel_group, channel, chat_id) or DIRECT_SCOPE


def allowed_scopes_for_turn(*, collab: bool = False, room_id: str = "",
                             channel_group: bool = False, channel: str = "",
                             chat_id: str = "") -> Set[str]:
    """本轮可召回的作用域集。

    协作群 = direct + 本房间；渠道群 = **只有本群**；私聊 = 仅 direct。
    渠道群不召回 direct 是刻意的（与上面协作群那行不同，别当成漏）：群里的听众是外部
    第三方身份，把某个人的基线记忆带进群回复等于当着众人念他的私事。要放开须另裁。
    """
    return allowed_scopes_for_tag(scope_tag_for_turn(
        collab=collab, room_id=room_id, channel_group=channel_group,
        channel=channel, chat_id=chat_id))


def allowed_scopes_for_tag(turn_scope_tag: str) -> Set[str]:
    """从**一个标签**推出允许召回集——写侧打的标与读侧放的行因此不可能互相矛盾。

    池的读侧只拿得到 `turn_scope` 这一个字符串（`context_pool._allowedRecallItems`），
    若那里另写一套 room/chgrp 判断，就会出现"写 chgrp: 读 {direct}"= 群归档永远召不回。
    渠道群只召回本群（不含 direct）的保守口径也在此唯一表达。
    """
    tag = turn_scope_tag or DIRECT_SCOPE
    if tag.startswith(CHANNEL_GROUP_PREFIX):
        return {tag}
    if tag.startswith("room:") and len(tag) > len("room:"):
        return {DIRECT_SCOPE, tag}
    return {DIRECT_SCOPE}


def filter_by_tag(items, metadata_of, turn_scope_tag: str):
    """按本轮标签过滤（读侧只需一个值：写侧打的同一个标）。"""
    allowed = allowed_scopes_for_tag(turn_scope_tag)
    return [it for it in (items or []) if scope_from_metadata(metadata_of(it)) in allowed]


def scope_from_metadata(md: Dict[str, Any]) -> str:
    """从一段 metadata 解析作用域（记忆与上下文池 chunk 共用）。

    优先显式 `chat_scope`；缺省从 `session_id` 回溯：以 `project_` 前缀（协作房间 id）
    判定为 `room:<id>`，否则 `direct`。
    """
    md = md or {}
    tag = md.get("chat_scope")
    if isinstance(tag, str) and tag:
        return tag
    session_id = md.get("session_id")
    if isinstance(session_id, str) and session_id.startswith("project_"):
        return f"room:{session_id}"
    return DIRECT_SCOPE


def memory_scope(mem: Dict[str, Any]) -> str:
    """取一条记忆 dict 的作用域（委托 scope_from_metadata）。"""
    return scope_from_metadata(mem.get("metadata") if isinstance(mem, dict) else None)


def filter_by_scope(items, metadata_of, *, collab: bool = False, room_id: str = "",
                    channel_group: bool = False, channel: str = "", chat_id: str = ""):
    """通用作用域过滤：`metadata_of(item)` 返回该条的 metadata dict。

    供记忆（relevant_memories）与上下文池归档（历史回忆）共用同一隔离规则；
    单聊/非协作轮（collab=False）仅保留 direct→仍跨普通会话召回，但排除任何房间内容。
    """
    allowed = allowed_scopes_for_turn(collab=collab, room_id=room_id,
                                       channel_group=channel_group, channel=channel,
                                       chat_id=chat_id)
    return [it for it in (items or []) if scope_from_metadata(metadata_of(it)) in allowed]


def filter_memories_by_scope(
    memories: List[Dict[str, Any]], *, collab: bool = False, room_id: str = "",
    channel_group: bool = False, channel: str = "", chat_id: str = "",
) -> List[Dict[str, Any]]:
    """按本轮允许作用域过滤召回结果（读侧单点闸口，防跨群/跨单聊泄漏）。"""
    allowed = allowed_scopes_for_turn(collab=collab, room_id=room_id,
                                       channel_group=channel_group, channel=channel,
                                       chat_id=chat_id)
    return [m for m in (memories or []) if memory_scope(m) in allowed]
