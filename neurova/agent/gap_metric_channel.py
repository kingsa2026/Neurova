"""能力缺口指标的"写 → 读"接线（单源）。

写侧由 `capability_gap` 的缺口判定触发，读侧由 RSI 状态面取走。
为什么单独成模块而不是塞进 `capability_gap`：`evolution/rsi/metrics` 的
导入链会经 `evolution/__init__` 拉进 agent 包（历史上造成过循环依赖），
故计数器本体独立，两侧都只 import 本模块。

计数落进程内字典而非 Prometheus Gauge：这里的语义是"本轮命中了几类缺口",
是**事件读数**（可累加），Prometheus 侧的 Counter 由 `core/metrics`
在同一次写入里同步递增，两处口径由 `_syncPrometheus` 一处对齐。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_LOCK = threading.RLock()
_COUNTS: Dict[str, int] = {}


def bumpGapMetric(kinds: List[str]) -> None:
    """按类别累加缺口命中数，并同步 Prometheus 计数。"""
    with _LOCK:
        for kind in kinds:
            _COUNTS[kind] = _COUNTS.get(kind, 0) + 1
    _syncPrometheus(kinds)


def readGapMetrics() -> Dict[str, Any]:
    """读侧：各类别累计命中数与总和（无命中时total为 0，不是缺席）。"""
    with _LOCK:
        snapshot = dict(_COUNTS)
    return {"by_kind": snapshot, "total": sum(snapshot.values())}


def _syncPrometheus(kinds: List[str]) -> None:
    """同步进 `core/metrics` 的既有指标面（失败即记日志，不阻断主链）。"""
    try:
        from neurova.core.metrics import observe_capability_gap

        observe_capability_gap(list(kinds))
    except Exception:  # noqa: BLE001
        logger.debug("能力缺口 Prometheus 计数同步失败（忽略）", exc_info=True)


def resetGapMetrics() -> None:
    """清空计数（仅测试与进程重置使用）。"""
    with _LOCK:
        _COUNTS.clear()
