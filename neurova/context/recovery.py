"""
上下文溢出恢复（P1-1① 期①，对标 QP scroll 的单次恢复重试语义）

三个纯函数，零 I/O：
- assign_turn_ids：给对话消息序列标注轮次 id（写入侧配对锚点的依据）
- is_context_overflow_error：判定异常是否为上下文窗口溢出（类型或报错文本）
- compact_messages_for_overflow：把超窗消息折叠为可单次重试的紧凑序列

折叠策略：
- 全部 system 消息保留（角色契约）
- 第一条 user 消息保留（任务锚点）
- 末尾 recent_keep 条原样保留（近期上下文完整）
- 其余中段折叠为一条恢复桩；切割点回退对齐到轮次边界——
  assistant(tool_calls) 与其后 tool 结果同进同出，绝不允许孤儿 tool 消息
  （OpenAI 协议要求 tool 消息必须紧跟带 tool_calls 的 assistant）
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_RECOVERY_STUB_PREFIX = "[context recovery:"
_OVERFLOW_PATTERNS = (
    re.compile(r"maximum context length", re.IGNORECASE),
    re.compile(r"context[_ ]length[_ ]exceeded", re.IGNORECASE),
    re.compile(r"too many tokens", re.IGNORECASE),
    re.compile(r"context window", re.IGNORECASE),
    re.compile(r"request too large", re.IGNORECASE),
)


def assign_turn_ids(messages: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], str]]:
    """给对话消息序列标注轮次 id：每条 user 消息开启新轮（turn_N 递增）。

    user 消息是轮次的锚点——TOOL_CALL 等 chunk 的 pairs_with 指向 turn_id
    即可表达"属于哪一轮"（写入侧契约，见 pairing.validate_pairing）。
    """
    tagged: List[Tuple[Dict[str, Any], str]] = []
    current = 0
    for msg in messages:
        role = (msg or {}).get("role", "user")
        if role == "user":
            current += 1
        tagged.append((msg, f"turn_{max(current, 1)}"))
    return tagged


def is_context_overflow_error(exc: BaseException) -> bool:
    """判定异常是否为上下文窗口溢出：类型（TokenLimitExceeded）或报错文本。"""
    try:
        from neurova.llm_client import TokenLimitExceeded

        if isinstance(exc, TokenLimitExceeded):
            return True
    except ImportError:  # pragma: no cover - 可选依赖缺失时退化为文本判定
        pass
    message = str(exc or "")
    return any(p.search(message) for p in _OVERFLOW_PATTERNS)


def _is_tool_result(msg: Dict[str, Any]) -> bool:
    return (msg or {}).get("role") == "tool"


def _opens_tool_block(msg: Dict[str, Any]) -> bool:
    """assistant 消息且携带 tool_calls——工具轮块的起始边界。"""
    return (msg or {}).get("role") == "assistant" and bool(msg.get("tool_calls"))


# ── tool-turn 修复（OpenOcta 启发 P1-7：toolTurnRepair） ──────────────────


def _synth_tool_result(calls_seen: List[str]) -> str:
    return (
        f"{_RECOVERY_STUB_PREFIX} 工具调用 {', '.join(calls_seen)} 的结果已在上下文折叠时"
        "摘要化；如需细节请重新调用该工具。]"
    )


def repair_tool_turns(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """折叠/压缩/视图重建后修复 tool_use/tool_result 配对完整性。

    两类协议断裂（OpenAI 语义，违反即 400）：
    - 孤儿 tool 消息：tool_call_id 不在任何前文 assistant.tool_calls 中
      → 剥离为普通 user 注记（保留信息量，角色合法）
    - 悬空 tool_calls：assistant 声明了调用但结果缺失/被折掉
      → 就地补合成 tool 结果（"已折叠"说明），保持配对闭合

    纯函数：返回新列表，不修改输入；非 tool 语义消息原样保留。

    接线点（OpenOcta 思想：修复链放在"最后进入模型前"，任何上游折叠
    策略变化都无需各自重推配对规则）：
    - context.orchestrator.build_context：视图重建剥 tool_calls 后的
      残留 role:"tool"（caller_provided_history/渠道回传混入）
    - 本模块 compact_messages_for_overflow 的消费方可按需二次调用兜底
    """
    if not messages:
        return []

    # 前向扫描：记录每个 tool_call_id 是否已被某个 assistant.tool_calls 声明
    declared_ids: set = set()
    for msg in messages:
        if _opens_tool_block(msg):
            for call in msg.get("tool_calls") or []:
                cid = (call or {}).get("id") if isinstance(call, dict) else None
                if cid:
                    declared_ids.add(cid)

    out: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            out.append(msg)
            continue

        if _is_tool_result(msg):
            cid = msg.get("tool_call_id")
            if cid and cid in declared_ids:
                out.append(msg)  # 配对完整，原样保留
            else:
                # 孤儿 tool 结果 → 转为 user 注记（不丢信息，协议合法）
                content = msg.get("content", "")
                tool_name = msg.get("name") or msg.get("tool_name") or "tool"
                out.append({
                    "role": "user",
                    "content": (
                        f"[{tool_name} 结果（tool_call_id={cid or '未知'}，"
                        f"前文工具调用已折叠）] {content}"
                    ),
                })
            continue

        out.append(msg)

    # 第二遍：补齐悬空 tool_calls（扫描产出序列中每个 assistant 声明的 id
    # 是否都在其后的连续 tool 段中有结果；缺 → 就地插入合成结果）
    repaired: List[Dict[str, Any]] = []
    i = 0
    n = len(out)
    while i < n:
        msg = out[i]
        repaired.append(msg)
        if _opens_tool_block(msg):
            calls = [c for c in (msg.get("tool_calls") or []) if isinstance(c, dict)]
            expected_ids = [c.get("id") for c in calls if c.get("id")]
            # 收集紧随其后的 tool 消息段
            j = i + 1
            seen_ids: set = set()
            while j < n and _is_tool_result(out[j]):
                seen_ids.add(out[j].get("tool_call_id"))
                repaired.append(out[j])
                j += 1
            missing = [cid for cid in expected_ids if cid not in seen_ids]
            if missing:
                repaired.append({
                    "role": "tool",
                    "tool_call_id": missing[0] if len(missing) == 1 else ",".join(map(str, missing)),
                    "name": calls[0].get("function", {}).get("name", "tool") if calls else "tool",
                    "content": _synth_tool_result([str(c) for c in missing]),
                })
            i = j
            continue
        i += 1

    return repaired


def compact_messages_for_overflow(
    messages: List[Dict[str, Any]],
    recent_keep: int = 6,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """把超窗消息折叠为可单次重试的紧凑序列。

    Args:
        messages: 原始消息序列（OpenAI 格式）
        recent_keep: 末尾原样保留的消息条数（近期上下文）

    Returns:
        (compact_messages, info)
        info: {folded_count, original_count, compact_count}
        folded_count == 0 表示无需折叠（原序列已足够紧凑）
    """
    if not messages:
        return [], {"folded_count": 0, "original_count": 0, "compact_count": 0}

    original_count = len(messages)

    # 1) system 全保留（顺序保持）
    system_idx = [i for i, m in enumerate(messages) if (m or {}).get("role") == "system"]
    system_set = set(system_idx)

    # 2) 任务锚点：第一条非 system 的 user 消息
    anchor_idx = next(
        (i for i, m in enumerate(messages)
         if i not in system_set and (m or {}).get("role") == "user"),
        None,
    )

    # 3) 近期保留区起点：len - recent_keep，向前回退对齐到轮次边界
    #    （边界落在 tool 结果或工具块中间会破坏协议配对）
    cut = max(original_count - max(recent_keep, 0), 0)
    while cut > 0 and _is_tool_result(messages[cut]):
        cut -= 1
    # 边界不得切进"assistant(tool_calls) → tool…"块中间：若 cut 处消息的
    # 前驱是 opens_tool_block 的 assistant，整体再前移一位
    if 0 < cut < original_count and _opens_tool_block(messages[cut - 1]):
        cut -= 1
    # 至少保留锚点之后的区域，避免把锚点也折进去
    if anchor_idx is not None and cut <= anchor_idx:
        cut = anchor_idx + 1

    keep_recent = list(range(cut, original_count))
    keep_all = set(system_idx) | set(keep_recent)
    if anchor_idx is not None:
        keep_all.add(anchor_idx)

    # 4) 中段是否为空（无折叠必要）
    middle_idx = [i for i in range(original_count) if i not in keep_all]
    if not middle_idx:
        return list(messages), {
            "folded_count": 0,
            "original_count": original_count,
            "compact_count": len(messages),
            "folded_messages": [],
        }

    # 5) 装配：system… → 锚点 → 恢复桩 → 近期区
    compact: List[Dict[str, Any]] = []
    for i in sorted(system_idx):
        compact.append(messages[i])
    if anchor_idx is not None and anchor_idx not in system_idx:
        compact.append(messages[anchor_idx])
    compact.append({
        "role": "user",
        "content": (
            f"{_RECOVERY_STUB_PREFIX} {len(middle_idx)} 条早期消息已折叠以容纳上下文窗口；"
            "如需其中细节请明确说明。]"
        ),
    })
    for i in keep_recent:
        compact.append(messages[i])

    info = {
        "folded_count": len(middle_idx),
        "original_count": original_count,
        "compact_count": len(compact),
        # 增强①：暴露被折叠消息（溢出恢复路径据此生成摘要回写池）
        "folded_messages": [messages[i] for i in middle_idx],
    }
    return compact, info
