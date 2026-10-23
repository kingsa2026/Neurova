"""TurnOutcome 分类：只吃硬信号，不做文本猜测。"""
from __future__ import annotations

from typing import Optional

TURN_OUTCOMES = (
    "answered",
    "safety_refusal",
    "insufficient_evidence",
    "tool_failure",
    "handoff",
    "unknown",
)

EXPERIMENTAL_OUTCOMES = frozenset({"insufficient_evidence"})
_ANSWER_FINISHES = frozenset({"stop", "end_turn"})


def classifyTurnOutcome(
    finishReason: Optional[str],
    retrievalHits: Optional[int] = None,
    retrievalQuality: Optional[float] = None,
    explicitOutcome: Optional[str] = None,
) -> str:
    """按完成态与检索 gate 分类；显式 metadata 优先，无法确定时 unknown。

    content_filter 是安全拒答的硬信号；无检索命中且质量低于 0.3 记为
    insufficient_evidence（实验口径）；其余 stop/end_turn 记 answered。
    tool_failure/handoff 只接受显式 metadata，不按工具消息或文本猜。
    """
    explicit = str(explicitOutcome or "").strip().lower()
    if explicit in TURN_OUTCOMES:
        return explicit
    finish = str(finishReason or "").strip().lower()
    if finish == "content_filter":
        return "safety_refusal"
    if retrievalHits is not None:
        try:
            hits = int(retrievalHits)
        except (TypeError, ValueError):
            hits = None
        if hits is not None and hits <= 0:
            quality = 1.0 if retrievalQuality is None else float(retrievalQuality)
            if quality < 0.3:
                return "insufficient_evidence"
    if finish in _ANSWER_FINISHES:
        return "answered"
    return "unknown"
