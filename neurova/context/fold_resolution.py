# -*- coding: utf-8 -*-
"""折叠分辨率阶梯：视图按位置几何退避装配多档概览（Issue #90 · T-11c）。

## 为什么单独一个模块

T-11a/b/d/e 交出的是**数据**：代际栈、池内层节点（带 `covers`）、可解析引用、
后台 rollup。而**视图装配器**从没改过 —— `build_context` 把折叠产出的那一行摘要
（= 代际栈顶那一代）拼进 `context` 就结束了。

实测（真 `build_context` 连跑 6 轮，budget 1200）：池内 **6 档层节点**，视图里
**1 行摘要**。于是工单 §12.1 的 **C2 梯度**在数据上不成立 —— 只有一代，
"越远的位置分辨率越低"（§12.0 B）无从谈起，§12.7 判据 1/2 与探针 P15 全红。

本模块是**阶梯的唯一出处**：档位预算、可行档数、按预算截断三件事都只在这里
定义一次。装配器只做"取索引 → 问阶梯 → 拼行"，读侧（读数、探针）也从同一处
取档位预算 —— 各写一份几何比就是第二份事实源（修复教义第 6 条）。

## 「1 : 4 : 16」的方向（本票的解读，已登记进工单 §12.4）

规格把比写成按档号升序的数列，而 §12.0 B 与 §12.7 判据 2 要求**越远分辨率越低**。
二者只有在"档号升序 = 位置由近及远、预算由大到小"时同时成立：近档 16 份、
中档 4 份、远档 1 份（相邻比恒为 4，按距离升序读即 1 : 4 : 16）。
反向读（远档拿 16 份）会当场违反判据 2。故阶梯取**相邻比 4 的几何序列**，
方向由判据 2 唯一确定。

## 成本为什么有界（不必随轨迹增长）

深度 `k` 的阶梯总预算 = `region × (1 + 1/4 + … + 4^-(k-1)) < 4/3 × region`，
对任意 `k` 都成立。所以"档数不设上限"（§12.1）与视图预算有限并不冲突：
索引不设上限，视图按预算装前 `k` 档，被省掉的深档**如实计数**（`dropped_levels`）
—— 不静默丢层。深档仍可由确定性索引寻址（`covers_ref` 下钻）。
"""

from __future__ import annotations

import os
from typing import Dict, Tuple

#: 回退开关（§12.6 等式测试）。与 T-11e 的 `NEUROVA_CONTEXT_ROLLUP` **刻意不同名**：
#: 那是"rollup 走不走后台"，这是"视图装不装多档"，两件事各用各的开关。
RESOLUTION_ENV = "NEUROVA_CONTEXT_FOLD_RESOLUTION"

#: 档间几何比（工单 §12.1 C2 的 1 : 4 : 16 即相邻比 4）。
GEO_RATIO = 4

#: 折叠概览区在窗口预算里的份额。取 0.5 的理由：级别 1 的档位预算 = region × 4/3 的
#: 倒数关系下约 0.37×window —— 与"栈顶那一代摘要本来就占一行"的既有量级同阶，
#: 同时把这一行从**无上限**（LLM 摘要多长就多长）变成受预算约束。
FOLD_REGION_SHARE = 0.5

#: 最深一档的预算地板。低于它的一行连"摘要首句 + covers_ref"都放不下，
#: 装出来只会是一个不可用的残片 —— 那不如如实记为未装配（`dropped_levels`）。
MIN_LEVEL_TOKENS = 24

#: 截断标记。截断这件事必须对模型可见（不只对读数可见）：悄悄砍掉半句会让
#: 模型以为"这就是那一档的全部"。读数里的 `truncated_chars` 是同一条事实的机器可读面。
TRUNCATION_MARK = "…"


def resolutionEnabled() -> bool:
    """回退开关：默认开；显式 `0` 关（关时装配器逐字保留本票之前的形状）。"""
    return (os.environ.get(RESOLUTION_ENV, "1") or "1").strip() != "0"


def ladderBudgets(levelCount: int, regionBudget: int) -> Dict[int, int]:
    """视角阶梯：返回 `{档号: token 预算}`，**总和不超 `regionBudget`**。

    - 档数 = min(可用档数, 可行档数)：可行档数取"最深一档预算仍 ≥
      `MIN_LEVEL_TOKENS`"的最大值，故地板不会把几何比压歪（先定档数再算预算，
      而不是先算预算再把深档拍到地板上 —— 后者会让相邻比变成 1）。
    - 档号从 1（最近、最细）起递增，相邻比恒为 `GEO_RATIO`。
    """
    count = max(1, int(levelCount))
    budget = max(MIN_LEVEL_TOKENS, int(regionBudget))

    def depths(count: int) -> Dict[int, int]:
        weights = [GEO_RATIO ** -i for i in range(count)]
        total = sum(weights)
        return {
            i + 1: max(1, int(budget * weight / total))
            for i, weight in enumerate(weights)
        }

    chosen = depths(1)
    for candidate in range(2, count + 1):
        ladder = depths(candidate)
        if ladder[candidate] < MIN_LEVEL_TOKENS:
            break
        chosen = ladder
    return chosen


def fitToBudget(text: str, budgetTokens: int) -> Tuple[str, int]:
    """把一段文本裁到 token 预算内，返回 `(裁后文本, 被裁字符数)`。

    保留**开头**（摘要的首句承载主旨）；裁过则补 `TRUNCATION_MARK`，让"这里被裁过"
    对模型可见。裁不动（预算连一个字符都放不下）时返回空串并如实报出被裁字符数 ——
    不返回一段超预算的原文（那等于预算形同虚设）。
    """
    from neurova.context.token_estimator import estimate_tokens

    source = str(text or "")
    budget = max(0, int(budgetTokens))
    if not source:
        return "", 0
    estimated = estimate_tokens(source)
    if estimated <= budget:
        return source, 0

    # 按 token 比例预估字符数，再线性收敛（估算器非线性，单次比例会溢出）。
    keep = max(0, int(len(source) * (budget / max(1, estimated))))
    while keep > 0 and estimate_tokens(source[:keep] + TRUNCATION_MARK) > budget:
        keep = int(keep * 0.9) if keep > 10 else keep - 1
    if keep <= 0:
        return "", len(source)
    fitted = source[:keep] + TRUNCATION_MARK
    return fitted, len(source) - keep


def ladderDepth(budgets: Dict[int, int]) -> int:
    """已装配档数（阶梯上的档位个数）。"""
    return len(budgets or {})


__all__ = [
    "FOLD_REGION_SHARE",
    "GEO_RATIO",
    "MIN_LEVEL_TOKENS",
    "RESOLUTION_ENV",
    "TRUNCATION_MARK",
    "fitToBudget",
    "ladderBudgets",
    "ladderDepth",
    "resolutionEnabled",
]
