# -*- coding: utf-8 -*-
"""B1 子代理完成结果投递账本（投递状态机 pending→claimed→acknowledged|disposed）。

与 ``mailbox.AgentMailbox`` 的分工：邮箱是会话级**信箱**，管消息在箱内的
两阶段确认（lease→ack）与租约回收；本模块是**投递单账本**，记录"哪个子代理
run 的结果要投给哪个父 run"——一张投递单从开出（pending）、被父侧领取
（claimed）、到父侧确认入账（acknowledged）或处置作废（disposed）的完整去向，
含父闲补投（catchUp）与逐单审计轨迹（audit trail）。不替代邮箱，也不感知
邮箱实例；纯模块，不 import swarm。

状态机（本模块唯一出处）：
- ``pending``       已落投递单，待父侧领取；
- ``claimed``       父侧已领取、尚未最终确认；
- ``acknowledged``  父侧确认销账（投递闭环）；
- ``disposed``      处置作废（reason 必填留痕，如补投失败、父 run 已终结）。

幂等与补投：
- 同 ``message_id`` 的重复 record 返回既有投递单（去重，不重复入账）；
- ``catchUp`` 对目标父 run 的未销账单各补投一次：deliver_fn 返回 True →
  标记 redelivered；返回 False 或抛异常 → dispose("catchup_failed")；
  已 redelivered 的单不再投（每单只补投一次）。
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

#: 投递单状态机词值
DELIVERY_PENDING = "pending"
DELIVERY_CLAIMED = "claimed"
DELIVERY_ACKNOWLEDGED = "acknowledged"
DELIVERY_DISPOSED = "disposed"

#: 未销账的开放状态（catchUp 的补投对象）
_DELIVERY_OPEN_STATUSES = frozenset({DELIVERY_PENDING, DELIVERY_CLAIMED})


class DeliveryLedger:
    """子代理完成结果投递单账本（RLock 线程安全；每单带 audit trail）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._tickets: Dict[str, Dict[str, Any]] = {}  # ticket_id -> 投递单
        self._byMessageId: Dict[str, str] = {}         # message_id -> ticket_id（幂等索引）
        self._seq = 0                                  # 开单序号（快照稳定排序用）

    # ── 内部工具（持锁调用）──────────────────────────────────────
    @staticmethod
    def _view(ticket: Dict[str, Any]) -> Dict[str, Any]:
        """对外快照：拷贝字典与 audit 列表，防外部改写账本内部态。"""
        view = dict(ticket)
        view["audit"] = list(ticket["audit"])
        return view

    @staticmethod
    def _appendAudit(ticket: Dict[str, Any], action: str, **extra: Any) -> None:
        entry: Dict[str, Any] = {"ts": time.time(), "action": action}
        entry.update(extra)
        ticket["audit"].append(entry)
        ticket["updated_at"] = entry["ts"]

    # ── 对外契约 ────────────────────────────────────────────────
    def record(self, subagent_id: str, parent_run_id: str, tag: str, envelope: Any,
               message_id: str, *, generation: int = 0) -> Dict[str, Any]:
        """落投递单（pending）。同 message_id 幂等去重：返回既有投递单。"""
        sid = str(subagent_id or "").strip()
        pid = str(parent_run_id or "").strip()
        if not sid or not pid:
            raise ValueError("record 需要 subagent_id 与 parent_run_id")
        mid = str(message_id or "").strip()
        with self._lock:
            if mid:
                existingId = self._byMessageId.get(mid)
                if existingId is not None:
                    return self._view(self._tickets[existingId])
            self._seq += 1
            now = time.time()
            ticketId = f"dlv_{self._seq:06d}_{uuid.uuid4().hex[:8]}"
            ticket: Dict[str, Any] = {
                "ticket_id": ticketId,
                "subagent_id": sid,
                "parent_run_id": pid,
                "tag": str(tag or ""),
                "envelope": envelope,
                "message_id": mid,
                "generation": int(generation),
                "status": DELIVERY_PENDING,
                "redelivered": False,
                "disposed_reason": "",
                "created_at": now,
                "updated_at": now,
                "audit": [],
            }
            self._appendAudit(ticket, "record")
            self._tickets[ticketId] = ticket
            if mid:
                self._byMessageId[mid] = ticketId
            return self._view(ticket)

    def claim(self, ticket_id: str) -> bool:
        """pending→claimed。幂等：已 claimed 重复领返回 True；
        已销账（acknowledged/disposed）或未知单返回 False。"""
        tid = str(ticket_id or "").strip()
        with self._lock:
            ticket = self._tickets.get(tid)
            if ticket is None:
                return False
            if ticket["status"] == DELIVERY_CLAIMED:
                return True
            if ticket["status"] != DELIVERY_PENDING:
                return False
            ticket["status"] = DELIVERY_CLAIMED
            self._appendAudit(ticket, "claim")
            return True

    def acknowledge(self, ticket_id: str) -> bool:
        """claimed→acknowledged 销账；pending 直达确认允许（先确认后补记）。
        重复确认幂等返回 True；disposed 或未知单返回 False。"""
        tid = str(ticket_id or "").strip()
        with self._lock:
            ticket = self._tickets.get(tid)
            if ticket is None:
                return False
            if ticket["status"] == DELIVERY_ACKNOWLEDGED:
                return True
            if ticket["status"] not in _DELIVERY_OPEN_STATUSES:
                return False
            ticket["status"] = DELIVERY_ACKNOWLEDGED
            self._appendAudit(ticket, "acknowledge")
            return True

    def acknowledgeByMessageId(self, message_id: str) -> bool:
        """按投递时 messageId 镜像确认（B1 闭环）：邮箱消费侧（loops/base.py
        排空 ack）经此把投递单推到 acknowledged——销账态因此生产可达。
        未知/空 id 诚实返回 False；重复确认幂等。"""
        mid = str(message_id or "").strip()
        if not mid:
            return False
        with self._lock:
            ticketId = self._byMessageId.get(mid)
        if ticketId is None:
            return False
        return self.acknowledge(ticketId)

    def dispose(self, ticket_id: str, reason: str) -> Dict[str, Any]:
        """→disposed 并留痕。reason 必填（空则 ValueError）；未知单 KeyError；
        已 disposed 幂等返回原单（保留首次原因）。

        状态机上 disposed 只从开放态（pending/claimed）可达；acknowledged
        是已完成销账的终态，再处置属非法迁移，显式 ValueError 拒绝。
        """
        tid = str(ticket_id or "").strip()
        reasonText = str(reason or "").strip()
        if not reasonText:
            raise ValueError("dispose 需要非空 reason（处置留痕必填）")
        with self._lock:
            ticket = self._tickets.get(tid)
            if ticket is None:
                raise KeyError(f"投递单 {tid or tid!r} 不存在")
            if ticket["status"] == DELIVERY_DISPOSED:
                return self._view(ticket)
            if ticket["status"] == DELIVERY_ACKNOWLEDGED:
                raise ValueError(f"投递单 {tid} 已确认销账，不可再处置")
            ticket["status"] = DELIVERY_DISPOSED
            ticket["disposed_reason"] = reasonText
            self._appendAudit(ticket, "dispose", reason=reasonText)
            return self._view(ticket)

    def catchUp(self, parent_run_id: str,
                deliver_fn: Callable[[Dict[str, Any]], bool]) -> List[Dict[str, Any]]:
        """父闲补投：对目标父 run 的未销账单（pending/claimed）各补投一次。

        deliver_fn(ticket) 返回 True → 标记 redelivered（不改状态）；
        返回 False 或抛异常 → dispose("catchup_failed")。已 redelivered 的单
        不再投（每单只补投一次）。返回本次实际补投过的投递单快照列表。
        补投全程持锁：并发 catchUp 对同一单也只投一次；deliver_fn 内可重入
        本账本（RLock 同线程可重入）。
        """
        pid = str(parent_run_id or "").strip()
        if not pid:
            raise ValueError("catchUp 需要 parent_run_id")
        if deliver_fn is None:
            raise ValueError("catchUp 需要 deliver_fn")
        attempted: List[Dict[str, Any]] = []
        with self._lock:
            candidates = [
                t for t in self._tickets.values()
                if t["parent_run_id"] == pid
                and t["status"] in _DELIVERY_OPEN_STATUSES
                and not t["redelivered"]
            ]
            candidates.sort(key=lambda t: (t["created_at"], t["ticket_id"]))
            for ticket in candidates:
                attempted.append(self._view(ticket))
                try:
                    delivered = bool(deliver_fn(self._view(ticket)))
                except Exception as e:  # noqa: BLE001 - 补投失败按契约处置留痕，不静默吞
                    self.dispose(ticket["ticket_id"], "catchup_failed")
                    self._appendAudit(self._tickets[ticket["ticket_id"]],
                                      "catchup_failed", error=str(e))
                    continue
                if delivered:
                    ticket["redelivered"] = True
                    self._appendAudit(ticket, "catchup_delivered")
                else:
                    self.dispose(ticket["ticket_id"], "catchup_failed")
        return attempted

    def pendingForParent(self, parent_run_id: str) -> List[Dict[str, Any]]:
        """目标父 run 名下未销账（pending/claimed）的投递单快照（开单序）。"""
        pid = str(parent_run_id or "").strip()
        with self._lock:
            matches = [
                t for t in self._tickets.values()
                if t["parent_run_id"] == pid and t["status"] in _DELIVERY_OPEN_STATUSES
            ]
            matches.sort(key=lambda t: (t["created_at"], t["ticket_id"]))
            return [self._view(t) for t in matches]

    def get(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """按 ticket_id 取投递单快照；不存在返回 None。"""
        tid = str(ticket_id or "").strip()
        with self._lock:
            ticket = self._tickets.get(tid)
            return self._view(ticket) if ticket is not None else None

    def snapshot(self) -> List[Dict[str, Any]]:
        """全量投递单快照（开单序）。"""
        with self._lock:
            tickets = sorted(self._tickets.values(),
                             key=lambda t: (t["created_at"], t["ticket_id"]))
            return [self._view(t) for t in tickets]


_LEDGER: Optional[DeliveryLedger] = None
_LEDGER_LOCK = threading.Lock()


def getDeliveryLedger() -> DeliveryLedger:
    """进程级投递账本单例（DCL+RLock）。

    单一事实源在本模块；``swarm._deliveryLedger`` 委托到此，邮箱消费侧
    （loops/base.py）与编排写点（swarm.pushParentMail）据此共享同一本账。
    """
    global _LEDGER
    if _LEDGER is not None:
        return _LEDGER
    with _LEDGER_LOCK:
        if _LEDGER is None:
            _LEDGER = DeliveryLedger()
    return _LEDGER
