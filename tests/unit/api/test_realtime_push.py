# -*- coding: utf-8 -*-
"""SSE 推送统一模板（neurova/api/realtime_push.py）行为钉子。

钉四条契约（推送韧性四件套，计划 docs/04-plans/2026-11-20-reference-aa-borrowable-
mechanisms-plan.md 项 4）：
1. 订阅先于读首屏 -> 首屏快照 -> 增量：快照读取之后才到达的事件经游标必达（不漏），
   快照里已有的帧不重发（不重）；
2. 心跳周期内重验订阅权限：authorize 返回 False 后，服务端在当前心跳内收尾——
   "权限过期连接仍存活"不得发生；
3. 心跳是对外兼容的注释帧 `: keep-alive\n\n`，数据帧格式由 renderFrame 决定
   （既有出口为 `data: {json}\n\n`）；
4. 终态帧后收尾；增量源永久关闭（FEED_EXHAUSTED）即收尾。
"""

import asyncio
import json

from neurova.api.realtime_push import FEED_EXHAUSTED, PollingSnapshotFeed, ssePushStream


def _render(frame):
    """与既有出口相同的对外帧格式。"""
    return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"


class _ScriptedFeed:
    """测试用 feed：首屏给定；增量按脚本给；支持在首屏读取后注入新帧。"""

    def __init__(self, snapshotFrames=None, terminalTypes=("done",)):
        self.snapshotFrames = list(snapshotFrames or [])
        self.laterFrames = []          # 快照之后才到达的帧（增量源）
        self.terminalTypes = set(terminalTypes)
        self.onSnapshotRead = None     # 钩子：首屏读取完成时触发
        self.exhausted = False         # 置 True 后增量源永久关闭

    def snapshot(self):
        frames = list(self.snapshotFrames)
        if self.onSnapshotRead:
            self.onSnapshotRead()
        return frames

    def frameKey(self, frame):
        return frame["seq"]

    def isTerminal(self, frame):
        return frame.get("type") in self.terminalTypes

    async def nextFrame(self, afterKey, timeout):
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max(timeout, 0.0)
        while True:
            fresh = [f for f in self.laterFrames if afterKey is None or f["seq"] > afterKey]
            if fresh:
                self.laterFrames.remove(fresh[0])
                return fresh[0]
            if self.exhausted:
                return FEED_EXHAUSTED
            if loop.time() >= deadline:
                return None
            await asyncio.sleep(0.005)


def _collect(stream, maxChunks=50):
    """驱动异步生成器到自然收尾（或上限），收集全部输出块。"""

    async def _run():
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)
            if len(chunks) >= maxChunks:
                break
        return chunks

    return asyncio.run(_run())


def _dataSeqs(chunks):
    return [json.loads(c[len("data:"):].strip())["seq"] for c in chunks if c.startswith("data:")]


def test_快照后到达的事件经增量必达不丢():
    """订阅先于读首屏：首屏读完后才写入的帧，经增量游标必须送达。"""
    feed = _ScriptedFeed(snapshotFrames=[{"seq": 1, "type": "snapshot"}])

    def _lateArrival():
        # 模拟"读首屏与取增量之间"事件源又记了一帧
        feed.laterFrames.append({"seq": 2, "type": "delta"})
        feed.exhausted = True

    feed.onSnapshotRead = _lateArrival

    chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, heartbeatInterval=0.05))

    assert _dataSeqs(chunks) == [1, 2], chunks


def test_快照与增量按游标衔接不重不漏():
    feed = _ScriptedFeed(snapshotFrames=[{"seq": 1}, {"seq": 2}])

    def _lateArrival():
        feed.laterFrames.extend([{"seq": 3}, {"seq": 4}])
        feed.exhausted = True

    feed.onSnapshotRead = _lateArrival

    chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, heartbeatInterval=0.05))

    assert _dataSeqs(chunks) == [1, 2, 3, 4], chunks


def test_权限过期_一个心跳内断开():
    """权限重验钩子：authorize 判 False 后，当前心跳内收尾，不再吐任何帧。"""
    feed = _ScriptedFeed()  # 无首屏、无增量：nextFrame 每次等满超时返回 None
    checks = {"n": 0}

    def _authorize():
        checks["n"] += 1
        return False

    chunks = _collect(
        ssePushStream(feed=feed, renderFrame=_render, authorize=_authorize, heartbeatInterval=0.05)
    )

    assert chunks == [], "权限过期后不得再吐任何帧（含心跳注释帧）"
    assert checks["n"] == 1, "权限重验必须发生在首个心跳周期内"


def test_权限有效_心跳是注释行保活帧():
    feed = _ScriptedFeed()
    beats = {"n": 0}

    def _authorize():
        beats["n"] += 1
        if beats["n"] >= 3:
            feed.exhausted = True  # 第 3 次心跳后关源收尾（测试钩子）
        return True

    chunks = _collect(
        ssePushStream(feed=feed, renderFrame=_render, authorize=_authorize, heartbeatInterval=0.05)
    )

    assert chunks == [": keep-alive\n\n"] * 3, chunks


def test_数据帧对外格式保持data前缀():
    feed = _ScriptedFeed(snapshotFrames=[{"seq": 1, "type": "x"}], terminalTypes=("x",))

    chunks = _collect(ssePushStream(feed=feed, renderFrame=_render))

    assert chunks == ['data: {"seq": 1, "type": "x"}\n\n'], chunks


def test_终态帧后收尾_增量不再消费():
    feed = _ScriptedFeed(snapshotFrames=[{"seq": 1, "type": "done"}])
    feed.laterFrames.append({"seq": 2, "type": "after"})

    chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, heartbeatInterval=0.05))

    assert len(chunks) == 1, chunks
    assert not feed.laterFrames or _dataSeqs(chunks)[-1] == 1


def test_增量源永久关闭即收尾():
    feed = _ScriptedFeed()
    feed.exhausted = True

    chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, heartbeatInterval=0.05))

    assert chunks == []


def test_maxFrames测试钩子截断():
    feed = _ScriptedFeed(snapshotFrames=[{"seq": 1}, {"seq": 2}])

    chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, maxFrames=1))

    assert _dataSeqs(chunks) == [1]


def test_轮询适配器_增量只取游标之后():
    """PollingSnapshotFeed：snapshot 与 nextFrame 共享游标语义，帧不重不漏。"""
    store = [{"seq": 1}, {"seq": 2}]
    feed = PollingSnapshotFeed(
        snapshotFn=lambda afterKey: [f for f in store if afterKey is None or f["seq"] > afterKey],
        keyFn=lambda f: f["seq"],
        pollInterval=0.005,
    )

    first = feed.snapshot()
    assert [f["seq"] for f in first] == [1, 2]

    store.append({"seq": 3})
    nxt = asyncio.run(feed.nextFrame(feed.frameKey(first[-1]), timeout=0.5))
    assert nxt["seq"] == 3

    store.clear()
    exhausted = asyncio.run(feed.nextFrame(3, timeout=0.05))
    assert exhausted is None


def test_执行事件流已接统一推送模板():
    """样例迁移钉子：neurflow 执行事件流必须走统一模板（通知/状态类 SSE 的样板）。"""
    import inspect

    from neurova.api.endpoints import neurflow_api

    assert "ssePushStream" in inspect.getsource(neurflow_api)
