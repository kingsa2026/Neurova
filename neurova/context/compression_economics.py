# -*- coding: utf-8 -*-
"""压缩经济性判据 —— 折叠是**有损动作**，有损动作必须可归因。

本模块是"这一刀值不值"的**唯一**判据出处（Issue #289 · 002）。
003 的负债口径引用本模块的输出字段（`profit` / `cost`），不得另立一份定义。

## 为什么需要它

本仓此前只回答"怎么塞下"，不回答"该不该塞"：`compression_ratio` 是
"装不下就等比缩小"的**结果**，不是判据；算出来只进日志，跨趟无人回读。
而 `envelope.py` 的"装不下弃整个信封"是净损失路径，此前不产生任何可归因读数。

## 三态不可折叠

"没测到"（`insufficient_data`）与"不划算"（`uneconomical`）必须是两个不同的值。
把未测量演成失败，是本仓在 `success` 三态上已经修过的同类病灶。
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CompressionAction(Enum):
    """一次压缩动作的处置值（封闭枚举：穷举且互斥）。"""

    # ── 动作侧（允许产生有损折叠）────────────────────────────────
    ECONOMICAL = "economical"
    """经济性成立：净省下的 token 大于为保留摘要付出的代价。"""

    SAFETY_LINE_YIELD = "safety_line_yield"
    """安全线让位：占用已撞窗口硬顶，此时**必须压**，此路径不计经济性。"""

    # ── 不动作侧（"不动作也出账"的闭合集合）──────────────────────
    PROFIT_NOT_POSITIVE = "profit_not_positive"
    """收益非正：折叠后省不出 token。"""

    UNECONOMICAL = "uneconomical"
    """经济性不足：省出的补不回本次代价（摘要留存本身要占位）。"""

    INSUFFICIENT_DATA = "insufficient_data"
    """数据不足：没有上一轮实测读数，判不了——**不等于**不划算。"""

    INFEASIBLE = "infeasible"
    """动作不可行：预演发现无物可切，不许 abort 之后再失败。"""

    RULER_UNCALIBRATED = "ruler_uncalibrated"
    """尺子未校准：判定所依赖的 token 尺子走了回退档，闸不得进入生效态。"""

    ENVELOPE_DISCARDED = "envelope_discarded"
    """整封被弃：装不下外壳的净损失路径——它必须留下可归因读数。"""


#: 动作侧取值（只有这两个允许产生有损折叠）。
ACTING_VALUES = frozenset({CompressionAction.ECONOMICAL, CompressionAction.SAFETY_LINE_YIELD})

#: 不动作侧取值（与动作侧互补，穷举无遗漏；每个值至少一条用例）。
INACTION_VALUES = frozenset(CompressionAction) - ACTING_VALUES


@dataclass(frozen=True)
class CompressionVerdict:
    """判据输出：是否动作 + 原因（封闭枚举）+ 两个数值（收益、代价）。"""

    act: bool
    action: CompressionAction
    profit: int
    cost: int

def evaluateCompressionEconomics(
    *,
    foldable_tokens: int,
    summary_tokens: int,
    occupied_tokens: int,
    window_ceiling: int,
    prior_compression_ratio: Optional[float],
    ruler_calibrated: bool = True,
) -> CompressionVerdict:
    """判一次有损折叠"值不值"（纯函数，输入全部是本仓已有的量）。

    参数:
        foldable_tokens: 本次拟折叠对象的 token 量（同一把尺子测）。
        summary_tokens: 折叠后**留存**下来的 token 量（摘要行 / 压缩后信封）。
        occupied_tokens: 本轮装配后的总占用。
        window_ceiling: 该链的窗口**硬顶**（撞上即安全线让位）。
            非正值表示本链没有已知硬顶——此时不构造安全线让位（不许把
            软预算冒充硬顶，那会让闸恒不让位、等于没有闸）。
        prior_compression_ratio: 上一轮实测的 `compression_ratio`（1.0 = 压了等于没压）。
            `None` 表示从未测过 —— 与"测了但不省"是两件事。
        ruler_calibrated: 判据所依赖的 token 尺子是否处于校准档。

    返回:
        CompressionVerdict：是否动作 + 原因值 + 收益 / 代价两个数值。

    判据次序（每一档都先于下一档，避免"安全线被经济性挡下"这类越权）：
        1. 尺子未校准 ⇒ 闸不生效（RULER_UNCALIBRATED）
        2. 撞窗口硬顶 ⇒ 安全线让位，此路径**不计**经济性（SAFETY_LINE_YIELD）
        3. 预演无物可切 ⇒ 不进入动作（INFEASIBLE）
        4. 收益非正 ⇒ 不动作（PROFIT_NOT_POSITIVE）
        5. 无上一轮实测 ⇒ 不动作（INSUFFICIENT_DATA，不是"不划算"）
        6. 收益补不回留存代价，或上一轮实测已证折叠无效 ⇒ UNECONOMICAL
        7. 其余 ⇒ ECONOMICAL
    """
    foldable = max(0, int(foldable_tokens))
    summary = max(0, int(summary_tokens))
    profit = foldable - summary
    cost = summary

    if not ruler_calibrated:
        return CompressionVerdict(False, CompressionAction.RULER_UNCALIBRATED, profit, cost)

    ceiling = int(window_ceiling or 0)
    if ceiling > 0 and int(occupied_tokens or 0) >= ceiling:
        return CompressionVerdict(True, CompressionAction.SAFETY_LINE_YIELD, profit, cost)

    if foldable <= 0:
        return CompressionVerdict(False, CompressionAction.INFEASIBLE, profit, cost)

    if profit <= 0:
        return CompressionVerdict(False, CompressionAction.PROFIT_NOT_POSITIVE, profit, cost)

    if prior_compression_ratio is None:
        return CompressionVerdict(False, CompressionAction.INSUFFICIENT_DATA, profit, cost)

    prior = float(prior_compression_ratio)
    if prior >= 1.0 or profit <= cost:
        return CompressionVerdict(False, CompressionAction.UNECONOMICAL, profit, cost)

    return CompressionVerdict(True, CompressionAction.ECONOMICAL, profit, cost)
