"""执行事件录制器 — P0-1 工作流执行流式化的"录制+订阅"传动轴。

机制已有缺传动轴（增量实施约束）：引擎 WorkflowExecutor 早已有 _emit/on_event
事件总线，本模块不新造事件源，只做三件事：
1. record()：把引擎事件同步写入 per-execution 环形缓冲（有界，防长工作流爆内存）
2. snapshot(execution_id, after)：按序取帧（seq 单调自增），支持游标续传
3. subscribe()：async generator——先回放历史帧，再实时推送，终态帧后自然收尾
   （run/stream 分离：执行方发 ID，订阅方随时接入、随时断开重连）

线程安全：record 可能被调度器等非事件循环线程调用——结构变更走 threading.Lock；
subscribe 用轻量轮询拉取（无跨线程 loop 唤醒复杂度，50ms 粒度对画布着色足够）。

attach_event_recorder(executor)：显式装配点（幂等）——把转发 handler 挂上引擎
事件总线；转发到全局单例，reset 后自动指向新实例（handler 不绑定具体实例）。
"""

import asyncio
import itertools
import threading
import time
from collections import OrderedDict, deque
from typing import Any, AsyncIterator, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 单个执行最多保留的事件帧数（环形丢弃最旧；含全部节点事件的长工作流）
EVENTS_PER_EXECUTION = 500
# 最多追踪的执行数（LRU 逐出最久未更新的执行缓冲）
MAX_TRACKED_EXECUTIONS = 200

# 终态事件类型（订阅在这些帧后收尾）；引擎 cancel 发的是 workflow_failed
_TERMINAL_TYPES = frozenset({"workflow_completed", "workflow_failed", "workflow_cancelled"})

# 挂到引擎 handler 上的哨兵属性名（attach 幂等判定）
_HANDLER_SENTINEL = "_neurflow_event_recorder_handler"


def _json_safe(value: Any) -> Any:
    """事件 data 兜底可 JSON 化（SSE 帧要求）；与 SessionEvent._json_safe 同思路。"""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


class ExecutionEventRecorder:
    """per-execution 事件环形缓冲 + 回放/实时订阅。"""

    def __init__(self):
        self._lock = threading.Lock()
        # execution_id -> OrderedDict[seq -> frame]（插入有序；LRU 驱逐按访问/写入）
        self._buffers: "OrderedDict[str, 'OrderedDict[int, dict]']" = OrderedDict()
        self._seq = itertools.count(1)

    # ── 写入（任意线程） ──────────────────────────────────────────

    def record(self, event: Any) -> Optional[dict]:
        """把一条引擎 ExecutionEvent 归一为帧并入缓冲；返回该帧（便于调试）。

        幂等语义不在此处——重复 record 同一事件会成两帧；去重靠 attach 幂等。
        """
        execution_id = getattr(event, "execution_id", "") or ""
        if not execution_id:
            return None
        etype = getattr(event, "type", "")
        etype = etype.value if hasattr(etype, "value") else str(etype)
        frame = {
            "seq": next(self._seq),
            "type": etype,
            "workflow_id": getattr(event, "workflow_id", ""),
            "execution_id": execution_id,
            "node_id": getattr(event, "node_id", None),
            "data": _json_safe(getattr(event, "data", {}) or {}),
            "timestamp": getattr(event, "timestamp", None) or time.time(),
        }
        with self._lock:
            buf = self._buffers.get(execution_id)
            if buf is None:
                buf = OrderedDict()
                self._buffers[execution_id] = buf
                self._evict_overflow_locked()
            else:
                # 触碰 LRU 顺序
                self._buffers.move_to_end(execution_id)
            buf[frame["seq"]] = frame
            while len(buf) > EVENTS_PER_EXECUTION:
                buf.popitem(last=False)
        return frame

    def _evict_overflow_locked(self) -> None:
        while len(self._buffers) > MAX_TRACKED_EXECUTIONS:
            self._buffers.popitem(last=False)

    # ── 读取 ─────────────────────────────────────────────────────

    def snapshot(self, execution_id: str, after: int = 0) -> List[dict]:
        """返回 seq > after 的帧（时间序）。未知执行返回 []。"""
        with self._lock:
            buf = self._buffers.get(execution_id)
            if buf is None:
                return []
            self._buffers.move_to_end(execution_id)
            return [dict(f) for f in buf.values() if f["seq"] > after]

    def is_tracked(self, execution_id: str) -> bool:
        with self._lock:
            return execution_id in self._buffers

    def has_terminal(self, execution_id: str) -> bool:
        """缓冲中是否已出现终态帧。"""
        with self._lock:
            buf = self._buffers.get(execution_id)
            if not buf:
                return False
            return any(f["type"] in _TERMINAL_TYPES for f in buf.values())

    # ── 订阅（async） ────────────────────────────────────────────

    async def subscribe(
        self, execution_id: str, after: int = 0, poll_interval: float = 0.05
    ) -> AsyncIterator[dict]:
        """回放历史帧 + 实时推送，终态帧后收尾。未知执行 → 空流（不阻塞）。

        轻量轮询拉取：结构变更在锁内 snapshot，等待在锁外 sleep——
        跨线程 record 无需 loop 唤醒，也不长期占锁。
        """
        cursor = after
        while True:
            frames = self.snapshot(execution_id, after=cursor)
            for frame in frames:
                cursor = frame["seq"]
                yield frame
                if frame["type"] in _TERMINAL_TYPES:
                    return
            if not self.is_tracked(execution_id) and cursor == after:
                # 从未追踪（且无历史可回放）：立即结束，由调用方决定降级
                return
            await asyncio.sleep(poll_interval)


# ── 全局单例与装配 ──────────────────────────────────────────────

_recorder: Optional[ExecutionEventRecorder] = None


def get_execution_event_recorder() -> ExecutionEventRecorder:
    global _recorder
    if _recorder is None:
        _recorder = ExecutionEventRecorder()
    return _recorder


def reset_execution_event_recorder() -> None:
    global _recorder
    _recorder = None


def attach_event_recorder(executor: Any) -> None:
    """把转发 handler 挂上执行器事件总线（幂等；转发到全局单例）。"""

    def _forwarding_handler(event: Any) -> None:
        get_execution_event_recorder().record(event)

    setattr(_forwarding_handler, _HANDLER_SENTINEL, True)
    handlers = getattr(executor, "_event_handlers", None)
    if handlers is None:
        return
    for h in handlers:
        if callable(h) and getattr(h, _HANDLER_SENTINEL, False):
            return  # 已挂载，幂等跳过
    handlers.append(_forwarding_handler)
    logger.debug("event recorder attached to executor")
