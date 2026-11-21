# -*- coding: utf-8 -*-
"""B4 排队 run 的管理面：优先级调整 / 取消 / 任务书修订 / 队列位置。

只管「排队中」的条目；已在跑的 run 不由本面持有——任务书修订经调用方注入的
``steer_fn(sid, text)`` 送达运行通道，本面不感知执行态（避免造第二套运行状态）。
优先级档位与归一**复用** ``mailbox`` 的 ``PRIORITY_RANK`` / ``normalizePriority``
（单一事实源，不造第二套档位表）。

队序规则：优先级降序（urgent > high > normal），同级按入队先后（先来先服务）。
所有位置读数均从 1 起；不在队列返回 0。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional

from neurova.agent.mailbox import PRIORITY_RANK, normalizePriority


class RunQueue:
    """排队 run 的管理面（RLock 线程安全）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: Dict[str, Dict[str, Any]] = {}  # subagent_id -> 队列条目
        self._seq = 0  # 入队序（同级先来先服务的依据）

    # ── 内部工具（持锁调用）──────────────────────────────────────
    def _orderedLocked(self) -> List[Dict[str, Any]]:
        """队序投影：优先级降序、同级按入队序升序。"""
        return sorted(
            self._entries.values(),
            key=lambda e: (-PRIORITY_RANK[e["priority"]], e["seq"]),
        )

    def _positionLocked(self, subagentId: str) -> int:
        for idx, entry in enumerate(self._orderedLocked()):
            if entry["subagent_id"] == subagentId:
                return idx + 1
        return 0

    # ── 对外契约 ────────────────────────────────────────────────
    def enqueue(self, subagent_id: str, task: str, *, priority: str = "normal") -> int:
        """入队，返回队列位次（从 1 起）。重复入队显式拒绝（不静默覆盖）。"""
        sid = str(subagent_id or "").strip()
        text = str(task or "").strip()
        if not sid:
            raise ValueError("enqueue 需要 subagent_id")
        if not text:
            raise ValueError("enqueue 需要非空 task")
        with self._lock:
            if sid in self._entries:
                raise ValueError(f"subagent {sid} 已在队列中，拒绝重复入队")
            self._seq += 1
            self._entries[sid] = {
                "subagent_id": sid,
                "task": text,
                "priority": normalizePriority(priority),
                "queued_at": time.time(),
                "seq": self._seq,
            }
            return self._positionLocked(sid)

    def setPriority(self, subagent_id: str, priority: str) -> int:
        """调整优先级（档位经 normalizePriority 归一），返回调整后的新位次。
        队列中不存在该 run 时显式 KeyError。"""
        sid = str(subagent_id or "").strip()
        with self._lock:
            entry = self._entries.get(sid)
            if entry is None:
                raise KeyError(f"subagent {sid} 不在队列中，无法调整优先级")
            entry["priority"] = normalizePriority(priority)
            return self._positionLocked(sid)

    def cancelQueued(self, subagent_id: str) -> Dict[str, Any]:
        """移出队列并留痕（返回被取消条目的快照，含取消时刻与取消时位次）。
        队列中不存在时显式 KeyError，不静默。"""
        sid = str(subagent_id or "").strip()
        with self._lock:
            positionAtCancel = self._positionLocked(sid)
            entry = self._entries.pop(sid, None)
            if entry is None:
                raise KeyError(f"subagent {sid} 不在队列中，无法取消")
            return {
                "subagent_id": entry["subagent_id"],
                "task": entry["task"],
                "priority": entry["priority"],
                "queued_at": entry["queued_at"],
                "position_at_cancel": positionAtCancel,
                "cancelled_at": time.time(),
            }

    def dequeue(self, subagent_id: str) -> bool:
        """出队（run 已开跑/已终态时由编排侧调用）。幂等软语义：
        在队 → 移除并返回 True；不在队 → 返回 False（不抛错，
        供状态迁移点无脑调用，与 cancelQueued 的显式 KeyError 语义区分）。"""
        sid = str(subagent_id or "").strip()
        with self._lock:
            return self._entries.pop(sid, None) is not None

    def editTask(self, subagent_id: str, new_task: str, *,
                 steer_fn: Optional[Callable[[str, str], bool]] = None) -> Dict[str, Any]:
        """任务书修订（按 run 所处分流三态）：

        - 排队中（本面持有）→ 改写任务书，返回 ``{"mode": "requeued", ...}``；
        - 已在跑（不在本面）→ 调用方注入的 ``steer_fn(sid, text)`` 送达，
          返回 True 记 ``{"mode": "steered"}``；
        - 两者都不可能（不在队列且无 steer_fn / steer_fn 失败或异常）→
          ``{"mode": "rejected", "reason": ...}`` 诚实拒绝。

        steer_fn 的异常不吞：转成 rejected 并把失败原因随结果带出。
        """
        sid = str(subagent_id or "").strip()
        text = str(new_task or "").strip()
        if not text:
            raise ValueError("editTask 需要非空 new_task")
        with self._lock:
            entry = self._entries.get(sid)
            if entry is not None:
                # 排队中：任务书尚未开跑，直接改写（位次不受任务内容影响）
                entry["task"] = text
                return {
                    "mode": "requeued",
                    "subagent_id": sid,
                    "position": self._positionLocked(sid),
                }
        # 不在队列：可能已在跑——由调用方注入的 steer_fn 送达；不通则诚实拒绝
        if steer_fn is not None:
            try:
                if steer_fn(sid, text):
                    return {"mode": "steered", "subagent_id": sid}
            except Exception as e:  # noqa: BLE001 - 注入失败转显式拒绝，原因随结果带出
                return {"mode": "rejected", "subagent_id": sid,
                        "reason": f"steer_fn 注入失败: {e}"}
            return {"mode": "rejected", "subagent_id": sid,
                    "reason": "steer_fn 返回失败，任务书未送达"}
        return {"mode": "rejected", "subagent_id": sid,
                "reason": "不在队列且未提供 steer_fn，无法修订任务书"}

    def position(self, subagent_id: str) -> int:
        """当前队列位次（从 1 起）；不在队列返回 0。"""
        sid = str(subagent_id or "").strip()
        with self._lock:
            return self._positionLocked(sid)

    def snapshot(self) -> List[Dict[str, Any]]:
        """队列有序快照：优先级降序 + 同级先来先服务；每项含
        position/subagent_id/priority/task/queued_at。"""
        with self._lock:
            return [
                {
                    "position": idx + 1,
                    "subagent_id": entry["subagent_id"],
                    "priority": entry["priority"],
                    "task": entry["task"],
                    "queued_at": entry["queued_at"],
                }
                for idx, entry in enumerate(self._orderedLocked())
            ]
