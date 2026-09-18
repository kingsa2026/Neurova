# -*- coding: utf-8 -*-
"""RSI 迭代结果摘要 —— 响应面/推送面的单一事实源。

为什么需要这层收口：

- ``RSIOrchestrator.run_iteration()`` 返回的是完整迭代快照
  （feedback_signals / optimizations / applied_results / metrics ...），
  体积大、且不适合进对话响应。
- PostChatPipeline 的 RSI 步骤已后台化（Issue #55 P0 尾延迟），原始 dict
  不再随响应回传。
- 但"上一轮 RSI 迭代到底做了什么"仍是调用方要的观测面（负一屏推送、
  运营面板）。此前 ``process()["rsi_result"]`` 恒为 None，而
  ``NegativeScreenPusher.push_rsi_result`` 读的是
  ``iteration/improvements/convergence_score/status``——与 orchestrator 真实
  输出（``convergence/applied_count/gain/phase_advanced``）名字全不匹配，
  且 ``convergence`` 是 dict（``dict * 100`` 直接 TypeError）：一旦接线即报错。

本模块只做两件事，字段名一律对齐 orchestrator 真实输出：

1. :func:`summarize_rsi_result` —— raw dict → 响应面摘要（四个字段）。
2. :func:`record_rsi_summary` / :func:`get_latest_rsi_summary` —— 按
   (agent, session) 记录**最近一次已完成**的迭代摘要。

关于"最近一次"而不是"本轮"：RSI 在后台 task 里跑，响应构建时本轮结果通常还
没产出。所以响应里给的是最近一次已完成摘要（``turn`` 标明归属轮次、
``stale`` 标明是否非本轮），而不是阻塞等待（会把尾延迟加回来）或编造数据。

存储是**进程内**的（有界表，插入序淘汰）：重启后到下一次 RSI 迭代前摘要为空。
观测字段只回答"最近一轮 RSI 做了什么"，不承担持久化职责。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, Dict, Optional, Tuple

# 响应面摘要的字段集合（唯一契约，测试与推送面都引用它）
RSI_SUMMARY_FIELDS: Tuple[str, ...] = ("status", "applied_count", "gain", "phase_advanced")

_UNKNOWN_STATUS = "unknown"

# 会话级摘要表的有界上限：只保最近 N 个 (agent, session)，防长进程无界增长
_MAX_TRACKED_SESSIONS = 1024

_summaries: "OrderedDict[Tuple[str, str], Dict[str, Any]]" = OrderedDict()
_lock = threading.RLock()


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def convergence_status(result: Mapping[str, Any]) -> str:
    """从迭代结果里取收敛状态。

    ``run_iteration()`` 的 ``convergence`` 是 dict（``{"status": ...}``）；
    历史/其它调用方也可能给扁平 ``status``/``convergence_status``。三者兼容，
    取不到时返回 ``"unknown"``——绝不拿 dict 当数字用。
    """
    convergence = result.get("convergence")
    status = convergence.get("status") if isinstance(convergence, Mapping) else None
    if not status:
        status = result.get("status") or result.get("convergence_status")
    return str(status) if status else _UNKNOWN_STATUS


def summarize_rsi_result(result: Any) -> Optional[Dict[str, Any]]:
    """把 RSI 迭代结果压成响应面摘要（字段名对齐 orchestrator 真实输出）。

    形态不符（None / 非 Mapping / 空 dict）时返回 None，不造默认值——
    不存在的迭代不该冒充"跑了一轮没优化"。
    """
    if not isinstance(result, Mapping) or not result:
        return None
    return {
        "status": convergence_status(result),
        "applied_count": _as_int(result.get("applied_count", 0)),
        "gain": _as_float(result.get("gain", 0.0)),
        "phase_advanced": bool(result.get("phase_advanced", False)),
    }


def _key(agent_id: Any, session_id: Any) -> Tuple[str, str]:
    return (str(agent_id or "default"), str(session_id or "default"))


def record_rsi_summary(
    agent_id: Any,
    session_id: Any,
    result: Any,
    turn: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """记录一次已完成 RSI 迭代的摘要（result 为 run_iteration 原始返回）。

    Returns:
        落库的摘要（含 ``turn``）；形态不符时返回 None 且不写入。
    """
    summary = summarize_rsi_result(result)
    if summary is None:
        return None

    key = _key(agent_id, session_id)
    with _lock:
        if key not in _summaries and len(_summaries) >= _MAX_TRACKED_SESSIONS:
            # 插入序淘汰最旧一半（dict 保序）——与 turn_context 的会话表同策略
            for stale in list(_summaries)[: _MAX_TRACKED_SESSIONS // 2]:
                _summaries.pop(stale, None)
        _summaries[key] = {"summary": summary, "turn": _as_int(turn) if turn is not None else None}
        return dict(_summaries[key])


def get_latest_rsi_summary(
    agent_id: Any,
    session_id: Any,
    current_turn: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """取该会话最近一次已完成的 RSI 摘要（从未有过迭代时返回 None）。

    ``current_turn`` 给出时附带 ``stale`` 标记：True 表示该摘要不是本轮的
    （RSI 仍在后台，或本轮 RSI 被跳过）。判不出轮次时不虚报。
    """
    with _lock:
        record = _summaries.get(_key(agent_id, session_id))
        if record is None:
            return None
        record = dict(record)

    payload = dict(record["summary"])
    payload["turn"] = record.get("turn")
    recorded_turn = record.get("turn")
    payload["stale"] = bool(
        current_turn is not None and recorded_turn is not None and recorded_turn != current_turn
    )
    return payload


def clear_rsi_summaries() -> None:
    """清空摘要表（测试/setup-teardown 用）。"""
    with _lock:
        _summaries.clear()


__all__ = [
    "RSI_SUMMARY_FIELDS",
    "convergence_status",
    "summarize_rsi_result",
    "record_rsi_summary",
    "get_latest_rsi_summary",
    "clear_rsi_summaries",
]
