# -*- coding: utf-8 -*-
"""P2-8 压缩生命周期钩子事件化判据。

`compact_window` 的生命周期经统一事件总线（`neurova.core.event_bus`）发布
before / after / error 三类进程内钩子事件；事件名常量单源在
`neurova.context.compaction_lifecycle`（修复教义第 6 条，消费方只准引用常量）。

判据：
- 超预算折叠：before / after 各恰好一次（不随递进折叠轮数重复发），
  负载字段齐、tokens_before > tokens_after、compacted_count > 0
- 未超预算：返回 None，零事件（不空转）
- 摘要器失败：COMPACT_ERROR(phase="summarize")，压缩仍 fail-open 正常返回
- 订阅者自身抛异常不反噬压缩主链路
- 事件 data 一律可 json.dumps（进程内钩子也要能进日志/遥测管道）
"""
import json

import pytest

from neurova.core.event_bus import get_event_bus, reset_event_bus
from neurova.context.compaction_lifecycle import (
    COMPACT_AFTER,
    COMPACT_BEFORE,
    COMPACT_ERROR,
)


@pytest.fixture(autouse=True)
def _freshEventBus():
    """每例独占一条干净总线：隔离订阅，跑完复位，不给别的测试留订阅者。"""
    reset_event_bus()
    yield
    reset_event_bus()


def _overBudgetMsgs(count=12):
    """构造确定超预算的窗口（中文密文：词级估算器对连续 ASCII 弱计数）。"""
    return [
        {"role": "user", "content": f"第{i}条消息：" + "重要内容" * 60}
        for i in range(count)
    ]


async def _fakeSummarize(droppedMsgs, previousSummary=""):
    """恒成功的假摘要器：返回可辨认的摘要串。"""
    return "摘要：" + "；".join(str(m.get("content", ""))[:12] for m in droppedMsgs[:3])


class _EventCollector:
    """订阅一组事件名，收集 (事件名, data 载荷)。"""

    def __init__(self, *eventNames):
        bus = get_event_bus()
        self.payloads = []
        for name in eventNames:
            bus.subscribe(name, self._onEvent)

    def _onEvent(self, event):
        self.payloads.append({"name": event.name, "data": event.data})

    def of(self, eventName):
        return [p for p in self.payloads if p["name"] == eventName]


class TestCompactionLifecycleEvents:
    @pytest.mark.asyncio
    async def testBeforeAndAfterEmittedOnCompaction(self):
        """超预算折叠：before/after 各一次，字段齐、前后读数方向正确。"""
        from neurova.context.window_compactor import compact_window

        collector = _EventCollector(COMPACT_BEFORE, COMPACT_AFTER, COMPACT_ERROR)
        compaction = await compact_window(
            _overBudgetMsgs(), 300,
            summarize=_fakeSummarize, keep_min_messages=2,
            sessionKey="sess-1",
        )
        assert compaction is not None

        before = collector.of(COMPACT_BEFORE)
        after = collector.of(COMPACT_AFTER)
        assert len(before) == 1, "before 进入时发一次，不随递进轮数重复"
        assert len(after) == 1, "after 返回前发一次"
        assert collector.of(COMPACT_ERROR) == [], "正常折叠不发 error"

        b = before[0]["data"]
        assert b["sessionKey"] == "sess-1"
        assert b["phase"] == "before"
        assert b["msgsCount"] == 12
        assert b["budgetTokens"] == 300
        assert isinstance(b["ts"], str) and b["ts"]
        json.dumps(b)  # 负载可 JSON 序列化

        a = after[0]["data"]
        assert a["sessionKey"] == "sess-1"
        assert a["phase"] == "after"
        assert a["tokensBefore"] > a["tokensAfter"] > 0
        assert a["compactedCount"] > 0
        assert a["summaryIsFresh"] is True
        assert a["windowSize"] == len(compaction.window)
        json.dumps(a)

    @pytest.mark.asyncio
    async def testNoEventsWhenUnderBudget(self):
        """未超预算：返回 None 且 before/after 均不发（零空转噪声）。"""
        from neurova.context.window_compactor import compact_window

        collector = _EventCollector(COMPACT_BEFORE, COMPACT_AFTER, COMPACT_ERROR)
        result = await compact_window(
            [{"role": "user", "content": "tiny"}], 10000,
            summarize=_fakeSummarize, sessionKey="sess-2",
        )
        assert result is None
        assert collector.payloads == [], "未超预算零事件"

    @pytest.mark.asyncio
    async def testErrorEventOnSummarizeFailure(self):
        """摘要器恒抛：COMPACT_ERROR(phase=summarize)，压缩仍 fail-open 返回。"""
        from neurova.context.window_compactor import compact_window

        async def alwaysFail(droppedMsgs, previousSummary=""):
            raise RuntimeError("摘要服务不可用")

        collector = _EventCollector(COMPACT_BEFORE, COMPACT_AFTER, COMPACT_ERROR)
        compaction = await compact_window(
            _overBudgetMsgs(), 300,
            summarize=alwaysFail, keep_min_messages=2,
            sessionKey="sess-3",
        )
        # 既有 fail-open 语义不回退：折叠结果照常产出（无摘要）
        assert compaction is not None
        assert compaction.compacted_count > 0
        assert compaction.summary is None

        errors = collector.of(COMPACT_ERROR)
        assert len(errors) >= 1, "摘要失败必须发 error 事件"
        assert all(e["data"]["phase"] == "summarize" for e in errors)
        assert all(e["data"]["sessionKey"] == "sess-3" for e in errors)
        assert all(e["data"]["errorType"] == "RuntimeError" for e in errors)
        assert all("摘要服务不可用" in e["data"]["errorMessage"] for e in errors)
        json.dumps(errors[0]["data"])
        # before / after 生命周期事件照常
        assert len(collector.of(COMPACT_BEFORE)) == 1
        assert len(collector.of(COMPACT_AFTER)) == 1

    @pytest.mark.asyncio
    async def testSubscriberExceptionDoesNotBreakCompaction(self):
        """订阅者自身抛异常：总线隔离之，压缩结果与正常订阅者均不受影响。"""
        from neurova.context.window_compactor import compact_window

        bus = get_event_bus()

        def explodingHandler(event):
            raise ValueError("订阅者自身故障")

        for name in (COMPACT_BEFORE, COMPACT_AFTER):
            bus.subscribe(name, explodingHandler)
        collector = _EventCollector(COMPACT_BEFORE, COMPACT_AFTER)

        compaction = await compact_window(
            _overBudgetMsgs(), 300,
            summarize=_fakeSummarize, keep_min_messages=2,
            sessionKey="sess-4",
        )
        assert compaction is not None, "订阅者故障不得反噬压缩主链路"
        assert compaction.compacted_count > 0
        assert len(collector.of(COMPACT_BEFORE)) == 1, "正常订阅者仍收到 before"
        assert len(collector.of(COMPACT_AFTER)) == 1, "正常订阅者仍收到 after"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
