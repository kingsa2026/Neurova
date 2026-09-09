"""对话窗口 token 预算压缩（zcode 式自动 compact）

2026-09-09 kai 空回复事故排查副产物：ContextPool 是归档+语义召回（不裁剪），
get_recent_context 是固定 20 条消息数窗口——两者都不约束 prompt 大小。
本模块提供纯逻辑的窗口预算切分与折叠装配，供 ContextOrchestrator 在
build_context 中做「尾部保留 + 老消息折叠」的自动压缩。
"""

import typing
from dataclasses import dataclass

# 每条消息的协议开销（role/分隔符等的保守估计）
_PER_MSG_OVERHEAD = 4


def estimate_window_tokens(msgs: typing.Iterable) -> int:
    """估算窗口消息序列的 token 总量（统一估算器 BALANCED 策略）。"""
    from neurova.context.token_estimator import estimate_tokens

    total = 0
    for m in msgs or []:
        content = (m or {}).get("content", "") if isinstance(m, dict) else str(m)
        total += estimate_tokens(content) + _PER_MSG_OVERHEAD
    return total


def split_window_by_budget(
    msgs: typing.List[dict],
    budget_tokens: int,
    keep_min_messages: int = 6,
    target_ratio: float = 0.5,
) -> typing.Tuple[typing.List[dict], typing.List[dict]]:
    """按 token 预算把窗口切成 (dropped, kept)。

    - 未超预算：([], 全部)
    - 超预算：从尾部保留至 target=budget×target_ratio（至少 keep_min_messages
      条，保证单条巨消息不会把窗口清空），其余折叠。
    kept 是 msgs 的尾部切片、dropped 是头部切片，时序不打乱。
    """
    msgs = list(msgs or [])
    if not msgs:
        return [], []
    if estimate_window_tokens(msgs) <= budget_tokens:
        return [], msgs

    target = max(budget_tokens * target_ratio, 1.0)
    acc = 0.0
    kept_count = 0
    for m in reversed(msgs):
        t = estimate_window_tokens([m])
        if kept_count >= keep_min_messages and acc + t > target:
            break
        acc += t
        kept_count += 1

    kept_count = min(kept_count, len(msgs))
    kept = msgs[len(msgs) - kept_count:] if kept_count else []
    dropped = msgs[: len(msgs) - kept_count] if kept_count < len(msgs) else []
    return dropped, kept


@dataclass
class WindowCompaction:
    """一次窗口折叠的结果。"""

    window: typing.List[dict]  # 折叠后窗口（摘要行在前，若有）
    summary: typing.Optional[str]  # LLM 摘要（无摘要器/失败时 None）
    compacted_count: int  # 被折叠的消息条数
    tokens_before: int
    tokens_after: int


async def compact_window(
    conversation_context: typing.Optional[typing.List[dict]],
    budget_tokens: int,
    summarize: typing.Optional[typing.Callable] = None,
    previous_summary: str = "",
    keep_min_messages: int = 6,
    target_ratio: float = 0.5,
    summary_prefix: str = "[早期对话摘要] ",
) -> typing.Optional[WindowCompaction]:
    """超预算时折叠窗口老消息；未超预算返回 None（零行为变化）。

    递进折叠（Letta compaction 对齐，2026-09-10）：折叠目标从
    target_ratio 起步，若折叠后窗口仍超预算则按 0.1 步进扩大折叠
    比例重试，直至放下或已折叠到 keep_min_messages 下限——避免
    一次激进摘要丢信息（最小摘要原则）。

    summarize: async (dropped_msgs, previous_summary) -> Optional[str]
    """
    msgs = [
        {"role": (m or {}).get("role", "user"), "content": (m or {}).get("content", "")}
        for m in (conversation_context or [])
        if isinstance(m, dict) and (m or {}).get("content")
    ]
    if not msgs:
        return None

    summary = None
    ratio = target_ratio
    best: typing.Optional[WindowCompaction] = None

    while True:
        dropped, kept = split_window_by_budget(
            msgs, budget_tokens, keep_min_messages, target_ratio=ratio
        )
        if not dropped:
            # 无可折叠（keep_min 下限本身超预算等物理无解）：返回保留态的
            # 尽力结果（零折叠、带说明性摘要行），不静默丢弃折叠机会
            if best is None and estimate_window_tokens(msgs) > budget_tokens:
                best = WindowCompaction(
                    window=list(msgs),
                    summary=None,
                    compacted_count=0,
                    tokens_before=estimate_window_tokens(msgs),
                    tokens_after=estimate_window_tokens(msgs),
                )
            break

        round_summary = None
        if summarize is not None:
            try:
                round_summary = await summarize(dropped, previous_summary)
            except Exception:  # noqa: BLE001 - 摘要失败不阻断上下文构建
                round_summary = None
            if isinstance(round_summary, str) and not round_summary.strip():
                round_summary = None

        window: typing.List[dict] = []
        if round_summary:
            window.append({"role": "system", "content": f"{summary_prefix}{round_summary}"})
        window.extend(kept)

        best = WindowCompaction(
            window=window,
            summary=round_summary,
            compacted_count=len(dropped),
            tokens_before=estimate_window_tokens(msgs),
            tokens_after=estimate_window_tokens(window),
        )
        summary = round_summary or summary

        # 递进：折叠后仍超预算且还有可折叠空间 → 扩大折叠比例重试
        if best.tokens_after <= budget_tokens or len(dropped) >= len(msgs) - keep_min_messages:
            break
        ratio = round(ratio + 0.1, 2)
        if ratio >= 1.0:
            break

    return best
