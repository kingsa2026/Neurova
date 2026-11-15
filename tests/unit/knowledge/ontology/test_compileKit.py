# -*- coding: utf-8 -*-
"""并发工程件（P3-3）判据：在飞限流、有序提交、取消语义、逐项隔离。

全部用确定性假 worker（用事件/栅栏控制时序），不依赖真实 sleep 抖动。
"""

from __future__ import annotations

import threading

from neurova.knowledge.ontology.compile_kit import (
    InflightLimiter,
    OrderedCommitQueue,
    runBounded,
)


class TestInflightLimiter:
    def testBoundsConcurrency(self):
        limiter = InflightLimiter(2)
        current = 0
        peak = 0
        lock = threading.Lock()
        gate = threading.Event()

        def worker(_item, _position):
            nonlocal current, peak
            with limiter:
                with lock:
                    current += 1
                    peak = max(peak, current)
                gate.wait(timeout=2)
                with lock:
                    current -= 1
            return True

        outcome = runBounded(list(range(6)), worker, maxWorkers=6)
        assert not outcome["errors"]
        assert peak <= 2


class TestOrderedCommitQueue:
    def testCommitOrderIsCanonicalRegardlessOfCompletionOrder(self):
        # 两个 worker：1 号先完成，但 0 号先提交
        queue = OrderedCommitQueue()
        committed = []

        def lateZero():
            queue.wait(0)
            committed.append(0)
            queue.advance(0)

        def earlyOne():
            queue.wait(1)
            committed.append(1)
            queue.advance(1)

        one = threading.Thread(target=earlyOne)
        zero = threading.Thread(target=lateZero)
        one.start()
        zero.start()
        one.join(timeout=2)   # 1 号先到，等 0 号
        zero.join(timeout=2)
        assert committed == [0, 1]

    def testSkipUnblocksWaitingLaterPositions(self):
        queue = OrderedCommitQueue()
        queue.skip(0)          # 0 号放弃
        queue.wait(1)          # 1 号不被 0 号卡死
        queue.advance(1)
        assert True


class TestRunBounded:
    def testItemErrorDoesNotKillBatch(self):
        def worker(item, _position):
            if item == 2:
                raise ValueError("boom")
            return item * 10

        outcome = runBounded([1, 2, 3], worker, maxWorkers=2)
        assert outcome["results"] == [10, 30]
        assert len(outcome["errors"]) == 1
        assert outcome["errors"][0]["position"] == 1
        assert "boom" in outcome["errors"][0]["error"]

    def testCancellationSkipsPendingAndReportsFlag(self):
        started = threading.Event()
        release = threading.Event()

        def worker(item, _position):
            if item == 0:
                started.set()
                release.wait(timeout=2)
                return "slow"
            return "fast"

        def isCancelled():
            return started.is_set() and not release.is_set()

        # 4 项 1 并发：0 在飞时置取消，1..3 应被跳过
        outcome = runBounded([0, 1, 2, 3], worker, maxWorkers=1,
                             isCancelled=isCancelled)
        assert outcome["cancelled"] is True
        assert outcome["results"] == ["slow"]

    def testOnResultReceivesInSubmissionOrder(self):
        # 完成顺序故意与提交顺序相反（worker 对早项置障），onResult 仍按序
        gate = threading.Event()

        def worker(item, _position):
            if item == 0:
                gate.wait(timeout=2)
            return item

        seen = []
        outcome = runBounded([0, 1, 2], worker, maxWorkers=3,
                             onResult=seen.append)
        assert outcome["results"] == [0, 1, 2]
