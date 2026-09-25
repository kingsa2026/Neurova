"""RoomStore — 协作群聊房间的持久消息存储（薄封装 SessionRepository/SessionManager）。

设计（见 docs/superpowers/specs/2026-09-19-collaboration-room-chat-design.md §2/§3）：
- 以 `room_id`（= 协作 project_id）同时作 `agent_id` 与 `session_id` 键，复用既有文件层
  持久化，零新表、零 schema 改动，且 project_ 前缀不与真实 agent 会话命名冲突。
- 多发送者归属经 `metadata.{sender_type, sender_id}` 往返；role 映射 user→user、
  agent→assistant、system→system。
- 与 SessionSyncManager（纯内存事件总线，ADR-0008 故意不实现 SessionRepository）解耦：
  本模块只负责"重开可回看"的持久层。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.session_repository import SessionRepository, get_session_repository

# sender_type → SessionRepository 的 role 取值
_ROLE_BY_SENDER = {"user": "user", "agent": "assistant", "system": "system"}
_SENDER_ATTRS = ("sender_type", "sender_id")


class RoomStore:
    """房间消息持久层。repo 可注入（测试用假仓库）。"""

    def __init__(self, repo: Optional[SessionRepository] = None) -> None:
        self._repo = repo

    @property
    def repo(self) -> SessionRepository:
        return self._repo or get_session_repository()

    def append(
        self,
        room_id: str,
        sender_type: str,
        sender_id: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """追加一条房间消息。返回存下的最小记录（含归属）。"""
        metadata: Dict[str, Any] = {"sender_type": sender_type, "sender_id": sender_id}
        if meta:
            metadata.update(meta)
        self.repo.save_message(
            agent_id=room_id,
            session_id=room_id,
            role=_ROLE_BY_SENDER.get(sender_type, "assistant"),
            content=content,
            metadata=metadata,
        )
        return {"room_id": room_id, "sender_type": sender_type, "sender_id": sender_id, "content": content}

    def history(self, room_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        """按时间顺序返回房间历史（截断至最近 limit 条），还原发送者归属。"""
        rows = self.repo.get_history(agent_id=room_id, session_id=room_id, max_messages=0) or []
        out: List[Dict[str, Any]] = []
        for r in rows:
            md = r.get("metadata") or {}
            out.append({
                "sender_type": md.get("sender_type", ""),
                "sender_id": md.get("sender_id", ""),
                "role": r.get("role", ""),
                "content": r.get("content", ""),
                "ts": r.get("timestamp"),
                "meta": {k: v for k, v in md.items() if k not in _SENDER_ATTRS},
            })
        return out[-limit:] if limit else out


_store: Optional[RoomStore] = None


def get_room_store() -> RoomStore:
    global _store
    if _store is None:
        _store = RoomStore()
    return _store


def reset_room_store() -> None:
    global _store
    _store = None
