"""对话窗口 token 预算压缩

2026-09-09 kai 空回复事故排查副产物：ContextPool 是归档+语义召回（不裁剪），
get_recent_context 是固定 20 条消息数窗口——两者都不约束 prompt 大小。
本模块提供纯逻辑的窗口预算切分与折叠装配，供 ContextOrchestrator 在
build_context 中做「尾部保留 + 老消息折叠」的自动压缩。
"""

import typing
from dataclasses import dataclass

# 每条消息的协议开销（role/分隔符等的保守估计）。
# 单一事实源：模块内一切"整窗计量"与"逐条计量"都必须经 WindowTokenMeter，
# 它按此常量补开销；`estimate_window_tokens` 只是它的无状态入口。
# 第二份开销常数（含就地写法 `+ 4`）即口径分裂，守卫见
# tests/unit/context/test_window_token_metering.py。
PER_MSG_OVERHEAD = 4
_PER_MSG_OVERHEAD = PER_MSG_OVERHEAD

# 摘要失败收敛：摘要请求失败时从折叠区丢最旧一条
# 重试（输入变小更易成功），最多重试 _SUMMARY_MAX_RETRIES 次；仍失败则回落
# 静态桩（编排层既有语义）。压缩自身必须收敛，不允许摘要失败拖垮整轮压缩。
_SUMMARY_MAX_RETRIES = 3


class WindowTokenMeter:
    """窗口 token 计量的**单源记忆体**（Issue #90 台账 §2 补充发现的根因修复）。

    改前形态：`split_window_by_budget` 每轮重算整窗、又为每条单算一次；
    `compact_window` 的递进折叠循环（ratio 每轮 +0.1，从 0.5 走到 1.0）每轮再各来
    一遍——单位调用内对同一批文本重复计量约 **2.4×**。尺子换成 o200k 精确计数后，
    单次折叠从约 20ms 涨到 75ms，重复计量按倍数放大。

    本类把"计量"收成一次：同一条消息在同一 meter 生命周期内只真正算一次，
    整窗总量由逐条值求和得出（不再有第二套整窗算法）。

    生命周期纪律：一个 meter 只服务一次折叠调用。跨调用复用会把已变化的窗口
    当旧的算——所以 `compact_window` / `split_window_by_budget` 的 `meter` 参数
    缺省为 None，每次调用自建。
    """

    def __init__(self, estimator: typing.Optional[typing.Callable[[str], int]] = None):
        if estimator is None:
            from neurova.context.token_estimator import estimate_tokens

            estimator = estimate_tokens
        self._estimator = estimator
        # 键是 id(obj)，但**同时持有强引用**——只存 id 会被 CPython 的 id 复用
        # 击中（对象被回收后新对象拿到同一 id → 计量结果串号）。meter 生命周期
        # 只有一次折叠调用，持有引用的代价可忽略。
        self._per_message: typing.Dict[int, typing.Tuple[typing.Any, int]] = {}
        self._totals: typing.Dict[int, typing.Tuple[typing.Any, int]] = {}

    @staticmethod
    def _contentOf(message) -> str:
        if isinstance(message, dict):
            return (message or {}).get("content", "") or ""
        return str(message)

    def one(self, message) -> int:
        """单条消息的 token 占用（含协议开销）。"""
        key = id(message)
        cached = self._per_message.get(key)
        if cached is not None and cached[0] is message:
            return cached[1]
        value = self._estimator(self._contentOf(message)) + PER_MSG_OVERHEAD
        self._per_message[key] = (message, value)
        return value

    def total(self, msgs: typing.Iterable) -> int:
        """消息序列的 token 总量：逐条求和（与 `one` 同源，无第二套算法）。"""
        seq = msgs if isinstance(msgs, (list, tuple)) else list(msgs or [])
        key = id(seq)
        cached = self._totals.get(key)
        if cached is not None and cached[0] is seq:
            return cached[1]
        value = sum(self.one(m) for m in seq)
        self._totals[key] = (seq, value)
        return value


def estimate_window_tokens(msgs: typing.Iterable) -> int:
    """估算窗口消息序列的 token 总量（统一估算器 EXACT/BALANCED 策略）。

    无状态入口：等价于一次性 `WindowTokenMeter`。需要在一段逻辑内多次求值时，
    请显式持有 meter，避免重复计量。
    """
    return WindowTokenMeter().total(msgs)


#: 视图归一化保留的字段（协议契约字段 + 工具寻址字段）。
#: 单源：折叠、视图重建、窗口计量三处都读这一份，避免各留各的字段白名单。
_MESSAGE_FIELDS = ("role", "content", "tool_call_id", "name", "tool_calls")


def normalizeViewMessages(messages: typing.Optional[typing.List[dict]]) -> typing.List[dict]:
    """把消息序列归一化为视图序列（保留契约字段，剔除空内容项）。

    视图装配的**唯一归一入口**：折叠、视图重建、窗口计量三处共用，避免各自
    写一份字段白名单——改前正是三处各抄一份"只留 role+content"，于是工具寻址
    字段被无声裁掉（审计 P2-4）。
    """
    out = [_normalizeMessage(m) for m in (messages or []) if isinstance(m, dict)]
    return [m for m in out if m.get("content") or m.get("tool_calls")]


def _normalizeMessage(message: typing.Optional[dict]) -> dict:
    """把一条消息归一化为视图消息：只保留契约字段（含工具寻址字段）。

    不含 `tool_call_id`/`name`/`tool_calls` 的形态会让"硬地址直取"与
    "tool 轮配对"两条链同时断掉（见模块顶部 P2-4 说明）。
    """
    src = message or {}
    out = {key: src[key] for key in _MESSAGE_FIELDS if key in src}
    out.setdefault("role", "user")
    out.setdefault("content", "")
    return out


def split_window_by_budget(
    msgs: typing.List[dict],
    budget_tokens: int,
    keep_min_messages: int = 6,
    target_ratio: float = 0.5,
    meter: typing.Optional["WindowTokenMeter"] = None,
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
    meter = meter or WindowTokenMeter()
    if meter.total(msgs) <= budget_tokens:
        return [], msgs

    target = max(budget_tokens * target_ratio, 1.0)
    acc = 0.0
    kept_count = 0
    for m in reversed(msgs):
        t = meter.one(m)
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
    # P1-2：本轮的 summary 是否为**新**产出。摘要器失败时会沿用 previous_summary
    # （对池侧是幂等 no-op），返回值仍非空——调用方若据此推进"已覆盖"记账，
    # 就是把新增消息谎报为已被摘要覆盖。判据取"与上一轮摘要不同"这一可观察事实，
    # 因此对任何 summarize 实现（含调用方自注入的桥）都成立。
    summary_is_fresh: bool = False


async def compact_window(
    conversation_context: typing.Optional[typing.List[dict]],
    budget_tokens: int,
    summarize: typing.Optional[typing.Callable] = None,
    previous_summary: str = "",
    keep_min_messages: int = 6,
    target_ratio: float = 0.5,
    summary_prefix: str = "[早期对话摘要] ",
    meter: typing.Optional["WindowTokenMeter"] = None,
) -> typing.Optional[WindowCompaction]:
    """超预算时折叠窗口老消息；未超预算返回 None（零行为变化）。

    递进折叠（Letta compaction 对齐，2026-09-10）：折叠目标从
    target_ratio 起步，若折叠后窗口仍超预算则按 0.1 步进扩大折叠
    比例重试，直至放下或已折叠到 keep_min_messages 下限——避免
    一次激进摘要丢信息（最小摘要原则）。

    summarize: async (dropped_msgs, previous_summary) -> Optional[str]
    """
    # 归一化**只裁协议外字段**：工具寻址字段（tool_call_id / name / tool_calls）
    # 必须随消息走——它们被裁掉后，`_tool_placeholder` 的硬地址指针与
    # `repair_tool_turns` 的配对判据同时失效（前者产空指针、后者把完整的
    # tool 轮误判为孤儿），模型再也无法凭指针直取归档原文（审计 P2-4）。
    msgs = normalizeViewMessages(conversation_context)
    if not msgs:
        return None

    # 单源计量：整段折叠（含递进各轮）共用同一个 meter，同一条消息只算一次。
    meter = meter or WindowTokenMeter()

    summary = None
    ratio = target_ratio
    best: typing.Optional[WindowCompaction] = None

    while True:
        dropped, kept = split_window_by_budget(
            msgs, budget_tokens, keep_min_messages, target_ratio=ratio, meter=meter
        )
        if not dropped:
            # 无可折叠（keep_min 下限本身超预算等物理无解）：返回保留态的
            # 尽力结果（零折叠、带说明性摘要行），不静默丢弃折叠机会
            if best is None and meter.total(msgs) > budget_tokens:
                best = WindowCompaction(
                    window=list(msgs),
                    summary=None,
                    compacted_count=0,
                    tokens_before=meter.total(msgs),
                    tokens_after=meter.total(msgs),
                )
            break

        round_summary = None
        skipped_oldest = 0
        if summarize is not None:
            # P0-2 收敛保证：摘要失败 → 丢最旧一条缩小输入重试（上限 3 次），
            # 而非直接放弃摘要。被丢弃的前缀在摘要行显式标注，不静默消失。
            dropped_for_summary = list(dropped)
            for attempt in range(_SUMMARY_MAX_RETRIES + 1):
                try:
                    round_summary = await summarize(dropped_for_summary, previous_summary)
                except Exception:  # noqa: BLE001 - 摘要失败不阻断上下文构建
                    round_summary = None
                if isinstance(round_summary, str) and round_summary.strip():
                    skipped_oldest = attempt
                    break
                if attempt >= _SUMMARY_MAX_RETRIES or len(dropped_for_summary) <= 1:
                    round_summary = None
                    break
                dropped_for_summary = dropped_for_summary[1:]

        window: typing.List[dict] = []
        if round_summary:
            if skipped_oldest > 0:
                round_summary = (
                    f"[摘要收敛时丢弃最早 {skipped_oldest} 条消息] " + round_summary
                )
            window.append({"role": "system", "content": f"{summary_prefix}{round_summary}"})
        window.extend(kept)

        best = WindowCompaction(
            window=window,
            summary=round_summary,
            compacted_count=len(dropped),
            tokens_before=meter.total(msgs),
            tokens_after=meter.total(window),
            summary_is_fresh=bool(round_summary)
            and (not previous_summary or round_summary != previous_summary),
        )
        summary = round_summary or summary

        # 递进：折叠后仍超预算且还有可折叠空间 → 扩大折叠比例重试
        if best.tokens_after <= budget_tokens or len(dropped) >= len(msgs) - keep_min_messages:
            break
        ratio = round(ratio + 0.1, 2)
        if ratio >= 1.0:
            break

    return best
