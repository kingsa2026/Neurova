# -*- coding: utf-8 -*-
"""Dreaming 反馈采集与判定面注入（实施计划项 7 的"未尽"两半）。

采集（写侧，全部经 :mod:`neurova.cognitive_layers.dreaming` 的 ``recordClue``
门槛与显式点名语义）：

- **审批裁决反馈**：用户对工具审批请求的批准/拒绝是最诚实的显式反馈——
  ``noteApprovalDecision`` 在 approve/reject 时落一条
  ``kind="tool_approval"``、``decision="approve|deny:<命令首词>"`` 的线索。
  同类命令被拒两次 → 候选规则 → 夜间 sweep 转正。
- **回合反馈（post_chat 链）**：管线每轮后台步 ``noteTurnFeedback``——
  本轮弹过主动提问而用户在下一句表达抵触（纠偏/点名）→
  ``kind="proactive_ask"``、``decision="suppress"``；用户直接点名
  （"以后不要…"句式）→ ``kind="user_directive"``、explicit=True 单次成候选。
  无反馈信号的回合不落任何账（忽略是缺席，不是观察）。

注入（读侧，判定面**只读 active 规则**，读不到 clue/candidate）：

- ``proactiveSuppressed()``：主动提问出队前查——存在 active 的
  ``proactive_ask/suppress`` 规则即本轮不出队；
- ``approvalHint(command)``：建审批请求时生成**建议性**提示（该类命令的
  历史裁决倾向 / 命中的用户点名），写进请求 ``metadata["dreamingHint"]``，
  只改提示文案，不自动裁决。

反馈分类是确定性规则（纠偏/感谢/点名句式），不调 LLM——LLM 抽取属夜间
任务增强，未落地前采集面先以可审计的确定性口径运转。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "classifyFeedback",
    "noteTurnFeedback",
    "noteApprovalDecision",
    "proactiveSuppressed",
    "approvalHint",
    "turnFeedbackStep",
]

# ── 反馈句式（确定性分类；命中即归类，未命中即无反馈）─────────────────

#: 用户直接点名（显式规则陈述）——单次即候选
_EXPLICIT_PATTERNS = (
    re.compile(r"以后(不要|别|再也不?)"),
    re.compile(r"(记住|记牢)[，,：:]"),
    re.compile(r"(永远|今后|从今)(不要|别)"),
    re.compile(r"不要再?(问我|发|用|执行|调用)"),
    re.compile(r"以后(都|请)?(要|记得)"),
)

#: 纠偏（对上一回合产出的否定反馈）
_CORRECTION_PATTERNS = (
    re.compile(r"(理解|理解得)?(错|错了|不对)"),
    re.compile(r"不是(这样|这个|我要的)"),
    re.compile(r"我(说|问)的是"),
    re.compile(r"(重新|再)(说|答|做|来)"),
    re.compile(r"(别|不要)再?(问|烦|打扰)"),
    re.compile(r"答非所问"),
    re.compile(r"(怎么|怎么又)(问|提)"),
)

#: 感谢/肯定
_PRAISE_PATTERNS = (
    re.compile(r"(谢谢|感谢|辛苦)"),
    re.compile(r"(不错|很好|完美|厉害|到位)"),
)

#: 点名/纠偏文本进 clue decision 的截断上限
_DECISION_TEXT_MAX = 200


def classifyFeedback(text: str) -> Optional[str]:
    """确定性反馈分类：``explicit``/``correction``/``praise``/``None``。

    explicit 优先级最高（点名蕴含纠偏语义，但点名是更强的准入信号）。
    """
    t = str(text or "").strip()
    if not t:
        return None
    for p in _EXPLICIT_PATTERNS:
        if p.search(t):
            return "explicit"
    for p in _CORRECTION_PATTERNS:
        if p.search(t):
            return "correction"
    for p in _PRAISE_PATTERNS:
        if p.search(t):
            return "praise"
    return None


def _commandHead(command: str) -> str:
    """命令首词（审批线索/规则的粒度键）：规范化后取第一个 token。"""
    try:
        from neurova.security.approval_manager import ApprovalManager

        canonical = ApprovalManager.canonicalize_command(str(command or ""))
    except Exception:  # noqa: BLE001 - 归一化不可用时退原串
        canonical = str(command or "")
    head = canonical.strip().split()
    return head[0] if head else ""


# ── 采集（写侧）──────────────────────────────────────────────────────


def noteApprovalDecision(command: str, approved: bool, requestId: str = "") -> Dict[str, Any]:
    """审批裁决落线索：同命令族的反复拒绝/批准累积成规则（夜间转正）。"""
    from neurova.cognitive_layers.dreaming import recordClue

    head = _commandHead(command)
    if not head:
        return {"recorded": False, "reason": "empty_command_head"}
    decision = ("approve:" if approved else "deny:") + head
    result = recordClue(
        kind="tool_approval",
        decision=decision,
        evidence_ref=str(requestId or ""),
    )
    logger.debug(
        "Dreaming 采集：审批裁决 kind=tool_approval decision=%s recorded=%s",
        decision,
        result.get("recorded"),
    )
    return result


def noteTurnFeedback(
    userText: str,
    sessionId: str = "",
    proactiveQuestion: Optional[str] = None,
) -> Dict[str, Any]:
    """post_chat 链回合反馈采集（管线后台步调用）。

    - 本轮弹过主动提问 + 用户负反馈（纠偏/点名）→ proactive_ask/suppress 线索；
    - 用户直接点名 → user_directive 显式线索（单次成候选）；
    - 其余（含感谢、无信号）不落账——没有判定面消费的账不写（断点纪律）。
    """
    from neurova.cognitive_layers.dreaming import recordClue

    category = classifyFeedback(userText)
    if category is None:
        return {"recorded": False, "reason": "no_feedback_signal"}
    negative = category in ("explicit", "correction")
    evidence = f"session:{sessionId}" if sessionId else ""
    recorded: list = []

    if proactiveQuestion and negative:
        result = recordClue(
            kind="proactive_ask",
            decision="suppress",
            evidence_ref=evidence,
        )
        if result.get("recorded"):
            recorded.append(result)
    if category == "explicit":
        result = recordClue(
            kind="user_directive",
            decision=str(userText).strip()[:_DECISION_TEXT_MAX],
            evidence_ref=evidence,
            explicit=True,
        )
        if result.get("recorded"):
            recorded.append(result)

    if not recorded:
        return {"recorded": False, "reason": "no_consumer_for_kind", "category": category}
    return {"recorded": True, "category": category, "results": recorded}


# ── 注入（读侧：判定面只读 active）────────────────────────────────────


def proactiveSuppressed() -> bool:
    """主动提问出队前的规则闸：存在 active 的 proactive_ask/suppress 规则即抑制。

    门控关闭时一律不抑制（功能停用 = 行为回到无规则基线）。内部吞异常：
    闸故障不拦主动提问（fail-open）。
    """
    try:
        from neurova.cognitive_layers.dreaming import activeRules, dreamingEnabled

        if not dreamingEnabled():
            return False
        for rule in activeRules("proactive_ask"):
            if str(rule.get("decision") or "") == "suppress":
                return True
    except Exception as exc:  # noqa: BLE001 - 闸故障不拦主动提问
        logger.debug("proactive 规则闸跳过：%s", exc)
    return False


async def turnFeedbackStep(userText: str, sessionId: str,
                           proactiveQuestion: Optional[str]) -> Dict[str, Any]:
    """post_chat 管线的 Dreaming 反馈采集步（项 7 写侧；纯旁路）。

    用户下一句对上一回合自主行为的反馈 → 线索（分类/门槛/显式点名语义都在
    本模块）。管线只调这一针，采集失败不影响回合。
    """
    try:
        return noteTurnFeedback(
            userText=userText,
            sessionId=sessionId,
            proactiveQuestion=proactiveQuestion,
        )
    except Exception as exc:  # noqa: BLE001 - 采集旁路失败不外泄
        logger.debug("dreaming 反馈采集跳过：%s", exc)
        return {"recorded": False, "reason": f"error:{type(exc).__name__}"}


def approvalHint(command: str) -> str:
    """建审批请求时的建议性提示（只改文案，不自动裁决）。

    汇总三类 active 规则：该命令族的裁决倾向（deny:/approve:）、命中的
    用户点名（user_directive 文本含命令首词）。无命中返回空串。
    """
    from neurova.cognitive_layers.dreaming import activeRules, dreamingEnabled

    if not dreamingEnabled():
        return ""
    head = _commandHead(command)
    if not head:
        return ""
    lines: list = []
    for rule in activeRules("tool_approval"):
        decision = str(rule.get("decision") or "")
        if decision == f"deny:{head}":
            lines.append("历史反馈：该类命令曾多次被拒绝，请确认确有必要")
        elif decision == f"approve:{head}":
            lines.append("历史反馈：该类命令此前通常获批准")
    for rule in activeRules("user_directive"):
        directive = str(rule.get("decision") or "")
        if head and head in directive:
            lines.append(f"用户曾点名：{directive}")
    return "；".join(dict.fromkeys(lines))
