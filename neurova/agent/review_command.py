# -*- coding: utf-8 -*-
"""P1-8 命令面：/review 聊天命令（受限评审子会话）。

- /review            → 以最近会话历史（≤12 条）为评审对象
- /review <内容>     → 直接评审给定 diff/文本
- 复用 agent/review.run_review（禁工具禁网、结构化 findings、容错解析）
- 交互契约与 /compact 同构：command_dispatched 短路 LLM + emitter 直发
"""
from __future__ import annotations

from typing import Any, Dict

_REVIEW_TARGET_MAX_CHARS = 24000
_REVIEW_HISTORY_MESSAGES = 12
_PRIORITY_ORDER = ("P0", "P1", "P2", "P3")


def format_review_reply(result: Dict[str, Any]) -> str:
    """run_review 结果 → 聊天回复文本。"""
    if not result.get("parse_ok"):
        raw = str(result.get("raw", ""))
        return "🔍 评审完成（模型未返回结构化结果，原文如下）：\n\n" + raw[:2000]
    findings = result.get("findings") or []
    lines = []
    for prio in _PRIORITY_ORDER:
        for f in findings:
            if f.get("priority") != prio:
                continue
            loc = f.get("code_location") or ""
            head = f"**{prio}** {f.get('title', '')}"
            if loc:
                head += f" — `{loc}`"
            lines.append(head)
            body = str(f.get("body", "") or "").strip()
            if body:
                lines.append(body)
            lines.append("")
    if not lines:
        lines.append("未发现需要处理的问题。")
    overall = str(result.get("overall_correctness", ""))
    overall_map = {
        "correct": "✅ 总体正确",
        "issues_found": "⚠️ 发现问题",
        "fundamentally_broken": "❌ 存在根本性问题",
    }
    summary = overall_map.get(overall, overall)
    explanation = str(result.get("overall_explanation", "") or "").strip()
    if explanation:
        summary += f"：{explanation}"
    return "🔍 评审结果\n\n" + "\n".join(lines).rstrip() + "\n\n" + summary


def extract_review_target(raw_text: str) -> Any:
    """/review [内容] → 评审对象。

    非 /review 命令返回 None（调用方跳过）；/review 无内容返回空串
    （调用方回落会话历史）。词边界：/reviews、/reviewxyz 不算命中。
    """
    text = (raw_text or "").strip()
    if not text.lower().startswith("/review"):
        return None
    rest_raw = text[len("/review"):]
    # 词边界：命令后必须是串尾或空白（/reviews 的 "s" 不是参数）
    if rest_raw and not rest_raw[0].isspace():
        return None
    return rest_raw.strip()


def build_history_target(history: list) -> str:
    """会话历史 → 评审对象文本（role 标注，截断到预算）。"""
    lines = []
    for m in history or []:
        role = str((m or {}).get("role", "user"))
        content = str((m or {}).get("content", "") or "")
        if content:
            lines.append(f"[{role}] {content}")
    return "\n".join(lines)[:_REVIEW_TARGET_MAX_CHARS]
