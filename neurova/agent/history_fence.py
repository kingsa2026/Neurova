"""HistoryWriteFence — 会话历史写入围栏（P1-10，OpenClaw 启发）

参照 OpenClaw `expectedWriterRunId` 事务内双重断言：并行会话/旧 run 恢复后
可能写脏历史。围栏语义：

- 每个 (agent_id, session_id) 维护当前 writer 与单调递增 generation；
- 新 run 调 claim() 接管会话（同 writer 重入不换代，异 writer 夺权换代+1）；
- 旧 run 持有的 claim 在写前 check() 失败 → 写入被拒绝（跳过，不抛异常），
  「被夺权的 run 永远写不进陈旧数据」。

纪律（增量实施约束）：显式参与式围栏——不传 writer_claim 的调用方行为
完全不变；围栏只拦截「明确参与且已失效」的写入，绝不扩大打击面。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class FenceClaim:
    """一次 claim 颁发的权属凭证：(writer_id, generation) 二元组。

    writer_id 由调用方命名（如 "run:<trace_id>"）；generation 由围栏颁发，
    夺权时递增。check 只认「当前 writer + 当前 generation」。
    """

    writer_id: str
    generation: int


class HistoryWriteFence:
    """RLock 保护的会话写入围栏。纯内存，无持久化状态。"""

    def __init__(self):
        self._lock = threading.RLock()
        # (agent_id, session_id) -> (writer_id, generation)
        self._owners: Dict[Tuple[str, str], Tuple[str, int]] = {}
        self._fenced_writes = 0

    def claim(self, agent_id: str, session_id: str, writer_id: str) -> FenceClaim:
        """接管/刷新会话写入权。同 writer 重入保持代数；异 writer 夺权换代。"""
        key = (agent_id or "default", session_id or "default")
        with self._lock:
            current = self._owners.get(key)
            if current is not None and current[0] == writer_id:
                generation = current[1]
            else:
                generation = (current[1] + 1) if current is not None else 1
                if current is not None:
                    logger.info(
                        "会话围栏夺权: agent=%s session=%s %s(gen%s) -> %s(gen%s)",
                        agent_id, session_id, current[0], current[1], writer_id, generation,
                    )
            self._owners[key] = (writer_id, generation)
            return FenceClaim(writer_id=writer_id, generation=generation)

    def check(self, agent_id: Optional[str], session_id: Optional[str], claim: Optional[FenceClaim]) -> bool:
        """写前断言：claim 仍是当前权属才放行。None claim 一律拒绝。"""
        if claim is None:
            return False
        key = (agent_id or "default", session_id or "default")
        with self._lock:
            current = self._owners.get(key)
            return current is not None and current == (claim.writer_id, claim.generation)

    @property
    def fenced_writes(self) -> int:
        """被围栏拒绝的写入次数（可观测性）"""
        return self._fenced_writes

    def record_fenced_write(self) -> None:
        with self._lock:
            self._fenced_writes += 1

    def release(self, agent_id: str, session_id: str, writer_id: str) -> None:
        """主动放弃写入权（测试/优雅退出用；OC 语义不强制释放）。"""
        key = (agent_id or "default", session_id or "default")
        with self._lock:
            current = self._owners.get(key)
            if current is not None and current[0] == writer_id:
                del self._owners[key]


_fence_singleton: Optional[HistoryWriteFence] = None
_fence_lock = threading.Lock()


def get_history_write_fence() -> HistoryWriteFence:
    """进程级共享围栏单例（ChatPipeline 与各写入咽喉共用）"""
    global _fence_singleton
    if _fence_singleton is None:
        with _fence_lock:
            if _fence_singleton is None:
                _fence_singleton = HistoryWriteFence()
    return _fence_singleton


def reset_history_write_fence() -> None:
    """测试隔离用：重置单例"""
    global _fence_singleton
    with _fence_lock:
        _fence_singleton = None
