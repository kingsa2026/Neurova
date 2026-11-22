# -*- coding: utf-8 -*-
"""压缩生命周期钩子事件化（P2-8）。

窗口压缩（`neurova.context.window_compactor.compact_window`）的生命周期经
**统一事件总线**（`neurova.core.event_bus.get_event_bus`）对外发布
before / after / error 三类进程内钩子事件，供观测与元认知回路订阅消费。

与既有落盘面的分工（两者并存、互不替代）：
- `neurova.context_pool.persistCompressionEvent`：压缩事件写会话时间线
  （append-only 持久化链路）；
- 本模块：进程内可订阅钩子（实时观测面），不落盘、不重复时间线语义。

单一事实源（修复教义第 6 条）：事件名常量与发射逻辑**只在本模块定义**；
消费方（含测试与后续编排层接线）一律引用这里的常量，不得另造同义或
异名事件。发布一律 fail-open——总线故障只告警，绝不打断压缩主链路。
"""

import typing
from datetime import datetime

from neurova.core.event_bus import get_event_bus
from neurova.core.logger import get_logger

if typing.TYPE_CHECKING:  # 仅供类型标注；运行时不 import，避免与 window_compactor 成环
    from neurova.context.window_compactor import WindowCompaction

logger = get_logger(__name__)

#: 折叠开始前（窗口确已超预算、即将进入折叠）。
COMPACT_BEFORE = "context.compaction.before"
#: 折叠完成后（产出有效 WindowCompaction 结果，含零折叠的物理无解尽力结果）。
COMPACT_AFTER = "context.compaction.after"
#: 压缩内部异常（phase 标明出错环节，当前为 "summarize"）。
COMPACT_ERROR = "context.compaction.error"


def _nowIso() -> str:
    """事件时间戳（ISO 字符串，与时间线落盘口径一致）。"""
    return datetime.now().isoformat()


def _publish(eventName: str, data: typing.Dict[str, typing.Any], source: str) -> list:
    """经统一总线同步发布；总线异常只告警不打断压缩主链路（fail-open）。

    订阅者自身异常由总线隔离（`EventBus.publish` 逐订阅者捕获）；
    这里再兜一层总线级异常（总线覆写/过滤链路故障等），双保险同纪律。
    """
    try:
        return get_event_bus().publish(eventName, data=data, source=source)
    except Exception as e:  # noqa: BLE001 - 事件是增强面，失败不阻断压缩
        logger.warning("压缩生命周期事件发布失败（忽略）: event=%s err=%s", eventName, e)
        return []


def emitCompactionBefore(
    sessionKey: str, msgsCount: int, budgetTokens: int, source: str = ""
) -> list:
    """折叠开始前发布：宣告一次真实压缩尝试（窗口确已超预算）。

    负载字段：ts / sessionKey / phase="before" / msgsCount / budgetTokens / source。
    """
    return _publish(COMPACT_BEFORE, {
        "ts": _nowIso(),
        "sessionKey": sessionKey,
        "phase": "before",
        "msgsCount": int(msgsCount),
        "budgetTokens": int(budgetTokens),
        "source": source,
    }, source)


def emitCompactionAfter(
    sessionKey: str,
    compaction: typing.Optional["WindowCompaction"],
    source: str = "",
) -> list:
    """折叠完成后发布：携带折叠结果读数（手动取字段，不整包 asdict——
    window 消息体可能很大，钩子负载只带读数不带全量消息）。

    `compaction` 为 None 时不发布（调用方仅在产出有效结果时调用；
    None 即"没有压缩结果"，发 after 反而制造误导性事件）。
    """
    if compaction is None:
        return []
    return _publish(COMPACT_AFTER, {
        "ts": _nowIso(),
        "sessionKey": sessionKey,
        "phase": "after",
        "compactedCount": int(compaction.compacted_count),
        "tokensBefore": int(compaction.tokens_before),
        "tokensAfter": int(compaction.tokens_after),
        "summaryIsFresh": bool(compaction.summary_is_fresh),
        "hasSummary": bool(compaction.summary),
        "windowSize": len(compaction.window),
        "source": source,
    }, source)


def emitCompactionError(
    sessionKey: str, error: typing.Optional[Exception], phase: str, source: str = ""
) -> list:
    """压缩内部异常发布（当前 phase="summarize"，即摘要调用失败）。

    负载字段：ts / sessionKey / phase / errorType / errorMessage / source。
    """
    return _publish(COMPACT_ERROR, {
        "ts": _nowIso(),
        "sessionKey": sessionKey,
        "phase": str(phase or ""),
        "errorType": type(error).__name__ if error is not None else "",
        "errorMessage": str(error) if error is not None else "",
        "source": source,
    }, source)
