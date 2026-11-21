# -*- coding: utf-8 -*-
"""SSE 推送统一模板：订阅先于读首屏 → 首屏快照 → 增量 → 心跳内权限重验。

推送韧性四件套之一（docs/04-plans/2026-11-20-reference-aa-borrowable-mechanisms-plan.md
项 4）。此前各"通知/状态"类 SSE 出口各自实现"回放 + 实时 + 心跳"，语义漂移且普遍
缺"连接存续期内的权限重验"。本模板统一四件事：

1. **订阅先于读首屏**：feed（订阅）先建立，再读首屏快照；快照与增量之间用游标
   （frameKey）衔接——快照里已有的帧不重发，快照之后到达的帧经增量必达（不漏）。
2. **首屏快照**：连接建立即回放当前累计帧，客户端不必盲等增量。
3. **增量**：`feed.nextFrame(afterKey, timeout)` 拉取游标之后的下一帧；
   返回 None 表示本轮超时（走心跳），返回 `FEED_EXHAUSTED` 表示增量源已永久关闭
   （收尾）。`afterKey=None` 表示"从 feed 当前游标起"，不回到流开头。
4. **心跳内权限重验**：每个心跳周期先过 `authorize()` 钩子，不过即在当前心跳内
   收尾——权限过期的连接最迟一个心跳内被服务端摘除（对齐 Linger voice SSE）。

对外帧格式由端点经 `renderFrame` 保持（既有出口为数据帧 `data: {json}\n\n`、
心跳 `: keep-alive\n\n` 注释行），模板不改动帧格式。console.py / chat.py 的
chat 回合流不在本模板范围（回合流非通知流）。

字节治理（单事件上限 + 重放字节预算，可选项）见 `ssePushStream` 的
`event_cap` / `byte_budget` 参数说明；协商与预算原语在
`neurova/api/ws_stream_budget.py`，续传决策在 `neurova/api/subscription_resume.py`。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Callable, List, Optional, Tuple

from neurova.api.ws_stream_budget import ReplayByteBudget, enforceEventCap

#: 增量源永久关闭的哨兵（区别于"本轮心跳超时"的 None）
FEED_EXHAUSTED = object()


class PollingSnapshotFeed:
    """快照 + 轮询增量型事件源的通用 feed 适配。

    适配"帧落在一个可重复读取的缓冲里"的源（如 ExecutionEventRecorder）：
    - `snapshotFn(afterKey)`：返回游标之后（key 严格大于 afterKey）的帧，时间序；
      afterKey 为 None 时从源当前起点给出全部可用帧。
    - `keyFn(frame)`：取单调递增游标。
    - `isTerminalFn(frame)`：终态帧判定（订阅在这些帧后收尾）。
    - `closedFn()`：增量源是否已永久关闭（如缓冲被逐出）；空且关闭即收尾。
    - `initialCursor`：断线重连续传游标（快照从它之后回放）。
    """

    def __init__(
        self,
        snapshotFn: Callable[[Optional[Any]], List[Any]],
        keyFn: Callable[[Any], Any],
        isTerminalFn: Optional[Callable[[Any], bool]] = None,
        closedFn: Optional[Callable[[], bool]] = None,
        pollInterval: float = 0.05,
        initialCursor: Any = None,
    ):
        self._snapshotFn = snapshotFn
        self._keyFn = keyFn
        self._isTerminalFn = isTerminalFn or (lambda frame: False)
        self._closedFn = closedFn
        self._pollInterval = pollInterval
        self._cursor = initialCursor

    def snapshot(self) -> List[Any]:
        """首屏快照：当前游标之后的全部累计帧（读取即推进内部游标）。"""
        frames = list(self._snapshotFn(self._cursor))
        if frames:
            self._cursor = self._keyFn(frames[-1])
        return frames

    def frameKey(self, frame: Any) -> Any:
        return self._keyFn(frame)

    def isTerminal(self, frame: Any) -> bool:
        return self._isTerminalFn(frame)

    async def nextFrame(self, afterKey: Optional[Any], timeout: float) -> Any:
        """轮询拉取游标之后的下一帧；超时返回 None，源永久关闭返回 FEED_EXHAUSTED。

        `afterKey=None` 语义是"从 feed 当前游标起"（衔接首屏快照的尾游标），
        不回到流开头——断线重连的游标由 initialCursor 承担。
        """
        cursor = self._cursor if afterKey is None else afterKey
        deadline = time.monotonic() + max(timeout, 0.0)
        while True:
            frames = list(self._snapshotFn(cursor))
            if frames:
                self._cursor = self._keyFn(frames[-1])
                return frames[0]
            if self._closedFn is not None and self._closedFn():
                return FEED_EXHAUSTED
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(self._pollInterval)


async def ssePushStream(
    *,
    feed: Any,
    renderFrame: Callable[[Any], str],
    authorize: Optional[Callable[[], bool]] = None,
    heartbeatInterval: float = 15.0,
    maxFrames: Optional[int] = None,
    byte_budget: Optional[ReplayByteBudget] = None,
    event_cap: Optional[int] = None,
) -> AsyncIterator[str]:
    """统一 SSE 生成器。

    时序：feed 建立（订阅）先于 snapshot()（读首屏）——这是"订阅先于读首屏"的
    落点；快照尾游标交给 nextFrame 做增量，衔接处不漏不重。maxFrames 为测试钩子
    （发满即收尾；生产不传 = 无限流）。

    字节治理（E3，可选；**不传这两个参数时行为与既有出口逐字一致**）：

    - ``event_cap``：单帧字节上限（建议用 ``ws_stream_budget.MAX_EVENT_BYTES``）。
      每帧渲染后按 UTF-8 编码字节数判定，超限帧**整体替换**为诚实占位帧
      ``data: {"event_truncated": true, "reason": "event_bytes_exceed_cap",
      "original_bytes": N, "cap_bytes": C}\\n\\n``（绝不产出半截 JSON），占位帧
      字节同样计入预算账面。
    - ``byte_budget``：:class:`~neurova.api.ws_stream_budget.ReplayByteBudget`，
      对本流外发的每个数据帧（首屏快照 + 增量 + 占位帧）按编码字节数记账。
      某帧记账后突破预算 → 该帧**扣下不发**，改发一帧降级通告后本流收尾：

      ``event: snapshot_downgrade\\ndata: {"reason": "replay_byte_budget_exhausted",
      "last_seq": <已外发最大游标>, "fed_bytes": N, "budget_bytes": M,
      "resume": "snapshot"}\\n\\n``

      客户端语义：收到 ``snapshot_downgrade`` 即丢弃本地增量游标，按
      ``subscription_resume.reconnectBackoff`` 的退避语义重连，以首屏快照恢复
      （与全局事件库 ``replayThrough`` 的 degraded → 快照降级协议同构）。
      心跳注释帧（``: keep-alive``）不记账。
    """
    sent = 0
    lastKey: Optional[Any] = None

    def _prepare(frame: Any) -> Tuple[Optional[str], bool]:
        """渲染 + 单事件上限 + 字节记账。返回 (外发帧, 是否触发降级)。

        外发帧为 None 表示该帧被预算扣下（未外发，客户端转快照恢复）。
        两个治理参数都未传时走原路径：渲染结果原样返回，零额外行为。
        """
        rendered = renderFrame(frame)
        if event_cap is None and byte_budget is None:
            return rendered, False
        encoded = rendered.encode("utf-8")
        if event_cap is not None:
            ok, honest = enforceEventCap(encoded, max_bytes=event_cap)
            if not ok:
                rendered = honest.decode("utf-8")
                encoded = honest
        if byte_budget is not None and not byte_budget.feed(len(encoded)):
            return None, True
        return rendered, False

    def _downgradeNotice(cursor: Optional[Any]) -> str:
        payload = json.dumps(
            {
                "reason": "replay_byte_budget_exhausted",
                "last_seq": cursor,
                "fed_bytes": byte_budget.fedBytes,
                "budget_bytes": byte_budget.maxBytes,
                "resume": "snapshot",
            },
            ensure_ascii=False,
        )
        return f"event: snapshot_downgrade\ndata: {payload}\n\n"

    for frame in feed.snapshot():                       # ② 首屏快照（① 订阅已先建立）
        rendered, downgrade = _prepare(frame)
        if downgrade:
            yield _downgradeNotice(lastKey)  # lastKey = 已外发的最大游标（被扣下的帧不计入）
            return
        lastKey = feed.frameKey(frame)
        sent += 1
        yield rendered
        if feed.isTerminal(frame):
            return
        if maxFrames is not None and sent >= maxFrames:
            return
    while maxFrames is None or sent < maxFrames:        # ③ 增量
        frame = await feed.nextFrame(lastKey, timeout=heartbeatInterval)
        if frame is FEED_EXHAUSTED:
            return
        if frame is None:                               # 心跳超时
            if authorize is not None and not authorize():  # ④ 心跳内权限重验
                return
            yield ": keep-alive\n\n"
            continue
        rendered, downgrade = _prepare(frame)
        if downgrade:
            yield _downgradeNotice(lastKey)  # lastKey = 已外发的最大游标（被扣下的帧不计入）
            return
        lastKey = feed.frameKey(frame)
        sent += 1
        yield rendered
        if feed.isTerminal(frame):
            return
