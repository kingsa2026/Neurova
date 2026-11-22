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

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


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


# ════════════════════════════════════════════════════════════════
# P0-1（上下文工程十轴 · 轴8）：缓存盈亏平衡判据。
#
# 折叠会重写视图头部（新代摘要行进分辨率阶梯），使两次折叠之间已存活的
# 前缀 KV 缓存失效。增量小而暖缓存大时，这一刀省下的 token 补不回缓存
# 重写——判据在这里单源，编排层只取现场量，不另写一份算术（教义第 6 条）。
# ════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CachePricing:
    """一个 provider 族的缓存计价元数据（USD/token）。

    `ttl_seconds <= 0` 表示该族无保证 TTL（缓存尽力而为、暖窗不确定）。
    """

    ttl_seconds: int
    cached_read_price_per_token: float
    write_price_per_token: float


#: 盈亏平衡判因（封闭集合；读数面按此归因，不写自由文本当键）。
CACHE_REASON_NO_PRICING = "no_pricing"
CACHE_REASON_WARM_WITHIN_TTL = "warm_within_ttl_deferred"
CACHE_REASON_BREAK_EVEN_FAILED = "break_even_failed"
CACHE_REASON_PROCEED = "proceed"
CACHE_BREAK_EVEN_REASONS = frozenset(
    {
        CACHE_REASON_NO_PRICING,
        CACHE_REASON_WARM_WITHIN_TTL,
        CACHE_REASON_BREAK_EVEN_FAILED,
        CACHE_REASON_PROCEED,
    }
)


@dataclass(frozen=True)
class CacheBreakEvenVerdict:
    """缓存盈亏平衡判据输出：是否缓折 + 判因（封闭集合）+ 两个数值。"""

    defer: bool
    reason: str
    savings: float
    rewrite_cost: float


#: 内置计价表（公开定价量级的保守常数，USD/token）：
#: - anthropic：Claude Sonnet 档——基础输入 $3/MTok，缓存读 $0.3/MTok（约 1/10 价），
#:   缓存写 $3.75/MTok（1.25×）；TTL 5 分钟（官方 prompt-caching 文档口径）。
#: - openai 兼容族：GPT-4o 档——输入 $2.5/MTok，缓存命中输入 $1.25/MTok（半价）；
#:   无独立写价（按原价计），缓存为尽力而为、无保证 TTL（记 0 = 无 TTL 界）。
_BUILTIN_CACHE_PRICING: Dict[str, CachePricing] = {
    "anthropic": CachePricing(
        ttl_seconds=300,
        cached_read_price_per_token=0.3e-6,
        write_price_per_token=3.75e-6,
    ),
    "openai": CachePricing(
        ttl_seconds=0,
        cached_read_price_per_token=1.25e-6,
        write_price_per_token=2.5e-6,
    ),
}

#: 模型名 → 家族别名（镜像 agent/loops/registry 的家族规则：claude-* → anthropic、
#: gpt-* → openai）。主路径是 provider 注册表给出的服务商族（精确键）；
#: 模型名匹配只是注册表查无此模型时的兜底，不另造第二份映射语义。
_CACHE_FAMILY_ALIASES = (
    ("anthropic", ("anthropic", "claude")),
    ("openai", ("openai", "gpt-")),
)

#: env 覆盖/追加计价表：JSON 数组 [{provider, ttl_seconds,
#: cached_read_price_per_token, write_price_per_token}]；同名 provider 覆盖
#: 内置值，新 provider 追加。坏 JSON 按无覆盖处置（回退内置表，不抛）。
CACHE_PRICING_ENV = "NEUROVA_CACHE_PRICING_JSON"


def _envCachePricingOverrides() -> Dict[str, CachePricing]:
    """解析 env 计价覆盖（fail-soft：任何解析失败按无覆盖处置并留 debug 痕）。"""
    raw = os.environ.get(CACHE_PRICING_ENV, "")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        entries = data if isinstance(data, list) else []
        overrides: Dict[str, CachePricing] = {}
        for item in entries:
            if not isinstance(item, dict):
                continue
            provider = str(item.get("provider") or "").strip()
            if not provider:
                continue
            overrides[provider.lower()] = CachePricing(
                ttl_seconds=int(item.get("ttl_seconds") or 0),
                cached_read_price_per_token=float(item.get("cached_read_price_per_token") or 0.0),
                write_price_per_token=float(item.get("write_price_per_token") or 0.0),
            )
        return overrides
    except (TypeError, ValueError) as e:
        logger.debug("%s 解析失败，按内置计价表处置: %s", CACHE_PRICING_ENV, e)
        return {}


def getProviderCachePricing(provider_key) -> Optional[CachePricing]:
    """按 provider 族（或模型名）取缓存计价元数据；未知一律 None = 无元数据。

    匹配次序：env/内置表**精确键**（不分大小写）→ 家族别名（键里含
    anthropic/claude 归 anthropic 族，含 openai/gpt- 归 openai 族）。
    None 表示"没有元数据"——调用方据此走数据不足路径，不编数。
    """
    key = str(provider_key or "").strip().lower()
    if not key:
        return None
    table = dict(_BUILTIN_CACHE_PRICING)
    table.update(_envCachePricingOverrides())
    if key in table:
        return table[key]
    for family, aliases in _CACHE_FAMILY_ALIASES:
        pricing = table.get(family)
        if pricing is not None and any(alias in key for alias in aliases):
            return pricing
    return None


def evaluateCacheBreakEven(
    *,
    remaining_steps: int,
    tokens_saved_per_call: int,
    invalidation_tokens: int,
    pricing: Optional[CachePricing],
    safety_factor: float = 1.5,
) -> CacheBreakEvenVerdict:
    """判一次主动折叠在**缓存维度**"值不值"（纯函数）。

    参数:
        remaining_steps: 折叠生效期内剩余模型调用步数的估计。
        tokens_saved_per_call: 折叠后每次调用少带的 token 量。
        invalidation_tokens: 本次折叠会使前缀缓存失效的 token 区间。
        pricing: provider 缓存计价元数据；None = 无元数据。
        safety_factor: 代价侧安全系数（默认 1.5——宁可高估重写代价；下界 1.0）。

    返回:
        CacheBreakEvenVerdict(defer, reason, savings, rewrite_cost)。

    判据次序：
        1. 无定价元数据 ⇒ 不 defer（no_pricing，行为与无判据一致）；
        2. 收益 = remaining_steps × tokens_saved_per_call × cached_read_price；
           代价 = invalidation_tokens × (write_price − cached_read_price) × safety_factor；
        3. 无可失效前缀（invalidation ≤ 0）⇒ 不 defer（没有要保护的缓存）；
        4. 收益 > 代价 ⇒ 不 defer（proceed）；
        5. 收益 ≤ 代价 ⇒ defer（ttl>0 记 warm_within_ttl_deferred，
           无保证 TTL 记 break_even_failed）。
    """
    if pricing is None:
        return CacheBreakEvenVerdict(False, CACHE_REASON_NO_PRICING, 0.0, 0.0)
    steps = max(0, int(remaining_steps or 0))
    saved = max(0, int(tokens_saved_per_call or 0))
    invalidated = max(0, int(invalidation_tokens or 0))
    try:
        safety = float(safety_factor)
    except (TypeError, ValueError):
        safety = 1.5
    if safety < 1.0:
        safety = 1.0
    readPrice = max(0.0, float(pricing.cached_read_price_per_token or 0.0))
    writePrice = max(0.0, float(pricing.write_price_per_token or 0.0))
    savings = steps * saved * readPrice
    rewriteCost = invalidated * max(0.0, writePrice - readPrice) * safety
    if invalidated <= 0 or savings > rewriteCost:
        return CacheBreakEvenVerdict(False, CACHE_REASON_PROCEED, savings, rewriteCost)
    if int(pricing.ttl_seconds or 0) > 0:
        return CacheBreakEvenVerdict(True, CACHE_REASON_WARM_WITHIN_TTL, savings, rewriteCost)
    return CacheBreakEvenVerdict(True, CACHE_REASON_BREAK_EVEN_FAILED, savings, rewriteCost)
