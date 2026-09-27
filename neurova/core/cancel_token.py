# -*- coding: utf-8 -*-
"""轮级取消令牌（协作式取消的下沉通路）。

## 为什么必须有它

阻塞调用按规矩一律下沉线程池（`tool_executor._blocking_fetch` 立的"只允许经
`asyncio.to_thread`"），而 `Task.cancel()` 对**已进入线程池**的调用无效：它只让
`await` 丢掉结果，线程照跑到自然结束。实测（本片取证）：

    task = asyncio.ensure_future(asyncio.to_thread(work))
    await asyncio.sleep(0.15); task.cancel()
    # 取消后计数 1 → 0.4s 后 9：worker 仍在推进

于是"取消沿 await 点传播"这句只在到达线程池边界**之前**成立。对进程型工具，
结果就是界面已认为中止、子进程继续占 CPU 与句柄。

本模块给 worker 一条**外部可达的通路**：令牌持有杀灭回调，置位时同步执行它们。
回调是唯一被允许打断线程池里那次调用的手段——信号发给进程，阻塞的 `communicate`
随之返回，线程自己退出。

## 不新增第二个取消入口

令牌不是新的取消源。取消源仍是 `core/task_tracker.request_session_stop`；令牌
只是它的**执行层延伸**——外层 `CancelledError` 到达 await 边界时触发置位
（见 `agent/tool_coordinator.run_with_timeout`），进程杀灭随之兑现。

## 生命周期

令牌按**轮**持有（与耗时常量累加器同款纪律：轮首换绑新对象，不跨轮复用），
不挂 loop 实例——loop 是 per-agent 单例，挂上去会让交叠会话互相取消
（Issue #268 缺陷 A 的同型污染）。
"""

from __future__ import annotations

import asyncio
import threading
from contextvars import ContextVar
from typing import Callable, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "CancelToken",
    "setTurnCancelToken",
    "getTurnCancelToken",
    "resetTurnCancelToken",
    "registerKillAction",
]


class CancelToken:
    """一次可取消执行单元的协作令牌。

    线程安全：置位可能发生在事件循环线程，而杀灭回调注册可能发生在线程池
    worker 里（进程刚 `Popen` 出来就注册），故内部用 `RLock` 串行化。
    """

    __slots__ = ("_lock", "_cancelled", "_reason", "_actions")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cancelled = False
        self._reason = ""
        self._actions: List[Callable[[], None]] = []

    def cancelled(self) -> bool:
        """worker 轮询点：长循环分片处自查，据此提前收手。"""
        return self._cancelled

    @property
    def reason(self) -> str:
        """置位原因（`timeout` / `user`）；未置位为空串。"""
        return self._reason

    def raiseIfCancelled(self) -> None:
        """长循环分片处调用：已置位即以 `CancelledError` 收手。

        抛的是 `CancelledError` 而不是自定义异常类型——取消在 Python 里只有这一个
        语义，自造一种会让每一层调用方都要写两套 except。
        """
        if self._cancelled:
            raise asyncio.CancelledError(f"已取消（{self._reason or '未说明原因'}）")

    def onCancel(self, action: Callable[[], None]) -> None:
        """注册杀灭回调；**已置位则立即兑现**。

        立即兑现不是便利：进程可能在上层置位之后、worker 拿到 PID 之前才注册
        回调（`Popen` 与注册之间存在窗口）。丢弃这个迟到的回调，等于那个进程
        永远不会被回收。

        单个回调抛错不阻断其余回调——一个坏工具的进程失败不该拖住同一轮里
        其它工具的收尸。失败以警告形态暴露，不静默。
        """
        run_now = False
        with self._lock:
            if self._cancelled:
                run_now = True
            else:
                self._actions.append(action)
        if run_now:
            self._run(action)

    def cancel(self, reason: str = "") -> None:
        """置位并**同步**执行全部已注册的杀灭回调（幂等）。"""
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            self._reason = str(reason or "")
            actions = list(self._actions)
            self._actions.clear()
        for action in actions:
            self._run(action)

    @staticmethod
    def _run(action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as e:  # noqa: BLE001 - 单个杀灭回调失败不阻断其余回调
            logger.warning("取消回调执行失败（该资源的回收需另行确认）: %s", e)


#: 本轮的工具取消令牌。与耗时常量累加器同款：轮首换绑，不跨轮复用。
#: 用 ContextVar 而非模块级全局：并发会话各有各的令牌，互不置位。
_turn_token_var: ContextVar = ContextVar("neurova_turn_cancel_token", default=None)


def setTurnCancelToken(token: Optional[CancelToken]) -> None:
    """绑定额外的取消令牌（`None` = 清除；轮首调用）。"""
    _turn_token_var.set(token)


def getTurnCancelToken() -> Optional[CancelToken]:
    """当前轮的工具取消令牌；未绑定返回 None（调用方按无令牌处置）。"""
    token = _turn_token_var.get()
    return token if isinstance(token, CancelToken) else None


def resetTurnCancelToken() -> CancelToken:
    """轮首换绑一只新令牌（**必须换新对象**，不能把已置位的那个复位）。

    复位看起来等价，实则不同：上一轮的取消若已被置位，复位后本轮首个进程
    注册回调就会立即被兑现——新任务被上一轮的取消理由杀掉。
    """
    token = CancelToken()
    _turn_token_var.set(token)
    return token


def registerKillAction(action: Callable[[], None]) -> bool:
    """把杀灭动作挂到**当前轮**的令牌上；本轮无令牌返回 False。

    这是进程型执行体唯一该走的注册口（不各自 import 令牌再判断），
    保证"何处可被取消"只有一份判据。
    """
    token = getTurnCancelToken()
    if token is None:
        return False
    token.onCancel(action)
    return True
