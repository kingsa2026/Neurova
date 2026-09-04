"""触发投递重试（P2 — webhook_deliveries 已有表补重试语义）。

- 失败投递（status=failed）按指数退避重试：attempt+1、
  next_retry_at = now + base * 2^(attempt-1)；达到 max_attempts 标 dead
- retry_delivery：手动单条重试（管理页按钮）；dead 不再重试
- retry_due：到期批量重试（后台调度消费）
- redeliver 回调注入式（生产接 webhook_ingress.handle_webhook_ingress，
  测试注入桩）——本模块只管重试账目，不重复实现入站协议
"""

from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_Redeliver = Callable[[str, int], Awaitable[Dict[str, Any]]]


class TriggerRetryService:
    """投递重试账目（退避/上限/dead 状态机；存储侧持久化）"""

    def __init__(self, storage: Any, max_attempts: int = 3, base_delay_s: float = 30.0):
        self._storage = storage
        self._max_attempts = max(1, int(max_attempts))
        self._base_delay = float(base_delay_s)

    def list_failed(self, limit: int = 100) -> List[Dict[str, Any]]:
        """待重试队列（failed 项）"""
        return self._storage.list_failed_deliveries(limit=limit)

    async def retry_delivery(self, delivery_id: int, redeliver: _Redeliver) -> Dict[str, Any]:
        """单条重试：成功标 delivered；失败退避或标 dead。"""
        row = self._storage.get_delivery(delivery_id)
        if row is None:
            return {"success": False, "status": "not_found", "error": f"投递记录不存在: {delivery_id}"}
        status = str(row.get("status") or "")
        if status == "dead":
            return {"success": False, "status": "dead", "error": "已达重试上限"}
        if status == "delivered":
            return {"success": True, "status": "delivered", "error": "已投递，无需重试"}

        attempt = int(row.get("attempt") or 0) + 1
        trigger_id = str(row.get("trigger_id") or "")

        try:
            outcome = await redeliver(trigger_id, attempt) or {}
        except Exception as e:  # noqa: BLE001 — 重新投递异常视同失败
            logger.warning("重投异常 delivery=%s: %s", delivery_id, e)
            outcome = {"ok": False, "error": str(e)}

        if outcome.get("ok"):
            self._storage.update_delivery_retry(
                delivery_id, attempt=attempt, next_retry_at=0.0,
                status="delivered", execution_id=outcome.get("execution_id"),
            )
            logger.info("投递重试成功 delivery=%s attempt=%s", delivery_id, attempt)
            return {"success": True, "status": "delivered", "attempt": attempt,
                    "execution_id": outcome.get("execution_id")}

        if attempt >= self._max_attempts:
            self._storage.update_delivery_retry(
                delivery_id, attempt=attempt, next_retry_at=0.0, status="dead"
            )
            logger.warning("投递重试达上限标记 dead delivery=%s attempt=%s", delivery_id, attempt)
            return {"success": False, "status": "dead", "attempt": attempt}

        next_at = time.time() + self._base_delay * (2 ** (attempt - 1))
        self._storage.update_delivery_retry(
            delivery_id, attempt=attempt, next_retry_at=next_at, status="pending_retry"
        )
        return {"success": False, "status": "pending_retry", "attempt": attempt,
                "next_retry_at": next_at}

    async def retry_due(self, redeliver: _Redeliver, limit: int = 20) -> List[int]:
        """到期批量重试（failed 首试 + 到期 pending_retry；返回已处理 id）"""
        now = time.time()
        processed: List[int] = []
        # failed（首试，next_retry_at=0 即到期）与到期 pending_retry 一并处理
        with self._storage._lock:
            rows = self._storage._conn.execute(
                "SELECT id FROM webhook_deliveries WHERE status IN ('failed', 'pending_retry')"
                " AND next_retry_at <= ? AND attempt < ? ORDER BY next_retry_at ASC LIMIT ?",
                (now, self._max_attempts, int(limit)),
            ).fetchall()
        for row in rows:
            delivery_id = int(row["id"])
            await self.retry_delivery(delivery_id, redeliver)
            processed.append(delivery_id)
        return processed


__all__ = ["TriggerRetryService"]
