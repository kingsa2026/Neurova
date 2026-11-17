# -*- coding: utf-8 -*-
"""P2-5 子代理终态回传 mailbox；H-1 起为两阶段确认（租约→入持久上下文→consume）。

会话级邮箱：蜂群子任务的**终态信封**投递父会话；agent loop 工具轮间隙取件注入。
信封只带关键信息与 `transcript` 指针（投影单源在 `SwarmManager._uplinkEnvelope`），
正文不在此重复——主 Agent 要详情就凭指针经 `recall_history` 下钻到 member 会话。
前台模式下它是增强可见性，后台模式下它是唯一回传通道。

两阶段确认（CoworkOS 对照评测 H-1，"Queuing is not acknowledgement"）：
- `lease()` 把消息交给消费方并标记 leased——未 ack 前再次 lease 仍取得到
  （至少一次投递：排空后、落盘前失败不再丢终态）；
- `acknowledge()` 只在消息确实进入持久上下文后调用，才真正删除；
- TTL 只清 **ready** 态过期件，leased 态不受 TTL 影响（在途处理不得被中途丢弃）。
- 破坏性一次性排空（旧 `drain()`）已退役：与两阶段并存即第二套投递语义。
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List

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
            # TTL 只清 ready 态：leased 是消费方正在处理（尚未确认入持久上下文）
            # 的唯一副本，中途清掉等于丢终态。
            box[:] = [e for e in box if e.get("state") == "leased" or now - e["ts"] < self.ttl_seconds]
            if len(box) >= self.max_per_session:
                logger.warning("邮箱会话 %s 已满（%d），拒绝新消息", sid, self.max_per_session)
                return False
            box.append({"id": f"mail_{uuid.uuid4().hex[:12]}", "message": message,
                        "ts": now, "state": "ready"})
            return True

    def lease(self, session_id: str) -> List[Dict[str, Any]]:
        """取件：返回 [{id, message}] 并标记 leased。未 ack 的消息再次 lease
        仍会返回（至少一次投递——落盘失败/轮次中断不丢，宁重不丢）。"""
        sid = str(session_id or "")
        if not sid:
            return []
        with self._lock:
            box = self._boxes.get(sid, [])
            now = time.time()
            out: List[Dict[str, Any]] = []
            for e in box:
                if e.get("state") == "ready" and now - e["ts"] >= self.ttl_seconds:
                    continue  # ready 态过期件不投递
                e["state"] = "leased"
                e["leased_at"] = now
                out.append({"id": e["id"], "message": e["message"]})
            return out

    def acknowledge(self, session_id: str, ids: List[str]) -> int:
        """确认消费：只删除调用方点名的 id（幂等；未 ack 的保持可再投）。"""
        sid = str(session_id or "")
        want = {str(i) for i in (ids or [])}
        if not sid or not want:
            return 0
        with self._lock:
            box = self._boxes.get(sid, [])
            before = len(box)
            box[:] = [e for e in box if e.get("id") not in want]
            removed = before - len(box)
            if not box:
                self._boxes.pop(sid, None)
            return removed

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
