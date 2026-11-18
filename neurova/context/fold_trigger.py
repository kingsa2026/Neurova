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

import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, Tuple


#: 触发原因（封闭集合；读数面按此归因，不写自由文本当键）。
REASON_BUDGET_BREACH = "budget_breach"
REASON_GROWTH_GATE = "growth_gate"
REASON_GATE_DISABLED = "gate_disabled"
REASON_BELOW_FLOOR = "below_floor"
REASON_INSUFFICIENT_GROWTH = "insufficient_growth"
REASON_INSUFFICIENT_MASS = "insufficient_mass"
#: SC-2 卡住抑制的归因：增长门想折、被卡住信号改判不折（诚实归因，不谎报"门没触发"）。
REASON_STUCK_SUPPRESSED = "stuck_suppressed"

#: SC-2：工具失败率阈值（失败率 = 1 - 成功率，**严格大于**该值判卡住）。
STUCK_FAILURE_RATE_THRESHOLD = 0.5

#: S6'：折叠基线时间线事件种类（与 CompressionEvent / 冷却事件同一落盘面）。
FOLD_BASELINE_TIMELINE_KIND = "fold_baseline"

#: 折叠尾保护下限（keep_min_messages）——本模块内判定/切点共用此单源。
#: （`window_compactor.compact_window` 的同名默认值是既有另一处，本卡不动
#: window_compactor；收口留待后续批。）
FOLD_KEEP_MIN_MESSAGES = 6


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
    keep_min_messages: int = FOLD_KEEP_MIN_MESSAGES,
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
    keep_min_messages: int = FOLD_KEEP_MIN_MESSAGES,
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


def reflectionFoldCutIndex(
    *,
    rest_len: int,
    distilled_len: int,
    keep_min_messages: int = FOLD_KEEP_MIN_MESSAGES,
) -> int:
    """SC-7 反思节律对齐：已提炼区在未覆盖尾段内的折叠终点（不含；0 = 无延伸）。

    口径（保守近似，对照文档 §9.4 SC-7）：MetaLedger 游标只给"最近一次反思
    编译的时刻与事件上界"，编译覆盖的**消息区间**不可直接得——按「最近反思
    时刻之前的更早消息」计（编排层以水印落位：反思后首轮建图时的窗口长度，
    该长度内的消息即编译发生前的更早消息）。

    切点不越过 keep_min 尾保护：推导链最后一条消息/当前工具调用对由既有
    尾保护管辖（与冻结头/前缀保护合流，不重复造保护）。
    """
    restLen = max(0, int(rest_len))
    distilled = max(0, int(distilled_len))
    keepMin = max(0, int(keep_min_messages))
    return max(0, min(distilled, restLen - keepMin))


def reflectionAlignedFoldBudget(
    *,
    plain_fold_budget: int,
    kept_tokens: int,
    target_ratio: float,
) -> int:
    """SC-7 反思节律对齐：把折叠预算压到「保留区 = 反思边界之后」的水平。

    对齐只是**候选排序信号**（对照文档 §9.5 第 1 条：元认知信号是优先级
    建议，不是替代门）：只让更早的已提炼消息提前进折叠区，绝不放宽折叠——
    结果预算取 min(原预算, 对齐预算)。保留区目标 = kept_tokens（反思边界
    之后的尾段 token），按 split 的 target_ratio 口径反推预算。
    """
    plain = max(1000, int(plain_fold_budget))
    ratio = min(max(float(target_ratio), 0.05), 1.0)
    aligned = max(1000, int(math.ceil(max(0, int(kept_tokens)) / ratio)))
    return min(plain, aligned)


# ════════════════════════════════════════════════════════════════
# SC-1 / SC-2 / SC-8 / S6'：软抑制、边界保护与基线重放（对照文档 §9.4/§9.5）
# ════════════════════════════════════════════════════════════════

def stuckFailureRateThreshold() -> float:
    """SC-2：工具失败率阈值（env `NEUROVA_FOLD_STUCK_FAILURE_RATE` 可覆盖）。"""
    try:
        value = float(
            os.environ.get("NEUROVA_FOLD_STUCK_FAILURE_RATE", str(STUCK_FAILURE_RATE_THRESHOLD))
        )
    except (TypeError, ValueError):
        value = STUCK_FAILURE_RATE_THRESHOLD
    return min(max(value, 0.05), 1.0)


def suppressProactiveFold(decision: FoldTriggerDecision, reason: str) -> FoldTriggerDecision:
    """把一次增长门主动折叠判定**改判**为抑制（现场量原样保留，归因换抑制原因）。

    软抑制不改写触发算术：occupancy/growth 现场量照旧，只把"该不该折"翻成否
    并如实归因——读数面看到的是"门想折、被某某信号按住"，不是"门没触发"。
    """
    return FoldTriggerDecision(
        False, reason, decision.occupancy, decision.growth_tokens, decision.growth_msgs
    )


def stuckSuppressionHit(
    *,
    avoidToolActive: bool,
    toolSuccessRates: Dict[str, float],
    failureRateThreshold: float = None,
) -> bool:
    """SC-2 卡住抑制命中判定（纯判据；信号是现成读数，本函数不检测卡住）。

    命中 = 活跃 avoid_tool 教训 ∨ 任一工具失败率超阈（失败率 = 1 - 成功率，
    严格大于阈值）。工具成功率由 MetaLedger.tool_success_rates 给出（已按
    最小样本过滤），这里只做判定，不另造第二套卡住检测器。
    """
    if avoidToolActive:
        return True
    threshold = (
        stuckFailureRateThreshold() if failureRateThreshold is None else failureRateThreshold
    )
    for rate in (toolSuccessRates or {}).values():
        try:
            failureRate = 1.0 - float(rate)
        except (TypeError, ValueError):
            continue
        if failureRate > threshold:
            return True
    return False


def derivationAnchorCount(msgs: Sequence[dict]) -> int:
    """SC-1 边界锚点条数：最后一条消息 + 当前未闭合工具调用对（纯判据）。

    锚点是**推导链的当前端点**：尾部为 `role="tool"` 结果行时，连续结果行与
    声明这些调用的 `assistant.tool_calls` 行一并计入（一次并行多工具调用是
    一个调用对整体，拆开折叠会把寻址指针与结果分离）；尾部为已发出但未拿到
    结果的调用行时，该行本身是锚点。
    """
    rows = list(msgs or [])
    n = len(rows)
    if n == 0:
        return 0
    end = n - 2  # 最后一个非锚点下标；最后一条消息恒为锚点（锚点从 end+1 起）
    last = rows[-1] or {}
    if str(last.get("role") or "") == "tool":
        # 尾部是结果行：连续结果行 + 声明这些调用的 assistant.tool_calls 行
        while end >= 0 and str((rows[end] or {}).get("role") or "") == "tool":
            end -= 1
        if end >= 0:
            head = rows[end] or {}
            if str(head.get("role") or "") == "assistant" and head.get("tool_calls"):
                end -= 1
    return n - (end + 1)


def lessonIsActive(lesson: Mapping) -> bool:
    """活跃教训判据（与 check_tool_advisory 同一 TTL 口径）。

    未过期（expires_at 缺省视为活跃）且状态非失效。status 缺省视为活跃
    （本仓 lesson 无强制状态列；growth-log 的 PENDING/VALIDATED 均属活跃态，
    EXPIRED/REJECTED 类值不豁免）。
    """
    meta = lesson or {}
    expiresAt = str(meta.get("expires_at") or "").strip()
    if expiresAt:
        now = datetime.now(timezone.utc).isoformat()
        if expiresAt < now:
            return False
    status = str(meta.get("status") or "").strip().lower()
    if status and status not in ("pending", "validated"):
        return False
    return True


def _messageReferencesLessonSubject(message: dict, subject: str) -> bool:
    """结构匹配：tool 行的 name 或 assistant.tool_calls 的 function.name 命中 subject。

    不做正文子串匹配——正文提到工具名不等于该消息是教训的证据原文。
    """
    if not subject:
        return False
    row = message or {}
    if str(row.get("role") or "") == "tool" and str(row.get("name") or "") == subject:
        return True
    for call in row.get("tool_calls") or []:
        function = (call or {}).get("function") or {}
        if str(function.get("name") or "") == subject:
            return True
    return False


def lessonProtectedStart(msgs: Sequence[dict], lessons: Iterable[dict]) -> int:
    """SC-8：活跃教训引用的**最早**原文消息下标（无命中返回 len(msgs)）。

    "折叠时豁免"的切分口径：从最早被引用消息起整段保留在视图（与冻结头/
    反思对齐的切点语义同形——保留区是尾段，时序不打乱）。只有活跃教训
    （lessonIsActive）参与；过期教训不豁免。
    """
    rows = list(msgs or [])
    subjects = {
        str((lesson or {}).get("subject") or "")
        for lesson in (lessons or [])
        if lessonIsActive(lesson)
    }
    subjects.discard("")
    if not subjects or not rows:
        return len(rows)
    for index, row in enumerate(rows):
        for subject in subjects:
            if _messageReferencesLessonSubject(row, subject):
                return index
    return len(rows)


def rebuildFoldBaseline(timelineEvents: Iterable) -> Dict[str, Any]:
    """从会话时间线重放折叠基线（S6'；时间线是事实源，复用冷却重建模式）。

    顺序重放 fold_baseline 事件：covered 集取**并集**（增量式落账），计数器/
    摘要取**最新一条**。其余种类与基线无关，跳过。返回折叠槽形状的基线
    （last_fold_tokens/last_fold_msgs/last_count/fold_seq/summary/covered）；
    无基线事件时返回空 dict（调用方按"无基线"处理，行为与改前一致）。
    """
    baseline: Dict[str, Any] = {}
    covered: set = set()
    for row in timelineEvents or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("kind") or "") != FOLD_BASELINE_TIMELINE_KIND:
            continue
        payload = row.get("event")
        payload = payload if isinstance(payload, dict) else {}
        covered |= {str(h) for h in (payload.get("covered") or []) if h}
        for key, payloadKey in (
            ("last_fold_tokens", "lastFoldTokens"),
            ("last_fold_msgs", "lastFoldMsgs"),
            ("last_count", "lastCount"),
            ("fold_seq", "foldSeq"),
        ):
            if payloadKey in payload:
                try:
                    baseline[key] = int(payload.get(payloadKey) or 0)
                except (TypeError, ValueError):
                    pass
        if "summary" in payload:
            baseline["summary"] = str(payload.get("summary") or "")
    if not baseline and not covered:
        return {}
    baseline["covered"] = covered
    return baseline
