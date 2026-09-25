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


def scope_tag_for_turn(*, collab: bool, room_id: str = "") -> str:
    """本轮写入应打的记忆作用域标签。"""
    return f"room:{room_id}" if (collab and room_id) else DIRECT_SCOPE


def allowed_scopes_for_turn(*, collab: bool, room_id: str = "") -> Set[str]:
    """本轮可召回的作用域集。群轮 = direct + 本群；单聊轮 = 仅 direct。"""
    if collab and room_id:
        return {DIRECT_SCOPE, f"room:{room_id}"}
    return {DIRECT_SCOPE}


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


def filter_by_scope(items, metadata_of, *, collab: bool, room_id: str = ""):
    """通用作用域过滤：`metadata_of(item)` 返回该条的 metadata dict。

    供记忆（relevant_memories）与上下文池归档（历史回忆）共用同一隔离规则；
    单聊/非协作轮（collab=False）仅保留 direct→仍跨普通会话召回，但排除任何房间内容。
    """
    allowed = allowed_scopes_for_turn(collab=collab, room_id=room_id)
    return [it for it in (items or []) if scope_from_metadata(metadata_of(it)) in allowed]


def filter_memories_by_scope(
    memories: List[Dict[str, Any]], *, collab: bool, room_id: str = ""
) -> List[Dict[str, Any]]:
    """按本轮允许作用域过滤召回结果（读侧单点闸口，防跨群/跨单聊泄漏）。"""
    allowed = allowed_scopes_for_turn(collab=collab, room_id=room_id)
    return [m for m in (memories or []) if memory_scope(m) in allowed]
