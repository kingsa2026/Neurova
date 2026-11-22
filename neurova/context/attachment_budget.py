# -*- coding: utf-8 -*-
"""附件注入预算判据（P1-5 · 上下文工程十轴 轴 7）。

附件正文在本轮 `build_context` **之前**并入 `user_input`（chat_pipeline 的
Step 0.7/1.5）。没有预算闸时，大附件会把窗口直接顶过压缩触发线
（预算 × `CONTEXT_COMPACT_TRIGGER_RATIO`），"附件永不触发压缩"就落空。

本模块是附件预算的**唯一判据出处**：

- 逐附件决策 `full`（全文并入）/ `preview`（截断预览 + 句柄说明）；
- **硬约束**：计划总量（含预览与句柄说明）≤ `remaining_budget_tokens`；
- 预览裁剪复用 `fold_resolution.fitToBudget` 的"按预算裁到最长的保留开头"
  while-keep 收敛模式与 `TRUNCATION_MARK` 形态（估算尺非线性，单次比例会
  溢出，须线性收敛）；token 计量只走 `neurova.context.token_estimator`
  单源，本模块不自带第二把尺（`estimator` 参数仅供判据测试注入确定性尺子）；
- `remaining_budget_tokens` 为 None/负值 ⇒ 透传计划（调用方无预算信息时
  行为与既往一致，不造数）；`attachments` 为空 ⇒ 空 plan。

句柄口径沿用既有约定（`composeUnparseableAttachmentNotice`）：附件落在
`data/storage/users/**`，取用凭证只有 `file_id`，服务端路径不对外。预览被裁
时必须把句柄一并交给模型，"这里被裁过、完整件在哪"才对模型可见、可补救。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from neurova.context.fold_resolution import TRUNCATION_MARK

#: 预览段首说明：诚实标注"这是被预算截断的预览"，不冒充全文。
PREVIEW_HEADER_TEMPLATE = (
    "[用户上传了文件 {filename}，以下为该文件的内容预览"
    "（因本轮上下文预算截断，完整内容未并入）]"
)

#: 句柄说明：与抽取失败通知的句柄句同口径——取用一律凭 file_id。
HANDLE_NOTE_TEMPLATE = "附件句柄 file_id={file_id}（服务端路径不对外，取用一律凭该句柄）"

#: 连预览都放不下时的最小留痕（句柄仍在，不静默消失）。
OMITTED_NOTICE_TEMPLATE = "[用户上传了文件 {filename}（内容因本轮窗口预算未并入）]"

DECISION_FULL = "full"
DECISION_PREVIEW = "preview"

Estimator = Callable[[str], int]


@dataclass
class AttachmentBudgetItem:
    """单个附件的预算判据输入（纯数据，无 I/O）。"""

    file_id: str = ""
    filename: str = ""
    file_type: str = ""
    #: 全文并入时的完整段落（含说明行；抽取失败的通知文本也在这里）。
    full_text: str = ""
    #: 可截断正文（preview 只裁这里；通知类附件为空串）。
    body: str = ""


@dataclass
class AttachmentInjectionDecision:
    """单个附件的注入决策（字段可序列化、可读）。"""

    file_id: str
    filename: str
    file_type: str
    #: "full"（全文并入）| "preview"（截断预览 + 句柄说明）。
    decision: str
    #: 计划并入本轮的最终文本段；空串 = 预算内放不下任何内容（诚实空置）。
    injected_text: str
    #: injected_text 的计划占用（含预览与句柄说明）。
    used_tokens: int
    #: 全文并入本需的 token（读数用）。
    full_tokens: int
    #: preview 实际保留的正文长度（full 时为 0）。
    preview_chars: int
    #: 被裁掉的正文长度。
    truncated_chars: int
    #: 句柄说明（full 时为空串）。
    handle_note: str

    def toDict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AttachmentInjectionPlan:
    """一轮附件注入的总体计划。"""

    decisions: List[AttachmentInjectionDecision]
    remaining_budget_tokens: Optional[int]
    #: True = 调用方无预算信息，全量并入透传（行为与既往一致）。
    passthrough: bool

    @property
    def total_used_tokens(self) -> int:
        return sum(d.used_tokens for d in self.decisions)

    def isValid(self) -> bool:
        """硬约束自检：透传不受预算约束；否则计划总量不得超预算。"""
        if self.passthrough or self.remaining_budget_tokens is None:
            return True
        return self.total_used_tokens <= int(self.remaining_budget_tokens)

    def toDict(self) -> Dict[str, Any]:
        return {
            "passthrough": self.passthrough,
            "remaining_budget_tokens": self.remaining_budget_tokens,
            "total_used_tokens": self.total_used_tokens,
            "decisions": [d.toDict() for d in self.decisions],
        }


def _defaultEstimator(text: str) -> int:
    from neurova.context.token_estimator import estimate_tokens

    return estimate_tokens(text or "")


def _coerceItem(raw: Union[AttachmentBudgetItem, Dict[str, Any]]) -> AttachmentBudgetItem:
    if isinstance(raw, AttachmentBudgetItem):
        return raw
    if isinstance(raw, dict):
        return AttachmentBudgetItem(
            file_id=str(raw.get("file_id") or ""),
            filename=str(raw.get("filename") or ""),
            file_type=str(raw.get("file_type") or ""),
            full_text=str(raw.get("full_text") or ""),
            body=str(raw.get("body") or ""),
        )
    raise TypeError(f"附件预算判据的输入形态不支持：{type(raw)!r}")


def _handleNote(file_id: str) -> str:
    return HANDLE_NOTE_TEMPLATE.format(file_id=file_id) if file_id else ""


def _previewDecision(
    item: AttachmentBudgetItem, remaining: int, est: Estimator
) -> AttachmentInjectionDecision:
    """超预算附件的预览决策：保留开头的截断预览 + 句柄说明。

    裁剪模式与 `fold_resolution.fitToBudget` 同源：先按 token 比例估保留
    字符数，再线性收敛到"整段预览（含说明行与句柄）不超剩余预算"；裁过
    补 `TRUNCATION_MARK`，让"这里被裁过"对模型可见。连句柄留痕都放不下时
    诚实空置（硬约束优先，附件不把窗口顶过触发线）。
    """
    fullTokens = est(item.full_text) if item.full_text else 0
    header = PREVIEW_HEADER_TEMPLATE.format(filename=item.filename)
    handle = _handleNote(item.file_id)
    body = item.body or ""

    if body:
        tail = f"\n{handle}" if handle else ""
        whole = f"{header}\n{body}{tail}"
        if est(whole) <= remaining:
            # 剩余空间容得下整个正文：预览形态承载全文（无截断标记）。
            keep = len(body)
        else:
            keep = max(0, int(len(body) * (remaining / max(1, est(whole)))))
            while (
                keep > 0
                and est(f"{header}\n{body[:keep]}{TRUNCATION_MARK}{tail}") > remaining
            ):
                keep = int(keep * 0.9) if keep > 10 else keep - 1
        if keep > 0:
            truncated = keep < len(body)
            fitted = body[:keep] + (TRUNCATION_MARK if truncated else "")
            injected = f"{header}\n{fitted}{tail}"
            return AttachmentInjectionDecision(
                file_id=item.file_id,
                filename=item.filename,
                file_type=item.file_type,
                decision=DECISION_PREVIEW,
                injected_text=injected,
                used_tokens=est(injected),
                full_tokens=fullTokens,
                preview_chars=keep,
                truncated_chars=len(body) - keep,
                handle_note=handle,
            )

    # 无正文（通知类）或正文一个字都放不下：退化为"只留句柄"的最小留痕。
    minimal = " ".join(
        x
        for x in (OMITTED_NOTICE_TEMPLATE.format(filename=item.filename), handle)
        if x
    )
    if minimal and est(minimal) <= remaining:
        return AttachmentInjectionDecision(
            file_id=item.file_id,
            filename=item.filename,
            file_type=item.file_type,
            decision=DECISION_PREVIEW,
            injected_text=minimal,
            used_tokens=est(minimal),
            full_tokens=fullTokens,
            preview_chars=0,
            truncated_chars=len(body),
            handle_note=handle,
        )
    return AttachmentInjectionDecision(
        file_id=item.file_id,
        filename=item.filename,
        file_type=item.file_type,
        decision=DECISION_PREVIEW,
        injected_text="",
        used_tokens=0,
        full_tokens=fullTokens,
        preview_chars=0,
        truncated_chars=len(body),
        handle_note=handle,
    )


def _fullDecision(item: AttachmentBudgetItem, est: Estimator) -> AttachmentInjectionDecision:
    fullTokens = est(item.full_text) if item.full_text else 0
    return AttachmentInjectionDecision(
        file_id=item.file_id,
        filename=item.filename,
        file_type=item.file_type,
        decision=DECISION_FULL,
        injected_text=item.full_text,
        used_tokens=fullTokens,
        full_tokens=fullTokens,
        preview_chars=0,
        truncated_chars=0,
        handle_note="",
    )


def planAttachmentInjection(
    *,
    attachments: Sequence[Union[AttachmentBudgetItem, Dict[str, Any]]],
    remaining_budget_tokens: Optional[int],
    estimator: Optional[Estimator] = None,
) -> AttachmentInjectionPlan:
    """附件注入预算判据（纯函数，同输入同计划）。

    - 逐附件按序贪心：先到先得；预算内 `full` 全文并入，超预算 `preview`
      （截断预览 + 句柄说明），预览长度按剩余预算贪心分配；
    - **硬约束**：计划总量（含预览与句柄说明）≤ `remaining_budget_tokens`
      —— 附件永不把窗口顶过压缩触发线；
    - `remaining_budget_tokens` 为 None/负值 ⇒ 返回"全量并入"的透传计划
      （调用方无预算信息时行为与现状一致，不造数）；
    - `attachments` 为空 ⇒ 空 plan。
    """
    est = estimator or _defaultEstimator
    items = [_coerceItem(a) for a in (attachments or [])]

    budget = None if remaining_budget_tokens is None else int(remaining_budget_tokens)
    if budget is not None and budget < 0:
        budget = None  # 负值视同"无预算信息"：透传，不造数

    if budget is None:
        return AttachmentInjectionPlan(
            decisions=[_fullDecision(i, est) for i in items],
            remaining_budget_tokens=None,
            passthrough=True,
        )

    decisions: List[AttachmentInjectionDecision] = []
    used = 0
    for item in items:
        fullTokens = est(item.full_text) if item.full_text else 0
        if used + fullTokens <= budget:
            decisions.append(_fullDecision(item, est))
            used += fullTokens
            continue
        decision = _previewDecision(item, budget - used, est)
        decisions.append(decision)
        used += decision.used_tokens

    return AttachmentInjectionPlan(
        decisions=decisions,
        remaining_budget_tokens=budget,
        passthrough=False,
    )


__all__ = [
    "DECISION_FULL",
    "DECISION_PREVIEW",
    "HANDLE_NOTE_TEMPLATE",
    "OMITTED_NOTICE_TEMPLATE",
    "PREVIEW_HEADER_TEMPLATE",
    "AttachmentBudgetItem",
    "AttachmentInjectionDecision",
    "AttachmentInjectionPlan",
    "planAttachmentInjection",
]
