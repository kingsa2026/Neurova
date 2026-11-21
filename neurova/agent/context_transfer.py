"""上下文传递工件（参照系 ac 借鉴 B2）：ContextTransfer 廉价登记 + ContextHandoff 物化 + 预算 + 三态投递。

跨 run / 跨 agent 的上下文交接不再依赖自由文本，而是产出可审计的工件：
- ContextTransfer：一次传递意图的廉价登记（类型、源点位、解析状态）。
- ContextHandoff：物化后的交接工件——预算内挑选的历史、被省略条目 id（不丢弃，
  供上层按需恢复）、覆盖说明、投递状态与实际成本。
- 预算：token / byte 双预算，从新到旧整条填充；强制保留最新一轮与最早 user。
- 诚实失败：窗口放不下交接内容时抛 ContextHandoffBudgetError，禁止静默截断。

五类型 × 本仓编排触发点接线矩阵（B2 多触发点卡的可审计产出；改接线先改此矩阵，
测试钉子在 tests/unit/agent/test_context_transfer_triggers.py）：

- fork —— 本仓机制：C2 分支派生（continue_subagent mode=fork →
  NeuacpMemberSurface.fork → spawn 派生新 run，新 member 会话 + resumed_from
  溯源）。接线决策：已接（B2 多触发点卡）——swarm._updateSubagentInner 的
  fork 分支在派生前为**已终态**来源 run 构建交接工件（type=fork，登记/预算/
  inline 投递/context_transfer 事件留痕），随分支任务投递；构建失败诚实降级
  不阻断 fork。运行中来源无产出可交接，fork 照常（不带工件，如实缺省）。
- provider_handoff —— 本仓机制：D-B 跨 executor 切换（resumeFinishedRun
  五结果决策 create_with_handoff / restart_and_resume →
  NeuacpMemberSurface.handoffArtifact）。接线决策：已接（B2 既有）——工件经
  本模块 buildHandoff 物化（type=subagent_result 登记），随重开的 member
  会话任务 inline 投递；断言测试钉住。
- merge_back —— 本仓机制：候选合入（_submitResultCandidate /
  _mergeCandidateForRun）。接线决策：如实不接——合入消费的是子 run 全文
  report（无截断），不存在需要工件化的「先前上下文」；硬套工件不增益，
  反而多出一处截断面。
- subagent_spawn —— 本仓机制：普通 spawn 派生。接线决策：如实不接——spawn
  的任务书本身就是完整上下文，没有「先前上下文」可交接；父侧历史由会话召回
  既有通道覆盖。
- subagent_result —— 本仓机制：完成回灌（_uplinkEnvelope + _notifyParentMail，
  信封带全文 report + transcript 指针，无截断）。接线决策：触发点如实不接——
  完成信封已带全文，工件不增益；类型枚举本身被 B2 续跑/分支衔接复用
  （SwarmManager._buildResumeHandoff 以本类型登记），衔接工件即本类型的既有消费点。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

TRANSFER_TYPES = ("fork", "provider_handoff", "merge_back", "subagent_spawn", "subagent_result")
HANDOFF_STRATEGIES = ("delta_since_last_seen", "full_summary", "checkpoint_summary", "manual_context")
DELIVERY_STATES = ("pending", "injected", "inline", "failed")

#: D-A 拍板（2026-11-21）：默认交接预算 32k token（原 16k；env
#: NEUROVA_CONTEXT_HANDOFF_TOKEN_CAP 仍可覆盖）。
DEFAULT_TOKEN_CAP = 32000
MIN_TOKEN_CAP, MAX_TOKEN_CAP = 1024, 64000
DEFAULT_BYTE_CAP = 64 * 1024
PER_IMAGE_RESERVE_TOKENS = 8192

# inline 投递文本的前缀声明：交接内容不是用户输入，避免下游把工件误当作用户话术。
_INLINE_PREFIX_LINE = "【上下文交接】以下是上下文交接内容，非用户输入。"

_USER_ASSISTANT_ROLES = ("user", "assistant")


class ContextTransferError(Exception):
    """上下文传递工件的构造、校验或状态推进非法。"""


class ContextHandoffBudgetError(ContextTransferError):
    """预算放不下交接内容：宁可失败，不静默截断。"""


@dataclass
class ContextSourcePoint:
    """交接源点位：发生在哪个 thread / run / checkpoint。"""

    thread_id: str
    run_id: Optional[str] = None
    checkpoint_id: Optional[str] = None


@dataclass
class ContextTransfer:
    """一次上下文传递的廉价登记（先登记，后按需物化 ContextHandoff）。"""

    transfer_id: str
    type: str  # 必须在 TRANSFER_TYPES
    source_point: ContextSourcePoint
    resolution: Optional[str] = None  # native_fork | portable_context | None(未解析)
    status: str = "pending"  # pending | resolved | consumed | superseded


@dataclass
class ContextHandoff:
    """物化后的交接工件：带预算、可审计、省略可恢复、投递状态可追踪。"""

    handoff_id: str
    transfer_id: str
    thread_id: str
    target_run_id: Optional[str]
    strategy: str  # 必须在 HANDOFF_STRATEGIES
    summary_text: str
    history: List[dict]  # 保留的历史条目（每条含 role/content 等）
    omitted_item_ids: List[str]  # 预算放不下被省略的条目 id（不丢弃，供上层按需恢复）
    coverage_text: str  # 覆盖说明（含恢复指引文案）
    delivery_status: str = "pending"  # DELIVERY_STATES
    budget_tokens: int = 0
    budget_bytes: int = 0


def clampTokenCap(cap: Optional[int]) -> int:
    """None→DEFAULT_TOKEN_CAP；夹在 [MIN_TOKEN_CAP, MAX_TOKEN_CAP]。"""
    if cap is None:
        return DEFAULT_TOKEN_CAP
    return max(MIN_TOKEN_CAP, min(MAX_TOKEN_CAP, int(cap)))


def estimateTokens(text: str) -> int:
    """token 估算：UTF-8 字节数 // 4 向上取整（可测、无重依赖）。"""
    return (len(text.encode("utf-8")) + 3) // 4


def _itemTokenCost(item: dict, tokenFn: Callable[[str], int]) -> int:
    """单条历史成本 = 文本 token + 图片张数 * 每图预留。"""
    images = item.get("images") or 0
    return tokenFn(str(item.get("content", ""))) + int(images) * PER_IMAGE_RESERVE_TOKENS


def _itemByteCost(item: dict) -> int:
    """单条历史的字节成本：content 的 UTF-8 字节数。"""
    return len(str(item.get("content", "")).encode("utf-8"))


def computeHandoffBudget(*, token_cap: Optional[int] = None, window_tokens: int,
                         native_usage_tokens: int = 0, input_tokens: int = 0,
                         reserve_tokens: int = 0, byte_cap: Optional[int] = None) -> Tuple[int, int]:
    """返回 (budget_tokens, budget_bytes)。

    budget_tokens = min(clampTokenCap(token_cap), window_tokens - native_usage - input - reserve)，
    结果 < MIN_TOKEN_CAP 时抛 ContextHandoffBudgetError（说明窗口放不下交接内容）。
    budget_bytes = min(DEFAULT_BYTE_CAP, byte_cap or DEFAULT_BYTE_CAP)。
    """
    if byte_cap is not None and byte_cap < 0:
        raise ContextTransferError(f"byte_cap 不能为负数：{byte_cap}")
    windowBudget = int(window_tokens) - int(native_usage_tokens) - int(input_tokens) - int(reserve_tokens)
    budgetTokens = min(clampTokenCap(token_cap), windowBudget)
    if budgetTokens < MIN_TOKEN_CAP:
        raise ContextHandoffBudgetError(
            f"上下文窗口放不下交接内容：窗口余量 {windowBudget} tokens，"
            f"低于交接下限 {MIN_TOKEN_CAP} tokens（宁可失败，不静默截断）。"
        )
    budgetBytes = min(DEFAULT_BYTE_CAP, byte_cap if byte_cap else DEFAULT_BYTE_CAP)
    return budgetTokens, budgetBytes


def _forcedKeepIds(items: List[dict]) -> set:
    """强制保留项：最新一条 user/assistant、最早一条 user（预算不够也保留）。"""
    forced: set = set()
    for item in reversed(items):
        if item.get("role") in _USER_ASSISTANT_ROLES:
            forced.add(str(item.get("id")))
            break
    for item in items:
        if item.get("role") == "user":
            forced.add(str(item.get("id")))
            break
    return forced


def _coverageText(keptCount: int, omittedIds: List[str], total: int) -> str:
    """中文覆盖说明；omitted 非空时必须带恢复指引。"""
    if not omittedIds:
        return f"历史覆盖：注入 {keptCount}/{total} 条，无省略。"
    idList = "、".join(omittedIds)
    return (
        f"历史覆盖：注入 {keptCount}/{total} 条；"
        f"以下 {len(omittedIds)} 条历史因预算未注入，可按 item id 从会话归档取回：{idList}。"
    )


def selectHistory(items: List[dict], *, budget_tokens: int, budget_bytes: int,
                  token_fn=estimateTokens) -> Tuple[List[dict], List[str], str]:
    """按预算从新到旧整条填充历史。

    items 每条形如 {"id": str, "role": "user"|"assistant"|"tool"|..., "content": str,
                    "images": int(可选，图片张数)}，按时间升序（旧→新）排列。
    强制保留：最新一条 user/assistant、最早一条 user（即使超预算也保留，此时预算被
    突破是调用方窗口问题，函数仍按实际成本返回）。
    图片条目成本 = 文本 token + images*PER_IMAGE_RESERVE_TOKENS。
    返回 (kept_items, omitted_item_ids, coverage_text)；coverage_text 为中文覆盖说明，
    omitted 非空时含恢复指引（按 item id 从会话归档取回）。
    """
    total = len(items)
    if total == 0:
        return [], [], "历史覆盖：会话无历史条目，无可交接内容。"

    forcedIds = _forcedKeepIds(items)
    keptNewestFirst: List[dict] = []
    omittedNewestFirst: List[str] = []
    remainingTokens = int(budget_tokens)
    remainingBytes = int(budget_bytes)
    cutoffReached = False

    for item in reversed(items):
        itemId = str(item.get("id"))
        itemTokens = _itemTokenCost(item, token_fn)
        itemBytes = _itemByteCost(item)
        if itemId in forcedIds:
            # 强制保留不计入预算放行判断，但照实扣减，保证断流点真实
            keptNewestFirst.append(item)
            remainingTokens -= itemTokens
            remainingBytes -= itemBytes
            continue
        if cutoffReached or itemTokens > remainingTokens or itemBytes > remainingBytes:
            # 从新到旧首个放不下的条目即断流：其后（更旧的）非强制条目一并省略
            cutoffReached = True
            omittedNewestFirst.append(itemId)
            continue
        keptNewestFirst.append(item)
        remainingTokens -= itemTokens
        remainingBytes -= itemBytes

    kept = list(reversed(keptNewestFirst))
    omittedIds = list(reversed(omittedNewestFirst))
    coverage = _coverageText(len(kept), omittedIds, total)
    return kept, omittedIds, coverage


def _summaryLine(item: dict) -> str:
    return f"[{item.get('role', 'unknown')}] {item.get('content', '')}"


def _buildSummaryText(strategy: str, kept: List[dict], omittedIds: List[str], total: int) -> str:
    """按 strategy 组织 summary_text（均基于预算内保留的 kept 条目，时序旧→新）。"""
    if strategy == "manual_context":
        # 原样拼接，不加角色标注与标题
        return "\n".join(str(item.get("content", "")) for item in kept)

    body = "\n".join(_summaryLine(item) for item in kept)
    if strategy == "full_summary":
        header = f"上下文交接·完整摘要（{len(kept)}/{total} 条）："
    elif strategy == "delta_since_last_seen":
        header = f"上下文交接·自上次同步以来的新增内容（{len(kept)} 条）："
    elif strategy == "checkpoint_summary":
        header = f"上下文交接·检查点摘要（注入 {len(kept)}/{total} 条，省略 {len(omittedIds)} 条）："
    else:
        raise ContextTransferError(f"未知的交接策略：{strategy}（合法：{HANDOFF_STRATEGIES}）")
    return f"{header}\n{body}" if body else header


def buildHandoff(transfer: ContextTransfer, *, thread_id: str, target_run_id: Optional[str],
                 strategy: str, items: List[dict], token_cap: Optional[int] = None,
                 window_tokens: int, native_usage_tokens: int = 0, input_tokens: int = 0,
                 reserve_tokens: int = 0, token_fn=estimateTokens) -> ContextHandoff:
    """组合入口：算预算→selectHistory→按 strategy 生成 summary_text。

    strategy 非法 / transfer.type 非法 → ContextTransferError；窗口放不下 →
    ContextHandoffBudgetError。handoff.budget_* 记录物化后的实际成本。
    """
    if transfer.type not in TRANSFER_TYPES:
        raise ContextTransferError(f"未知的传递类型：{transfer.type}（合法：{TRANSFER_TYPES}）")
    if strategy not in HANDOFF_STRATEGIES:
        raise ContextTransferError(f"未知的交接策略：{strategy}（合法：{HANDOFF_STRATEGIES}）")

    budgetTokens, budgetBytes = computeHandoffBudget(
        token_cap=token_cap,
        window_tokens=window_tokens,
        native_usage_tokens=native_usage_tokens,
        input_tokens=input_tokens,
        reserve_tokens=reserve_tokens,
    )
    kept, omittedIds, coverage = selectHistory(
        items, budget_tokens=budgetTokens, budget_bytes=budgetBytes, token_fn=token_fn
    )
    summaryText = _buildSummaryText(strategy, kept, omittedIds, len(items))
    actualTokens = sum(_itemTokenCost(item, token_fn) for item in kept)
    actualBytes = sum(_itemByteCost(item) for item in kept)
    return ContextHandoff(
        handoff_id=uuid.uuid4().hex,
        transfer_id=transfer.transfer_id,
        thread_id=thread_id,
        target_run_id=target_run_id,
        strategy=strategy,
        summary_text=summaryText,
        history=kept,
        omitted_item_ids=omittedIds,
        coverage_text=coverage,
        delivery_status="pending",
        budget_tokens=actualTokens,
        budget_bytes=actualBytes,
    )


def renderInlinePrefix(handoff: ContextHandoff) -> str:
    """inline 投递文本：交接前缀（标明"以下是上下文交接内容，非用户输入"）
    + summary_text + coverage_text。空 summary 且无 history → ContextTransferError。
    """
    if not handoff.summary_text and not handoff.history:
        raise ContextTransferError(
            f"交接 {handoff.handoff_id} 无可投递内容：summary_text 与 history 均为空。"
        )
    parts = [_INLINE_PREFIX_LINE, handoff.summary_text, handoff.coverage_text]
    return "\n".join(part for part in parts if part)


def markDelivery(handoff: ContextHandoff, status: str) -> None:
    """投递状态推进：仅允许 pending→injected|inline|failed；其余迁移一律抛
    ContextTransferError（含未知状态、终态回退、pending→pending）。
    """
    if status not in DELIVERY_STATES:
        raise ContextTransferError(f"未知的投递状态：{status}（合法：{DELIVERY_STATES}）")
    if handoff.delivery_status != "pending":
        raise ContextTransferError(
            f"投递状态只能从 pending 推进：当前 {handoff.delivery_status}，拒绝迁移到 {status}。"
        )
    if status == "pending":
        raise ContextTransferError("投递状态不能从 pending 迁移到 pending。")
    handoff.delivery_status = status
