# -*- coding: utf-8 -*-
"""折叠 rollup 后台化：失败批次的摘要补做与失败回滚（Issue #90 · T-11e）。

## 为什么要有这个模块

工单 §12.7 判据 6：**每轮新增摘要 LLM 调用 ≤ 1 次（rollup 走后台）**。
改前折叠路径把压缩器的「摘要失败 → 丢最旧一条重试（上限 `_SUMMARY_MAX_RETRIES` = 3）」
整段跑在关键路径上：摘要器恒失败时单轮 `build_context` **实测发起 4 次** LLM 调用
（1 次首试 + 3 次重试）——失败越多、调用越多，正是这条判据要挡住的曲线。

## 为什么不是 `ensure_future` 发后不管

工单 §12.5 第 4 条把「rollup 用 `asyncio.ensure_future` 发后不管」明列为假实现
（现成反例 `openai_loop.py:492/555`：异常无人 await，失败静默消失）。故本模块的
worker 必须：

- **持有并 await 自己的任务**：异常被记账成 `last_error`（点名类型与消息），
  不逃逸成"未处理异常"，也不静默；
- **失败不写**：只有摘要**成功**才回调写入侧（推进覆盖账 + 写层节点）——
  与 T-05 同族纪律，摘要失败不得推进覆盖账；
- **有界**：同会话在飞至多 1 个、全局在飞有上限；超出的派发被**丢弃并计数**
  （`dropped`），不静默堆积。

回退开关 `NEUROVA_CONTEXT_ROLLUP=0`：不装配 worker，折叠行为回到本票之前的形状
（§12.6 要求回退等式，纪律同 §11.7 第 3 条）。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 回退开关的环境变量名（读数与文档都取这一处，不各写一份字面串）。
ROLLUP_ENV = "NEUROVA_CONTEXT_ROLLUP"

#: 在飞上限。后台是补做队列，不是无限缓冲：会话越长，堆积越多 ⇒ 上限必须存在，
#: 超出的派发记 `dropped`（可见），而不是让内存随会话时长增长（T-07 的纪律同理）。
MAX_GLOBAL_IN_FLIGHT = 4
MAX_SESSION_IN_FLIGHT = 1


def rollupEnabled() -> bool:
    """回退开关：默认开；显式 `0` 关（关时不装配 worker）。"""
    return (os.environ.get(ROLLUP_ENV, "1") or "1").strip() != "0"


class ContextRollupWorker:
    """折叠 rollup 的后台补做队列（每会话在飞 ≤ 1，失败不推进覆盖账）。

    `commit` 是写入侧的唯一回调（由编排器提供）：它拿到的只有**已成功的摘要**，
    因此"失败不写"这条纪律由本类的调用点位置保证，而不是靠调用方自觉。
    """

    def __init__(
        self,
        commit: Callable[[str, str, Sequence[str], Sequence[str], int], None],
        *,
        maxGlobalInFlight: int = MAX_GLOBAL_IN_FLIGHT,
        maxSessionInFlight: int = MAX_SESSION_IN_FLIGHT,
    ):
        self._commit = commit
        self._maxGlobalInFlight = max(1, int(maxGlobalInFlight))
        self._maxSessionInFlight = max(1, int(maxSessionInFlight))
        # 键是会话槽键（与折叠缓存槽**同一个键**：引用/索引/补做三处同源）。
        self._tasks: Dict[str, asyncio.Task] = {}
        self._readout: Dict[str, Any] = {
            "dispatched": 0,
            "succeeded": 0,
            "failed": 0,
            "dropped": 0,
            "last_error": None,
        }

    def dispatch(
        self,
        *,
        sessionKey: str,
        summarize: Optional[Callable[..., Awaitable[Optional[str]]]],
        droppedMsgs: Sequence[Any],
        covers: Sequence[str],
        turnIds: Sequence[str],
        lastCount: int,
    ) -> bool:
        """把一个失败批次交给后台补做；返回是否真的派发（False 记 `dropped`）。"""
        if summarize is None or not droppedMsgs:
            return False
        key = str(sessionKey or "direct")
        current = self._tasks.get(key)
        if current is not None and not current.done():
            self._readout["dropped"] += 1
            logger.info(
                "折叠 rollup 补做派发被丢弃（同会话已有在飞任务）：session=%s", key
            )
            return False
        if len(self._tasks) >= self._maxGlobalInFlight:
            self._readout["dropped"] += 1
            logger.info("折叠 rollup 补做派发被丢弃（全局在飞已达上限）：session=%s", key)
            return False

        self._readout["dispatched"] += 1
        task = asyncio.ensure_future(
            self._run(
                key,
                summarize,
                list(droppedMsgs),
                list(covers),
                list(turnIds),
                int(lastCount),
            )
        )
        # 持有强引用：只把 task 交给事件循环的话，它在完成后可能被回收，
        # 而 `drain()` 与读数都靠这份引用（"发后不管"正好是缺了这一步）。
        self._tasks[key] = task
        task.add_done_callback(lambda _t, k=key: self._tasks.pop(k, None))
        return True

    async def _run(
        self,
        key: str,
        summarize: Callable[..., Awaitable[Optional[str]]],
        droppedMsgs: List[Any],
        covers: List[str],
        turnIds: List[str],
        lastCount: int,
    ) -> None:
        """后台补做体：本协程是任务本体，异常在这里被记账（不逃逸、不静默）。"""
        try:
            summary = await summarize(droppedMsgs, "")
            if not summary:
                raise RuntimeError("rollup 摘要返回空（不推进覆盖账，T-05 同族）")
            self._commit(key, summary, covers, turnIds, lastCount)
            self._readout["succeeded"] += 1
        except Exception as exc:  # noqa: BLE001 - 后台失败必须被记账，不静默
            self._readout["failed"] += 1
            self._readout["last_error"] = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "折叠 rollup 后台补做失败（覆盖账未推进）：%s", self._readout["last_error"]
            )

    def inFlightCount(self, sessionKey: str) -> int:
        """该会话在飞补做数（0/1）—— `dispatch` 的丢弃判据与读数同源。"""
        return sum(
            1
            for key, task in self._tasks.items()
            if key == str(sessionKey or "direct") and not task.done()
        )

    async def drain(self) -> None:
        """等全部在飞补做跑完（测试与收尾用；生产路径不 await 它）。"""
        while True:
            pending = [task for task in self._tasks.values() if not task.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    def stats(self) -> Dict[str, Any]:
        """读数（形状由编排器的 `_emptyContextHealth()` 单源给出，这里只填值）。"""
        return {
            **self._readout,
            "in_flight": len([t for t in self._tasks.values() if not t.done()]),
        }
