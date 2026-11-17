# -*- coding: utf-8 -*-
"""P2-5 子代理终态回传 mailbox；H-1 起为两阶段确认（租约→入持久上下文→consume）。

会话级邮箱：蜂群子任务的**终态信封**投递父会话；agent loop 工具轮间隙取件注入。
信封只带关键信息与 `transcript` 指针（投影单源在 `SwarmManager._uplinkEnvelope`），
正文不在此重复——主 Agent 要详情就凭指针经 `recall_history` 下钻到 member 会话。
前台模式下它是增强可见性，后台模式下它是唯一回传通道。

两阶段确认（CoworkOS 对照评测 H-1，"Queuing is not acknowledgement"）：
- `lease()` 把消息交给消费方并标记 leased——未 ack 前再次 lease 仍取得到
  （至少一次投递：排空后、落盘前失败不再丢终态）；
- `acknowledge()` 只在消息确实进入持久上下文后调用，才真正删除；对已 ack 的
  id 重复调用幂等（返回 0，计数不重复扣减）；
- 破坏性一次性排空（旧 `drain()`）已退役：与两阶段并存即第二套投递语义。

S2 可靠性语义补全（CoworkOS 对照 C1/C3）：
- 幂等：消息带 `messageId`（投递点生成，缺省由本层补 uuid）；同 id 重复投递
  直接去重（只生效一次）。端到端"不重复生效"由消费侧配合：重投件（确认前
  中断/死主回收）携同一 messageId，消费方判重后只补确认（见 loops/base.py）；
- 优先级：消息带 `priority`（normal/high/urgent，缺省 normal）；`lease()` 按
  优先级降序、同级按投递时间升序返回（审批/升级类投递默认 high）；
- 死主回收：TTL 清扫从"只清 ready 态"扩展为 **leased 超 TTL 未 ack 也回收回
  ready**（原样留在 leased 态会让死消费者的租约永占箱容）。回收保留原
  messageId 并重置计时，回收计数进 `stats()` 运维快照——宁重不丢，不升级成
  重复生效。
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

#: 优先级档位（S2）：数值越大越先出箱；缺省 normal。
PRIORITY_RANK: Dict[str, int] = {"urgent": 3, "high": 2, "normal": 1}


def normalizePriority(value: Any) -> str:
    """优先级归一：非法/缺省值一律落 normal（投递面不做二次猜测）。"""
    priority = str(value or "").strip().lower()
    return priority if priority in PRIORITY_RANK else "normal"


class AgentMailbox:
    """会话级子代理回传邮箱（单例经 get_agent_mailbox() 获取）。

    两阶段确认 + messageId 幂等 + 优先级队列 + 死主回收（模块 docstring 详述）。
    累计计数（ack/回收/去重）为实例生命周期内的运维口径，经 `stats()` 暴露。
    """

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS, max_per_session: int = _DEFAULT_MAX_PER_SESSION):
        self.ttl_seconds = ttl_seconds
        self.max_per_session = max_per_session
        self._lock = threading.RLock()
        self._boxes: Dict[str, List[Dict]] = {}
        self._ackedTotal = 0
        self._reclaimedTotal = 0
        self._dedupedTotal = 0

    def push(self, session_id: str, message: str, message_id: str = "", priority: str = "normal") -> bool:
        """投递（唯一写点在 `SwarmManager.pushParentMail`）。

        `message_id` 是幂等键：同 id 的活件（ready/leased）已在箱即去重，
        返回 True（幂等接受，不重复入库）；缺省由本层补 uuid。
        """
        message = str(message or "").strip()
        sid = str(session_id or "")
        if not sid or not message:
            return False
        prio = normalizePriority(priority)
        mid = str(message_id or "").strip() or uuid.uuid4().hex
        with self._lock:
            box = self._boxes.setdefault(sid, [])
            now = time.time()
            self._sweepLocked(box, now)
            if any(e.get("messageId") == mid for e in box):
                self._dedupedTotal += 1
                return True
            if len(box) >= self.max_per_session:
                logger.warning("邮箱会话 %s 已满（%d），拒绝新消息", sid, self.max_per_session)
                return False
            box.append({
                "id": f"mail_{uuid.uuid4().hex[:12]}",
                "messageId": mid,
                "message": message,
                "ts": now,
                "state": "ready",
                "leased_at": None,
                "priority": prio,
                "reclaims": 0,
            })
            return True

    def lease(self, session_id: str) -> List[Dict[str, Any]]:
        """取件：按优先级降序、同级按时间升序返回 [{id, messageId, message, priority}]
        并标记 leased。未 ack 的消息再次 lease 仍会返回（至少一次投递——落盘
        失败/轮次中断不丢，宁重不丢）；重投件 messageId 不变，消费方据此判重。
        """
        sid = str(session_id or "")
        if not sid:
            return []
        with self._lock:
            box = self._boxes.get(sid, [])
            now = time.time()
            self._sweepLocked(box, now)
            ordered = sorted(box, key=lambda e: (-PRIORITY_RANK[e["priority"]], e["ts"]))
            out: List[Dict[str, Any]] = []
            for e in ordered:
                if e["state"] == "ready":
                    e["state"] = "leased"
                    e["leased_at"] = now
                out.append({
                    "id": e["id"],
                    "messageId": e["messageId"],
                    "message": e["message"],
                    "priority": e["priority"],
                })
            return out

    def acknowledge(self, session_id: str, ids: List[str]) -> int:
        """确认消费：只删除调用方点名的 id（幂等；未 ack 的保持可再投；
        对已 ack 的 id 重复调用返回 0，ack 计数不重复扣减）。"""
        sid = str(session_id or "")
        want = {str(i) for i in (ids or [])}
        if not sid or not want:
            return 0
        with self._lock:
            box = self._boxes.get(sid, [])
            before = len(box)
            box[:] = [e for e in box if e.get("id") not in want]
            removed = before - len(box)
            if removed:
                self._ackedTotal += removed
            if not box:
                self._boxes.pop(sid, None)
            return removed

    def pending(self, session_id: str) -> int:
        with self._lock:
            return len(self._boxes.get(str(session_id or ""), []))

    def stats(self, session_id: str = "") -> Dict[str, Any]:
        """运维快照（S2）：在途租约数/ack 计数/回收计数/去重计数/优先级分布。

        带 `session_id` 时 live 态只统计该会话；累计计数为邮箱实例全局值。
        快照前先做死主回收清扫——在途租约读数不得把死主件算成在途。
        """
        sid = str(session_id or "")
        with self._lock:
            now = time.time()
            targets = [sid] if sid else list(self._boxes.keys())
            readyTotal = 0
            leasedTotal = 0
            distribution = {"normal": 0, "high": 0, "urgent": 0}
            for key in targets:
                box = self._boxes.get(key)
                if box is None:
                    continue
                self._sweepLocked(box, now)
                for e in box:
                    distribution[e["priority"]] = distribution.get(e["priority"], 0) + 1
                    if e.get("state") == "leased":
                        leasedTotal += 1
                    else:
                        readyTotal += 1
            return {
                "sessions": len(self._boxes) if not sid else (1 if sid in self._boxes else 0),
                "pendingTotal": readyTotal + leasedTotal,
                "readyTotal": readyTotal,
                "leasedTotal": leasedTotal,
                "ackedTotal": self._ackedTotal,
                "reclaimedTotal": self._reclaimedTotal,
                "dedupedTotal": self._dedupedTotal,
                "priorityDistribution": distribution,
            }

    def _sweepLocked(self, box: List[Dict], now: float) -> None:
        """就地清扫（持锁调用）：ready 过期件删除；leased 超 TTL 未 ack 的
        死主件回收回 ready（回收计数进 stats）。回收件保留原 messageId 并
        重置计时——对消费方仍是同一封，回收后可再 lease。"""
        kept: List[Dict] = []
        for e in box:
            if e.get("state") == "leased":
                leasedAt = float(e.get("leased_at") or 0.0)
                if now - leasedAt >= self.ttl_seconds:
                    e["state"] = "ready"
                    e["leased_at"] = None
                    e["ts"] = now
                    e["reclaims"] = int(e.get("reclaims", 0)) + 1
                    self._reclaimedTotal += 1
                kept.append(e)
            elif now - e["ts"] < self.ttl_seconds:
                kept.append(e)
        box[:] = kept


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
