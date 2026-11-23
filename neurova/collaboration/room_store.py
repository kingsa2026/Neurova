# -*- coding: utf-8 -*-
"""RoomStore — 协作群聊房间的持久消息存储。

落点（2026-11-23 拍板收口）：`data/collaboration/rooms/<room_id>/messages.jsonl`。

房间消息是**多发送者群聊流水**，不再借 agent 会话文件层——旧做法把 room_id
（= project_id，形如 `project_<hex12>`）同时当 agent_id 与 session_id 复用
SessionManager，导致每个发过消息的房间都在数据根顶层长出一个 `data/project_*/`
目录（data/ 顶层 316 个条目的主要来源之一），并被启动迁移当 agent 根反复扫描。

- 追加型流水：一行一条 JSON（sender_type/sender_id/role/content/timestamp/meta）；
- 进程内加锁追加（房间并发发言不丢行）；读侧整文件解析取尾部 limit 条；
- room_id 落盘前收进安全段（防 `../` 逃逸出命名空间）；
- 多发送者归属经 sender_type/sender_id 往返；role 映射 user→user、
  agent→assistant、system→system；
- 读方：房间历史 REST（collaboration_room_api）、审批链回看（approval_chain）、
  项目档案（projects_api）、分诊训练收割（triage_dataset 显式扫本命名空间）。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.data_root import get_data_root
from neurova.core.lazy_singleton import lazySingleton

# sender_type → 房间消息的 role 取值
_ROLE_BY_SENDER = {"user": "user", "agent": "assistant", "system": "system"}
_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9_-]+")
_APPEND_LOCK = threading.RLock()


def get_room_messages_path(room_id: str) -> Path:
    """房间消息流水落点：`data/collaboration/rooms/<room_id>/messages.jsonl`。"""
    segment = _SAFE_SEGMENT_RE.sub("_", str(room_id or "").strip())
    if not segment:
        raise ValueError(f"非法 room_id: {room_id!r}")
    return get_data_root() / "collaboration" / "rooms" / segment / "messages.jsonl"


class RoomStore:
    """房间消息持久层（JSONL 追加流水，落协作命名空间）。"""

    def append(
        self,
        room_id: str,
        sender_type: str,
        sender_id: str,
        content: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """追加一条房间消息。返回存下的最小记录（含归属）。"""
        record = {
            "room_id": room_id,
            "sender_type": sender_type,
            "sender_id": sender_id,
            "role": _ROLE_BY_SENDER.get(sender_type, "assistant"),
            "content": content,
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "meta": dict(meta or {}),
            # 房间按设计多人可见，所以"共享"是**显式决定**而非默认产物：
            # 参与者由房间成员关系裁决，不由会话属主裁决。写信人留在 sender_id。
        }
        path = get_room_messages_path(room_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _APPEND_LOCK:
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {
            "room_id": room_id,
            "sender_type": sender_type,
            "sender_id": sender_id,
            "content": content,
        }

    def history(self, room_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        """按时间顺序返回房间历史（截断至最近 limit 条），还原发送者归属。"""
        path = get_room_messages_path(room_id)
        if not path.exists():
            return []
        with _APPEND_LOCK:
            lines = path.read_text(encoding="utf-8").splitlines()
        rows: List[Dict[str, Any]] = []
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            rows.append({
                "sender_type": record.get("sender_type", ""),
                "sender_id": record.get("sender_id", ""),
                "role": record.get("role", ""),
                "content": record.get("content", ""),
                "ts": record.get("timestamp"),
                "meta": record.get("meta") or {},
            })
        return rows[-limit:] if limit else rows


_store: Optional[RoomStore] = None


@lazySingleton("_store")
def get_room_store() -> RoomStore:
    return RoomStore()


def reset_room_store() -> None:
    global _store
    _store = None
