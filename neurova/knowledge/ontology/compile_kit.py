# -*- coding: utf-8 -*-
"""本体编译并发工程件（对照研究 P3-3，2026-11-15）。

schema 建议器/未来自动编译管线要并行调 LLM 与探针，需要三件套：

- :class:`InflightLimiter`——在飞请求上限（对方 `limit_inflight` 的等价物）；
  LLM 并发超限会被端点 503 拒，限流要在管线作用域统一持锁，不是各调用点自理。
- :class:`OrderedCommitQueue`——LLM 并行抽取、**按规范顺序提交**的协调器
  （对方 `_OrderedCommitQueue` 的等价物）：名字类产物（术语注册唯一键）的归属
  必须确定性，抽取可以乱序完成，落库必须排队。
- :func:`runBounded`——有界并行的最小组装：worker 抛错不炸整批（逐项记入
  errors），取消语义 = 已在飞的跑完、未开始的跳过（不吵醒排队中的工作线程）。

全部零外部依赖；测试用确定性假 worker 覆盖（无 sleep 依赖真实时序）。
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional


class InflightLimiter:
    """在飞计数上限：`with limiter:` 超限即阻塞等待（作用域内复用同一把信号量）。"""

    def __init__(self, maxInflight: int = 6) -> None:
        import threading

        self._semaphore = threading.Semaphore(max(1, int(maxInflight)))

    def __enter__(self) -> "InflightLimiter":
        self._semaphore.acquire()
        return self

    def __exit__(self, excType, excValue, excTb) -> bool:
        self._semaphore.release()
        return False


class OrderedCommitQueue:
    """按位置排队提交：抽取乱序完成，commit 依 canonical 顺序。

    `skip` 允许某位置放弃排队且**不阻塞**工作线程（等轮到才放弃会占住
    稀缺的池线程）；跳过会在轮到时级联消化连续 skip。
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._nextPosition = 0
        self._skipped: set = set()

    def wait(self, position: int) -> None:
        with self._condition:
            while position != self._nextPosition:
                self._condition.wait()

    def advance(self, position: int) -> None:
        with self._condition:
            while position != self._nextPosition:
                self._condition.wait()
            self._nextPosition += 1
            self._drainSkippedLocked()
            self._condition.notify_all()

    def skip(self, position: int) -> None:
        with self._condition:
            self._skipped.add(position)
            self._drainSkippedLocked()
            self._condition.notify_all()

    def _drainSkippedLocked(self) -> None:
        while self._nextPosition in self._skipped:
            self._skipped.discard(self._nextPosition)
            self._nextPosition += 1


class CommitSlot:
    """一个条目的提交位：进入等位、退出推进、放弃走 skip（幂等）。"""

    def __init__(self, queue: OrderedCommitQueue, position: int) -> None:
        self._queue = queue
        self._position = position
        self._entered = False
        self._finished = False

    def __enter__(self) -> "CommitSlot":
        self._queue.wait(self._position)
        self._entered = True
        return self

    def __exit__(self, excType, excValue, excTb) -> bool:
        self._queue.advance(self._position)
        self._finished = True
        return False

    def skipIfUnused(self) -> None:
        if self._entered or self._finished:
            return
        self._queue.skip(self._position)
        self._finished = True


def runBounded(items: List[Any], worker: Callable[[Any, int], Any],
               maxWorkers: int = 3, isCancelled: Optional[Callable[[], bool]] = None,
               onResult: Optional[Callable[[Any], None]] = None) -> Dict[str, Any]:
    """有界并行跑 worker：返回 {"results": [...], "errors": [...], "cancelled": bool}。

    - worker(item, position) 的结果经 onResult 依**提交顺序**回调（名字类落库
      的确定性由调用方用 CommitSlot 自己排；这里保证的是回调顺序不抖动）；
    - 单项异常记入 errors（{"item", "position", "error"}），不炸整批；
    - isCancelled() 为真：未开始的项跳过、已在飞的等完——取消是止损不是掐断。
    """
    results: List[Optional[Any]] = [None] * len(items)
    errors: List[Dict[str, Any]] = []
    queue = OrderedCommitQueue()
    cancelledSeen = threading.Event()

    def _run(item: Any, position: int) -> None:
        slot = CommitSlot(queue, position)
        if isCancelled and isCancelled():
            cancelledSeen.set()
            slot.skipIfUnused()
            return
        try:
            result = worker(item, position)
            with slot:
                results[position] = result
                if onResult is not None:
                    onResult(result)
        except Exception as exc:  # noqa: BLE001 - 逐项隔离，失败不炸整批
            slot.skipIfUnused()
            errors.append({"item": item, "position": position,
                           "error": "%s: %s" % (type(exc).__name__, exc)})

    maxWorkers = max(1, int(maxWorkers))
    with ThreadPoolExecutor(max_workers=min(maxWorkers, len(items) or 1)) as pool:
        futures = [pool.submit(_run, item, position)
                   for position, item in enumerate(items)]
        for future in futures:
            future.result()
    return {"results": [r for r in results if r is not None],
            "errors": errors,
            "cancelled": cancelledSeen.is_set()}
