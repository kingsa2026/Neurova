# -*- coding: utf-8 -*-
"""E3 性能与资源治理：SSE 流字节预算 / 单事件上限 / 压缩协商（ws_stream_budget）行为钉子。

钉五条契约：
1. 压缩协商单源：无头 → identity；显式 gzip → 启用；多候选取服务端首选（gzip）；
   q=0 视为拒绝；通配 * 视为接受 gzip；大小写不敏感；
2. 单事件上限：限内原样通过；超限**整体替换**为诚实占位（绝不产出半截 JSON）；
3. ReplayByteBudget：累计记账、超预算置降级标记、可重置、负预算拒绝创建；
4. ssePushStream 接线回归钉：默认参数（不传 byte_budget/event_cap）输出与改前逐字一致；
5. ssePushStream 接线：超单事件上限 → 诚实占位帧；累计超预算 → 扣下溢出帧、
   发一帧 `event: snapshot_downgrade` 通告后收尾。
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from neurova.api.realtime_push import ssePushStream
from neurova.api.ws_stream_budget import (
    MAX_EVENT_BYTES,
    ReplayByteBudget,
    enforceEventCap,
    negotiateCompression,
)


class TestCompressionNegotiation:
    """服务端压缩协商单源：negotiateCompression。"""

    def test_无头走identity不启用压缩(self):
        assert negotiateCompression(None) == {"enabled": False, "encoding": "identity"}
        assert negotiateCompression("") == {"enabled": False, "encoding": "identity"}
        assert negotiateCompression("   ") == {"enabled": False, "encoding": "identity"}

    def test_gzip命中即启用(self):
        assert negotiateCompression("gzip") == {"enabled": True, "encoding": "gzip"}
        assert negotiateCompression("gzip, deflate") == {"enabled": True, "encoding": "gzip"}
        assert negotiateCompression("deflate, gzip") == {"enabled": True, "encoding": "gzip"}

    def test_多候选取服务端首选gzip_不支持则identity(self):
        # 服务端当前只支持 gzip：候选里没有 gzip 就诚实回落 identity
        assert negotiateCompression("br, gzip, zstd") == {"enabled": True, "encoding": "gzip"}
        assert negotiateCompression("deflate, br") == {"enabled": False, "encoding": "identity"}

    def test_q0显式拒绝_通配与大小写(self):
        assert negotiateCompression("gzip;q=0") == {"enabled": False, "encoding": "identity"}
        assert negotiateCompression("gzip;q=0.000, deflate") == {
            "enabled": False,
            "encoding": "identity",
        }
        assert negotiateCompression("*") == {"enabled": True, "encoding": "gzip"}
        assert negotiateCompression("GZIP") == {"enabled": True, "encoding": "gzip"}


class TestEventCap:
    """单事件字节上限：enforceEventCap。"""

    def test_限内事件原样通过(self):
        payload = b'data: {"seq": 1}\n\n'
        ok, honest = enforceEventCap(payload)
        assert ok is True
        assert honest == payload

    def test_超限事件整体替换为诚实占位帧(self):
        big = ('data: {"seq": 1, "blob": "' + "x" * (MAX_EVENT_BYTES + 16) + '"}\n\n').encode(
            "utf-8"
        )
        assert len(big) > MAX_EVENT_BYTES
        ok, honest = enforceEventCap(big)
        assert ok is False
        text = honest.decode("utf-8")  # 必须是完整可解码文本
        assert text.startswith("data: ") and text.endswith("\n\n")
        body = json.loads(text[len("data: "):].strip())  # 绝不半截 JSON
        assert body["event_truncated"] is True
        assert body["original_bytes"] == len(big)
        assert body["cap_bytes"] == MAX_EVENT_BYTES
        assert len(honest) <= MAX_EVENT_BYTES, "占位帧自身必须在上限内"

    def test_自定义上限生效(self):
        ok, honest = enforceEventCap(b"x" * 100, max_bytes=64)
        assert ok is False
        body = json.loads(honest.decode("utf-8"))
        assert body["cap_bytes"] == 64
        assert body["original_bytes"] == 100


class TestReplayByteBudget:
    """重放字节预算：累计、降级标记、重置。"""

    def test_限内累计记账(self):
        budget = ReplayByteBudget(100)
        assert budget.feed(40) is True
        assert budget.feed(40) is True
        assert budget.downgraded is False
        assert budget.fedBytes == 80
        assert budget.remaining() == 20

    def test_累计超预算置降级标记(self):
        budget = ReplayByteBudget(100)
        assert budget.feed(60) is True
        assert budget.feed(60) is False, "破预算的那一笔应被拒（调用方扣下转快照）"
        assert budget.downgraded is True
        assert budget.remaining() == 0
        assert budget.feed(1) is False, "降级后继续拒绝"

    def test_预算可重置(self):
        budget = ReplayByteBudget(50)
        budget.feed(60)
        assert budget.downgraded is True
        budget.reset()
        assert budget.fedBytes == 0
        assert budget.downgraded is False
        assert budget.remaining() == 50
        assert budget.feed(10) is True

    def test_负预算拒绝创建(self):
        with pytest.raises(ValueError):
            ReplayByteBudget(-1)


class _ScriptedFeed:
    """测试用 feed：首屏给定；增量按脚本给；支持首屏读取后注入新帧（与
    test_realtime_push.py 的同构替身，避免跨文件依赖）。"""

    def __init__(self, snapshotFrames=None, terminalTypes=("done",)):
        from neurova.api.realtime_push import FEED_EXHAUSTED

        self._FEED_EXHAUSTED = FEED_EXHAUSTED
        self.snapshotFrames = list(snapshotFrames or [])
        self.laterFrames = []
        self.terminalTypes = set(terminalTypes)
        self.onSnapshotRead = None
        self.exhausted = False

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
                return self._FEED_EXHAUSTED
            if loop.time() >= deadline:
                return None
            await asyncio.sleep(0.005)


def _render(frame):
    """与既有出口相同的对外帧格式。"""
    return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"


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


class TestPushStreamDefaultBehaviorUnchanged:
    """回归钉：不传 byte_budget/event_cap 时，ssePushStream 行为与改前逐字一致。"""

    def test_默认参数首屏与终态输出逐字一致(self):
        feed = _ScriptedFeed(snapshotFrames=[{"seq": 1}, {"seq": 2, "type": "done"}])
        chunks = _collect(ssePushStream(feed=feed, renderFrame=_render))
        assert chunks == ['data: {"seq": 1}\n\n', 'data: {"seq": 2, "type": "done"}\n\n']

    def test_默认参数增量衔接与收尾不变(self):
        feed = _ScriptedFeed(snapshotFrames=[{"seq": 1}])

        def _late():
            feed.laterFrames.append({"seq": 2})
            feed.exhausted = True

        feed.onSnapshotRead = _late
        chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, heartbeatInterval=0.05))
        assert chunks == ['data: {"seq": 1}\n\n', 'data: {"seq": 2}\n\n']

    def test_默认参数心跳注释帧不变(self):
        feed = _ScriptedFeed()
        beats = {"n": 0}

        def _authorize():
            beats["n"] += 1
            if beats["n"] >= 2:
                feed.exhausted = True
            return True

        chunks = _collect(
            ssePushStream(feed=feed, renderFrame=_render, authorize=_authorize, heartbeatInterval=0.05)
        )
        assert chunks == [": keep-alive\n\n"] * 2


class TestPushStreamEventCap:
    """ssePushStream × 单事件上限。"""

    def test_超限帧替换为诚实占位帧_其余帧照常(self):
        feed = _ScriptedFeed(snapshotFrames=[{"seq": 1, "blob": "x" * 500}, {"seq": 2}])
        feed.exhausted = True  # 首屏后即收尾（本用例不验心跳）
        chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, event_cap=128))
        assert len(chunks) == 2
        assert chunks[0].startswith("data: ") and chunks[0].endswith("\n\n")
        body = json.loads(chunks[0][len("data: "):].strip())
        assert body["event_truncated"] is True
        assert body["cap_bytes"] == 128
        assert "blob" not in body, "超限帧的原始负载不得外泄"
        assert json.loads(chunks[1][len("data: "):].strip())["seq"] == 2

    def test_占位帧字节计入预算账面(self):
        budget = ReplayByteBudget(10_000)
        feed = _ScriptedFeed(snapshotFrames=[{"seq": 1, "blob": "x" * 500}])
        feed.exhausted = True  # 首屏后即收尾（本用例不验心跳）
        _collect(ssePushStream(feed=feed, renderFrame=_render, byte_budget=budget, event_cap=128))
        assert budget.fedBytes > 0
        assert budget.downgraded is False


class TestPushStreamBudgetDowngrade:
    """ssePushStream × 累计字节预算：超预算 → 扣下溢出帧、降级通告、收尾。"""

    def test_累计超预算_扣下溢出帧并发降级通告后收尾(self):
        budget = ReplayByteBudget(40)
        feed = _ScriptedFeed(snapshotFrames=[{"seq": 1}, {"seq": 2}, {"seq": 3}])
        chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, byte_budget=budget))
        # 每帧渲染后 18 字节：前两帧共 36 ≤ 40；第三帧会破预算 → 扣下，改发降级通告
        assert chunks[0] == 'data: {"seq": 1}\n\n'
        assert chunks[1] == 'data: {"seq": 2}\n\n'
        assert chunks[2].startswith("event: snapshot_downgrade\ndata: ")
        assert chunks[2].endswith("\n\n")
        notice = json.loads(chunks[2][len("event: snapshot_downgrade\ndata: "):].strip())
        assert notice["reason"] == "replay_byte_budget_exhausted"
        assert notice["last_seq"] == 2, "通告应携带已外发的最大游标"
        assert notice["resume"] == "snapshot"
        assert notice["budget_bytes"] == 40
        assert len(chunks) == 3, "降级后必须收尾，不得再吐任何帧"
        assert budget.downgraded is True

    def test_预算内全部送达不降级(self):
        budget = ReplayByteBudget(4 * 1024)
        feed = _ScriptedFeed(snapshotFrames=[{"seq": 1}, {"seq": 2}])
        feed.exhausted = True  # 首屏后即收尾（本用例不验心跳）
        chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, byte_budget=budget))
        assert chunks == ['data: {"seq": 1}\n\n', 'data: {"seq": 2}\n\n']
        assert budget.downgraded is False

    def test_被扣下的溢出帧也记账在案(self):
        budget = ReplayByteBudget(40)
        feed = _ScriptedFeed(snapshotFrames=[{"seq": 1}, {"seq": 2}, {"seq": 3}])
        _collect(ssePushStream(feed=feed, renderFrame=_render, byte_budget=budget))
        assert budget.fedBytes >= 36, "已外发两帧 + 被扣下的第三帧都应计入账面"

    def test_增量阶段超预算同样降级(self):
        budget = ReplayByteBudget(40)
        feed = _ScriptedFeed(snapshotFrames=[{"seq": 1}])

        def _late():
            feed.laterFrames.append({"seq": 2})
            feed.laterFrames.append({"seq": 3})
            feed.exhausted = True

        feed.onSnapshotRead = _late
        chunks = _collect(ssePushStream(feed=feed, renderFrame=_render, byte_budget=budget, heartbeatInterval=0.05))
        assert chunks[0] == 'data: {"seq": 1}\n\n'
        assert chunks[-1].startswith("event: snapshot_downgrade\ndata: ")
        seqs = [json.loads(c[len("data: "):].strip())["seq"] for c in chunks if c.startswith("data: ")]
        assert seqs == [1, 2], "第三帧破预算被扣下"
