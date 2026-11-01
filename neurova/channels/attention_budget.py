# -*- coding: utf-8 -*-
"""出站注意力预算——「同一件事不重复说 / 人在等就压住」的唯一实现（D-1 甲案）。

只服务**显式标记的主动/提醒类出口**（调用方给出 `attention_key`）。Agent 对用户
这一问的正文回复不带键，永远直发，不经过本模块——这是甲案的边界，不是待办。

三条语义：

1. **同键未发出者被新值覆盖**：键相同的消息若前一条还没发出去（正在发），后到的
   只留在待发槽里，且槽里只保留最新一条；正在发的那条发完后，只补发最新值。
2. **同键严格排队**：同一键同一时刻最多一条在发；发送器内部不会再并发。
3. **人在等就压住**：调用方用 `hold(holdKey)` 开窗、`release(holdKey)` 关窗；
   窗口内带同一 `holdKey` 的投递只入槽不发，关窗时补发最新一条。窗口按引用计数，
   重叠回合不会提前放行（`ChannelManager._dispatch_message` 是唯一开窗点）。

失败方向：发送函数抛错原样外抛（教条第 2 条：不吞异常），键在 `finally` 里释放，
后续消息仍可发送；未发出的待发值留给下一次调用，不静默丢弃。关窗冲洗失败只
留痕并回报 `sent=False`——此时调用方正在收尾，不能让补发失败顶掉本轮结果。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class DeliveryResult:
    """一次投递的结果。

    - `coalesced=True`：同名已在发，值已并入槽位，本条没有发；
    - `held=True`：命中了「人在等」窗口，值已入槽，等关窗补发。
    """

    sent: bool
    coalesced: bool
    message_id: Optional[Any] = None
    held: bool = False


SendFn = Callable[[str], Awaitable[Optional[Any]]]


class ChannelAttentionBudget:
    """按键维护「在发 / 待发最新值 / 持窗」的小状态机；单进程内使用。"""

    def __init__(self) -> None:
        self._pending: Dict[str, str] = {}
        self._inflight: Set[str] = set()
        self._holds: Dict[str, int] = {}
        self._holdKeyOf: Dict[str, str] = {}
        self._held: Dict[str, Tuple[str, SendFn]] = {}
        self._guard = threading.Lock()

    # ── 持窗 ────────────────────────────────────────────────

    def hold(self, holdKey: str) -> None:
        """开一个等待窗口（引用计数）。"""
        with self._guard:
            self._holds[holdKey] = self._holds.get(holdKey, 0) + 1

    async def release(self, holdKey: str) -> List[DeliveryResult]:
        """关窗；最后一层关闭时补发该窗口下每个键的最新一条。"""
        with self._guard:
            remaining = self._holds.get(holdKey, 0) - 1
            if remaining > 0:
                self._holds[holdKey] = remaining
                return []
            self._holds.pop(holdKey, None)
            toFlush = [
                (key, text, sendFn)
                for key, (text, sendFn) in self._held.items()
                if self._holdKeyOf.get(key) == holdKey
            ]
            for key, _, _ in toFlush:
                self._held.pop(key, None)

        results: List[DeliveryResult] = []
        for key, text, sendFn in toFlush:
            try:
                results.append(await self._deliverNow(key, text, sendFn))
            except Exception as exc:  # noqa: BLE001 - 收尾冲洗失败不得顶掉本轮结果
                logger.warning("待人窗口关窗冲洗失败 key=%s: %s", key, exc, exc_info=True)
                results.append(DeliveryResult(sent=False, coalesced=False))
        return results

    # ── 投递 ────────────────────────────────────────────────

    async def deliver(
        self, key: str, text: str, sendFn: SendFn, holdKey: Optional[str] = None
    ) -> DeliveryResult:
        with self._guard:
            if holdKey is not None:
                self._holdKeyOf[key] = holdKey
            else:
                self._holdKeyOf.pop(key, None)
            activeHold = self._holdKeyOf.get(key)
            if activeHold and self._holds.get(activeHold, 0) > 0:
                self._held[key] = (text, sendFn)
                return DeliveryResult(sent=False, coalesced=False, held=True)
            self._held.pop(key, None)

        return await self._deliverNow(key, text, sendFn)

    async def _deliverNow(self, key: str, text: str, sendFn: SendFn) -> DeliveryResult:
        with self._guard:
            self._pending[key] = text
            if key in self._inflight:
                return DeliveryResult(sent=False, coalesced=True)
            self._inflight.add(key)

        result = DeliveryResult(sent=False, coalesced=False)
        try:
            while True:
                with self._guard:
                    nextText = self._pending.pop(key, None)
                    if nextText is None:
                        # 解除在发前再查一次：避免「查空→新值入槽→解除」的丢值窗口
                        self._inflight.discard(key)
                        nextText = self._pending.pop(key, None)
                        if nextText is None:
                            return result
                        self._inflight.add(key)
                messageId = await sendFn(nextText)
                if messageId is not None:
                    result = DeliveryResult(sent=True, coalesced=False, message_id=messageId)
        finally:
            with self._guard:
                self._inflight.discard(key)


_budget: Optional[ChannelAttentionBudget] = None
_budgetLock = threading.RLock()


def getAttentionBudget() -> ChannelAttentionBudget:
    global _budget
    if _budget is None:
        with _budgetLock:
            if _budget is None:
                _budget = ChannelAttentionBudget()
    return _budget


def resetAttentionBudgetForTests() -> None:
    global _budget
    with _budgetLock:
        _budget = None
