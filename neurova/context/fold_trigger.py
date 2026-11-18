# -*- coding: utf-8 -*-
"""折叠触发与冻结分区 —— B2/B5（billion-context 对照改进项）的纯判据层。

两个职责，皆为纯函数（无 I/O、无自持状态），供
`ContextOrchestrator._apply_window_budget` 消费；判据单源在此，
编排层不得另写一份同义条件（教义第 6 条）。

## B5 · 增长门（demand-side trigger）

改前折叠只有一根触发线：视图 token 超预算才折（容量被动）。两个后果：

1. 折叠必然切在任务中间（被容量压力逼出来的应激发）；
2. 会话视图取「最近 20 条」滑动窗——两次折叠之间新增的未折叠消息会被
   滑窗无声挤出视图（既不在摘要覆盖内、也不在视图里；池里有，但模型看不见）。

增长门在「占用过下限 ∧ 距上次折叠的增量够大 ∧ 有可折质量」时**主动**
折叠已消费增量——billion-context 论文 §3.4 demand-side 触发在确定性折叠器
上的对偶实现：折叠落在任务步骤间隙，单次增量更小、摘要质量更高，并在
滑窗把增量挤出视图之前收进摘要。预算击穿（breach）永远直接折叠——
安全线不受门管辖（与 compression_economics 的 SAFETY_LINE_YIELD 同序）。

默认开（2026-11-15 跑数据转正，`NEUROVA_FOLD_GROWTH_GATE=0` 关闭）——
转正依据：双臂马拉松实测门开峰值 -30%/均值 -26%、可恢复率 1.0 无损。

## B2 · 冻结已折叠区（increment-only fold）

改前每次折叠都对整窗重切重摘（previous_summary 链式续写），视图头部的
摘要行逐轮改写 → KV 前缀缓存每轮失效（实测 cache 读占比 7.97%，见
docs/08-research 对照报告 §B6）。冻结分区把「已被摘要覆盖的前缀」与
「未覆盖尾部」分开：前缀按既有代际渲染（渲染产物缓存在折叠槽，两次
折叠之间逐字节复用），折叠只作用于尾部增量——前缀缓存在两次折叠之间
存活。这正是 billion-context "append-only 视图 + 只折增量" 的确定性等价物。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Sequence, Tuple


#: 触发原因（封闭集合；读数面按此归因，不写自由文本当键）。
REASON_BUDGET_BREACH = "budget_breach"
REASON_GROWTH_GATE = "growth_gate"
REASON_GATE_DISABLED = "gate_disabled"
REASON_BELOW_FLOOR = "below_floor"
REASON_INSUFFICIENT_GROWTH = "insufficient_growth"
REASON_INSUFFICIENT_MASS = "insufficient_mass"


@dataclass(frozen=True)
class FoldTriggerDecision:
    """一次折叠触发判定：是否折叠 + 归因 + 三个现场量（读数用）。"""

    should_fold: bool
    reason: str
    occupancy: float
    growth_tokens: int
    growth_msgs: int


def growthGateEnabled() -> bool:
    """增长门总开关：默认开（2026-11-15 跑数据转正——门开峰值 -30%/均值 -26%、
    保留率 1.0 无损）；NEUROVA_FOLD_GROWTH_GATE=0 关闭（kill-switch）。"""
    return os.environ.get("NEUROVA_FOLD_GROWTH_GATE", "1") != "0"


def growthGateParams() -> Dict[str, float]:
    """增长门参数（env 可覆盖；单一出处，编排层只读不抄）。"""
    try:
        floor = float(os.environ.get("NEUROVA_FOLD_GROWTH_FLOOR", "0.6"))
    except (TypeError, ValueError):
        floor = 0.6
    try:
        min_tokens = int(os.environ.get("NEUROVA_FOLD_GROWTH_MIN_TOKENS", "2000"))
    except (TypeError, ValueError):
        min_tokens = 2000
    try:
        min_msgs = int(os.environ.get("NEUROVA_FOLD_GROWTH_MIN_MSGS", "3"))
    except (TypeError, ValueError):
        min_msgs = 3
    return {
        "floor": min(max(floor, 0.05), 1.0),
        "growth_min_tokens": max(0, min_tokens),
        "growth_min_msgs": max(0, min_msgs),
    }


def growthBudgetShare() -> float:
    """增量门槛的**预算份额**（窗口自适应，B5 追加批）。

    门槛随模型窗口缩放：大窗口模型要积累更多增量才主动折（"模型给多大
    预算，系统花多大"），小窗口模型更早折。有效门槛 =
    max(静态下限 NEUROVA_FOLD_GROWTH_MIN_TOKENS, 预算 × 本份额)。
    """
    try:
        share = float(os.environ.get("NEUROVA_FOLD_GROWTH_BUDGET_SHARE", "0.25"))
    except (TypeError, ValueError):
        share = 0.25
    return min(max(share, 0.0), 1.0)


def growthFloorTokens(budget_tokens: int) -> int:
    """增量 token 门槛（窗口自适应）：静态下限与预算份额取大。

    单源：`decideFoldTrigger` 与只读判读面 `assessFoldTrigger` 都从这里取，
    消费方不得另写 max(静态下限, 预算×份额) 的第二份（教义第 6 条）。
    """
    return max(
        growthGateParams()["growth_min_tokens"],
        int(max(1, int(budget_tokens)) * growthBudgetShare()),
    )


def decideFoldTrigger(
    *,
    total_tokens: int,
    budget_tokens: int,
    last_fold_tokens: int,
    last_fold_msgs: int,
    total_msgs: int,
    foldable_msgs: int,
    keep_min_messages: int = 6,
    enabled: bool = None,
) -> FoldTriggerDecision:
    """判一轮该不该折叠（B5）。次序：

    1. 预算击穿 ⇒ 直接折（安全线，不受门管辖）；
    2. 门未开 ⇒ 不折（行为与改前逐字一致：只有击穿才折）；
    3. 占用 < 下限 ⇒ 不折（省 token 不省到影响质量为止——压缩按需不按比例）；
    4. 增量不足（token 与条数双门槛）⇒ 不折（增量太小，摘要不划算且打断任务）；
    5. 可折质量不足（去掉 keep_min 后没有可折对象）⇒ 不折；
    6. 其余 ⇒ 增长门触发折叠。
    """
    total_tokens = max(0, int(total_tokens))
    budget_tokens = max(1, int(budget_tokens))
    occupancy = min(1.0, total_tokens / budget_tokens)
    growth_tokens = (
        total_tokens - int(last_fold_tokens)
        if int(last_fold_tokens or 0) > 0
        else total_tokens
    )
    growth_msgs = (
        total_msgs - int(last_fold_msgs)
        if int(last_fold_msgs or 0) > 0
        else total_msgs
    )

    if total_tokens > budget_tokens:
        return FoldTriggerDecision(True, REASON_BUDGET_BREACH, occupancy, growth_tokens, growth_msgs)

    if enabled is None:
        enabled = growthGateEnabled()
    if not enabled:
        return FoldTriggerDecision(False, REASON_GATE_DISABLED, occupancy, growth_tokens, growth_msgs)

    params = growthGateParams()
    if occupancy < params["floor"]:
        return FoldTriggerDecision(False, REASON_BELOW_FLOOR, occupancy, growth_tokens, growth_msgs)
    # 窗口自适应（B5 追加批）：增量门槛随预算缩放——大窗口模型要积累更多
    # 增量才主动折，小窗口模型更早折；静态下限兜住小预算场景。
    growth_floor_tokens = growthFloorTokens(budget_tokens)
    if growth_tokens < growth_floor_tokens or growth_msgs < params["growth_min_msgs"]:
        return FoldTriggerDecision(False, REASON_INSUFFICIENT_GROWTH, occupancy, growth_tokens, growth_msgs)
    if max(0, int(foldable_msgs)) < max(0, int(keep_min_messages)):
        return FoldTriggerDecision(False, REASON_INSUFFICIENT_MASS, occupancy, growth_tokens, growth_msgs)
    return FoldTriggerDecision(True, REASON_GROWTH_GATE, occupancy, growth_tokens, growth_msgs)


@dataclass(frozen=True)
class FoldTriggerReadout:
    """折叠时机判读（只读盘点面）：单源判定 + 四判据各自的现场读数。

    `decision` 即 `decideFoldTrigger` 的原判定（不复制不改装）；其余字段是
    判据阈值与逐项达标位，供 `context_status` 等盘点面拼装回执，不参与控制流。
    """

    decision: FoldTriggerDecision
    gate_enabled: bool
    floor: float
    growth_floor_tokens: int
    growth_min_msgs: int
    keep_min_messages: int
    foldable_msgs: int
    occupancy_met: bool
    growth_tokens_met: bool
    growth_msgs_met: bool
    mass_met: bool


def assessFoldTrigger(
    *,
    total_tokens: int,
    budget_tokens: int,
    last_fold_tokens: int,
    last_fold_msgs: int,
    total_msgs: int,
    enabled: bool = None,
    keep_min_messages: int = 6,
) -> FoldTriggerReadout:
    """只读判定辅助（SC-3）：折叠时机判读 = 单源判定 + 四判据各自读数。

    判定**直接复用** `decideFoldTrigger`（本函数不写第二套判据）；阈值一律取
    自本模块既有单源（`growthGateParams` / `growthFloorTokens`）。`foldable_msgs`
    由 `total_msgs - keep_min_messages` 就地推导（与编排层调用点同口径），
    调用方无需自带。
    """
    keep_min = max(0, int(keep_min_messages))
    foldable_msgs = max(0, int(total_msgs) - keep_min)
    decision = decideFoldTrigger(
        total_tokens=total_tokens,
        budget_tokens=budget_tokens,
        last_fold_tokens=last_fold_tokens,
        last_fold_msgs=last_fold_msgs,
        total_msgs=total_msgs,
        foldable_msgs=foldable_msgs,
        keep_min_messages=keep_min,
        enabled=enabled,
    )
    params = growthGateParams()
    gate_enabled = growthGateEnabled() if enabled is None else bool(enabled)
    budget = max(1, int(budget_tokens))
    floor_tokens = growthFloorTokens(budget)
    occupancy = min(1.0, max(0, int(total_tokens)) / budget)
    return FoldTriggerReadout(
        decision=decision,
        gate_enabled=gate_enabled,
        floor=params["floor"],
        growth_floor_tokens=floor_tokens,
        growth_min_msgs=int(params["growth_min_msgs"]),
        keep_min_messages=keep_min,
        foldable_msgs=foldable_msgs,
        occupancy_met=occupancy >= params["floor"],
        growth_tokens_met=int(decision.growth_tokens) >= floor_tokens,
        growth_msgs_met=int(decision.growth_msgs) >= int(params["growth_min_msgs"]),
        mass_met=foldable_msgs >= keep_min,
    )


def splitFrozenCoveredPrefix(
    msgs: Sequence[dict],
    covered: Iterable[str],
    hasher: Callable[[dict], str],
) -> Tuple[List[dict], List[dict]]:
    """把视图切成（已覆盖前缀, 未覆盖尾部）（B2）。

    折叠永远从头部折起，故「已摘要覆盖」的消息在视图里必为一段**前缀**
    （滑窗只从头上滑）。取最长前缀：一旦遇到未覆盖消息即停——其后即使
    出现 covered 集合里的 hash（理论不该有），也按未覆盖处理，交由整窗
    重折的安全线兜底，不在判据层猜。
    """
    covered_set = set(covered or ())
    frozen: List[dict] = []
    for msg in msgs or []:
        if hasher(msg) in covered_set:
            frozen.append(msg)
        else:
            break
    return frozen, list((msgs or [])[len(frozen):])
