# -*- coding: utf-8 -*-
"""P2-5 子代理终态回传 mailbox。

会话级邮箱：蜂群子任务的**终态信封**投递父会话；agent loop 工具轮间隙排空注入。
信封只带关键信息与 `transcript` 指针（投影单源在 `SwarmManager._uplinkEnvelope`），
正文不在此重复——主 Agent 要详情就凭指针经 `recall_history` 下钻到 member 会话。
前台模式下它是增强可见性，后台模式下它是唯一回传通道。
"""
from __future__ import annotations

import threading
import time
from typing import Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_TTL_SECONDS = 600
_DEFAULT_MAX_PER_SESSION = 20


class AgentMailbox:
    """会话级子代理回传邮箱（单例经 get_agent_mailbox() 获取）。"""

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS, max_per_session: int = _DEFAULT_MAX_PER_SESSION):
        self.ttl_seconds = ttl_seconds
        self.max_per_session = max_per_session
        self._lock = threading.RLock()
        self._boxes: Dict[str, List[Dict]] = {}

    def push(self, session_id: str, message: str) -> bool:
        message = str(message or "").strip()
        sid = str(session_id or "")
        if not sid or not message:
            return False
        with self._lock:
            box = self._boxes.setdefault(sid, [])
            now = time.time()
            box[:] = [e for e in box if now - e["ts"] < self.ttl_seconds]
            if len(box) >= self.max_per_session:
                return False
            box.append({"message": message, "ts": now})
            return True

    def drain(self, session_id: str) -> List[str]:
        sid = str(session_id or "")
        if not sid:
            return []
        with self._lock:
            box = self._boxes.pop(sid, [])
            now = time.time()
            return [e["message"] for e in box if now - e["ts"] < self.ttl_seconds]

    def pending(self, session_id: str) -> int:
        with self._lock:
            return len(self._boxes.get(str(session_id or ""), []))


_MAILBOX: AgentMailbox = None
_MAILBOX_LOCK = threading.Lock()


def get_agent_mailbox() -> AgentMailbox:
    global _MAILBOX
    with _MAILBOX_LOCK:
        if _MAILBOX is None:
            _MAILBOX = AgentMailbox()
        return _MAILBOX


def reset_agent_mailbox() -> None:
    global _MAILBOX
    with _MAILBOX_LOCK:
        _MAILBOX = None
