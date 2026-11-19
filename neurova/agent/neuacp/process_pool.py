# -*- coding: utf-8 -*-
"""NeuacpProcessPool：外部编码代理子进程池（设计文档 §4.5/§6.4）。

- **键含租户段**：``(tenant, tool, command, cwd, transport, remote)``——
  跨租户不共享进程/会话（§6.4 强制红线，租户段固定在键首位）；
- **全局并发上限**：``NEUROVA_EXTERNAL_AGENTS_MAX_PROCS``（默认 4）——
  计的是存活进程（空闲 + 在用），到顶后 acquire 排队等待；
- **空闲回收**：``NEUROVA_EXTERNAL_AGENTS_IDLE_S``（默认 600s）——
  acquire 前惰性清扫 + 后台清扫线程双保险；
- **崩溃踢出**：空闲池里的死进程在取出/清扫时淘汰并计数；使用中崩溃经
  :meth:`discard` 显式踢出；重建一律由下次 acquire 惰性完成，池不主动重启。

池对进程对象只有两个鸭子面要求：``is_alive``（属性/property/方法皆可）与
``terminate()``（或退回 ``close()``）——``NeuacpClient`` 原生满足。进程创建
经调用方注入的 ``factory`` 完成，池不关心具体拉起方式。进程的关闭（可能
秒级阻塞）一律在锁外执行，名额记账在锁内先行。
"""
import os
import threading
import time
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.agent.neuacp.acp_client import NeuacpError

MAX_PROCS_ENV = "NEUROVA_EXTERNAL_AGENTS_MAX_PROCS"
IDLE_SECONDS_ENV = "NEUROVA_EXTERNAL_AGENTS_IDLE_S"
DEFAULT_MAX_PROCS = 4
DEFAULT_IDLE_SECONDS = 600.0

#: 池键：租户段在首位（§6.4），其余为执行体身份段。
PoolKey = Tuple[str, str, Tuple[str, ...], str, str, str]


def envMaxProcs() -> int:
    """全局外部进程上限（env 显式值最优先；非法/缺省回落默认）。"""
    raw = (os.environ.get(MAX_PROCS_ENV) or "").strip()
    if not raw:
        return DEFAULT_MAX_PROCS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_PROCS
    return value if value > 0 else DEFAULT_MAX_PROCS


def envIdleSeconds() -> float:
    """空闲回收阈值（秒）；非法回落默认，负值按 0（不驻留）。"""
    raw = (os.environ.get(IDLE_SECONDS_ENV) or "").strip()
    if not raw:
        return DEFAULT_IDLE_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_IDLE_SECONDS
    return max(0.0, value)


def _normalizeKey(key: Tuple) -> PoolKey:
    if len(key) != 6:
        raise ValueError(
            "进程池键必须是 (tenant, tool, command, cwd, transport, remote) 六元组，"
            f"收到 {len(key)} 元")
    tenant, tool, command, cwd, transport, remote = key
    return (
        str(tenant or "default"),
        str(tool or ""),
        tuple(str(part) for part in (command or ())),
        str(cwd or ""),
        str(transport or "stdio"),
        str(remote or ""),
    )


def poolKey(tenant: str, tool: str, command, cwd: str,
            transport: str = "stdio", remote: str = "") -> PoolKey:
    """构造规范化池键；租户段缺省回落 default。"""
    return _normalizeKey((tenant, tool, tuple(command or ()), cwd, transport, remote))


def _isAlive(process: Any) -> bool:
    """进程存活判定：is_alive 兼容属性/property/方法三种形态。"""
    try:
        alive = process.is_alive
    except AttributeError:
        return True
    if callable(alive):
        try:
            return bool(alive())
        except Exception:  # noqa: BLE001 - 健康探测失败按已死处理（fail-closed）
            return False
    return bool(alive)


def _closeProcess(process: Any) -> None:
    """关闭进程：优先 terminate（NeuacpClient/Popen 语义），退回 close。"""
    for name in ("terminate", "close"):
        method = getattr(process, name, None)
        if callable(method):
            try:
                method()
                return
            except Exception:  # noqa: BLE001 - 关闭失败不抛（池回收路径）
                continue


class _PoolEntry:
    """池内进程条目：进程本体 + 键 + 时间戳。"""

    __slots__ = ("key", "process", "created_at", "last_used", "closed")

    def __init__(self, key: PoolKey, process: Any) -> None:
        self.key = key
        self.process = process
        self.created_at = time.time()
        self.last_used = self.created_at
        self.closed = False


class NeuacpProcessPool:
    """外部编码代理子进程池：上限、排队、空闲回收、崩溃踢出。"""

    def __init__(self, *, maxProcs: Optional[int] = None,
                 idleSeconds: Optional[float] = None) -> None:
        self._maxProcs = int(maxProcs) if maxProcs is not None else envMaxProcs()
        self._idleSeconds = (float(idleSeconds) if idleSeconds is not None
                             else envIdleSeconds())
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        # key → 空闲条目队列（FIFO 复用，先还先用）
        self._idle: Dict[PoolKey, deque] = {}
        # 存活进程数（空闲 + 在用）——上限计的就是它
        self._liveCount = 0
        self._crashCount = 0
        self._waiters = 0
        self._closed = False
        self._sweeper: Optional[threading.Thread] = None

    # ── 主流程：获取 / 归还 / 踢出 ───────────────────────────────────────

    def acquire(self, key: PoolKey, factory: Callable[[], Any],
                waitTimeout: Optional[float] = None) -> _PoolEntry:
        """取一个进程：优先复用同键空闲件；无空闲且未到上限则新建；
        到上限则排队等待释放/回收，超过 ``waitTimeout`` 秒抛 NeuacpError。

        factory 在锁外执行（拉起进程可能秒级），名额先占后建：创建失败
        如实归还名额并唤醒排队者。清扫出的过期件在锁外关闭（finally 兜底，
        无论从哪条路退出都不漏关）。
        """
        key = _normalizeKey(key)
        deadline = None if waitTimeout is None else time.monotonic() + float(waitTimeout)
        self._ensureSweeper()
        pendingClose: List[_PoolEntry] = []
        try:
            while True:
                with self._condition:
                    if self._closed:
                        raise NeuacpError("外部进程池已关闭，无法获取进程")
                    pendingClose.extend(self._sweepIdleLocked())
                    entry = self._popIdleLocked(key)
                    if entry is not None:
                        return entry
                    if self._liveCount < self._maxProcs:
                        self._liveCount += 1  # 先占名额（锁内），锁外创建
                        break
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        raise NeuacpError(
                            f"外部进程池已满（存活 {self._liveCount}/{self._maxProcs}），"
                            f"排队等待超时（{waitTimeout:g}s）")
                    self._waiters += 1
                    try:
                        self._condition.wait(remaining)
                    finally:
                        self._waiters -= 1
        finally:
            for stale in pendingClose:
                _closeProcess(stale.process)
        try:
            process = factory()
        except Exception:
            with self._condition:
                self._liveCount -= 1
                self._condition.notify()
            raise
        return _PoolEntry(key, process)

    def release(self, key: PoolKey, entry: _PoolEntry) -> None:
        """归还进程：无人排队且进程健康 → 驻留空闲池待复用；否则关闭腾位。"""
        key = _normalizeKey(key)
        if entry.closed:
            return
        with self._condition:
            if self._closed:
                entry.closed = True
                self._liveCount -= 1
                self._condition.notify()
                toClose = True
            elif not _isAlive(entry.process):
                entry.closed = True
                self._liveCount -= 1
                self._crashCount += 1
                self._condition.notify()
                toClose = True
            elif self._waiters > 0:
                # 有排队者：空闲件对其键大概率无用（有匹配空闲件时它不会等），
                # 直接关闭腾出全局名额，唤醒一位去建自己的。
                entry.closed = True
                self._liveCount -= 1
                self._condition.notify()
                toClose = True
            else:
                entry.last_used = time.time()
                self._idle.setdefault(key, deque()).append(entry)
                toClose = False
        if toClose:
            _closeProcess(entry.process)

    def discard(self, key: PoolKey, entry: _PoolEntry, reason: str = "") -> None:
        """把一个进程踢出池（使用中崩溃/不可复用时调用）；排队者被唤醒补位。"""
        key = _normalizeKey(key)
        with self._condition:
            queue = self._idle.get(key)
            if queue is not None:
                try:
                    queue.remove(entry)
                except ValueError:
                    pass
                if not queue:
                    self._idle.pop(key, None)
            if entry.closed:
                return
            entry.closed = True
            self._liveCount -= 1
            self._crashCount += 1
            self._condition.notify()
        _closeProcess(entry.process)

    # ── 空闲回收 ─────────────────────────────────────────────────────────

    def sweepIdle(self) -> int:
        """回收空闲超时/已死的空闲进程，返回关闭数。后台清扫与测试共用入口。"""
        with self._condition:
            expired = self._sweepIdleLocked()
        for entry in expired:
            _closeProcess(entry.process)
        return len(expired)

    def _sweepIdleLocked(self) -> List[_PoolEntry]:
        """锁内清扫：摘出空闲过期/已死条目并记账，返回待关闭列表（锁外关）。"""
        now = time.time()
        expired: List[_PoolEntry] = []
        for key, queue in list(self._idle.items()):
            keep = deque()
            while queue:
                entry = queue.popleft()
                if entry.closed:
                    continue
                idleTooLong = now - entry.last_used > self._idleSeconds
                dead = not _isAlive(entry.process)
                if idleTooLong or dead:
                    entry.closed = True
                    self._liveCount -= 1
                    if dead:
                        self._crashCount += 1
                    expired.append(entry)
                else:
                    keep.append(entry)
            if keep:
                self._idle[key] = keep
            else:
                self._idle.pop(key, None)
        if expired:
            self._condition.notify_all()
        return expired

    def _popIdleLocked(self, key: PoolKey) -> Optional[_PoolEntry]:
        """锁内取一个同键空闲健康件；顺路淘汰死件（腾出的名额唤醒排队者）。"""
        while True:
            queue = self._idle.get(key)
            if not queue:
                self._idle.pop(key, None)
                return None
            entry = queue.popleft()
            if not queue:
                self._idle.pop(key, None)
            if entry.closed:
                continue
            if not _isAlive(entry.process):
                entry.closed = True
                self._liveCount -= 1
                self._crashCount += 1
                self._condition.notify()
                continue
            return entry

    def _ensureSweeper(self) -> None:
        """懒启动后台清扫线程（守护；间隔 = min(idle/4, 60s)，下限 1s）。"""
        with self._lock:
            if self._sweeper is not None or self._closed:
                return
            interval = max(1.0, min(self._idleSeconds / 4.0, 60.0))

            def sweepLoop():
                while True:
                    time.sleep(interval)
                    if self._closed:
                        return
                    try:
                        self.sweepIdle()
                    except Exception:  # noqa: BLE001 - 清扫失败下轮再试
                        continue

            self._sweeper = threading.Thread(
                target=sweepLoop, daemon=True, name="neuacp-pool-sweeper")
            self._sweeper.start()

    # ── 观测 / 关停 ──────────────────────────────────────────────────────

    def stats(self) -> dict:
        """池状态快照（status 端点/测试用）。"""
        with self._condition:
            idleCount = sum(len(queue) for queue in self._idle.values())
            return {
                "max_procs": self._maxProcs,
                "idle_seconds": self._idleSeconds,
                "live": self._liveCount,
                "idle": idleCount,
                "waiters": self._waiters,
                "crashes": self._crashCount,
                "closed": self._closed,
            }

    def shutdown(self) -> None:
        """关停池：关闭全部空闲进程、唤醒并拒绝后续 acquire。"""
        with self._condition:
            self._closed = True
            entries = [entry for queue in self._idle.values() for entry in queue]
            self._idle.clear()
            for entry in entries:
                if not entry.closed:
                    entry.closed = True
                    self._liveCount -= 1
            self._condition.notify_all()
        for entry in entries:
            _closeProcess(entry.process)


# ── 进程级共享池（全局上限要全局生效，单例承载）─────────────────────────

_poolLock = threading.RLock()
_poolInstance: Optional[NeuacpProcessPool] = None


def getNeuacpProcessPool() -> NeuacpProcessPool:
    """进程级共享池单例（DCL + RLock，见 AGENTS.md §3 单例纪律）。"""
    global _poolInstance
    if _poolInstance is None:
        with _poolLock:
            if _poolInstance is None:
                _poolInstance = NeuacpProcessPool()
    return _poolInstance
