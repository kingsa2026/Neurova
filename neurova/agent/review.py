# -*- coding: utf-8 -*-
"""P1-8 /review 受限子会话（Codex review task 对齐）。

- 独立 rubric 系统提示词：P0-P3 优先级标注、建议块规则、overall correctness
- 禁工具/禁网：review 调用不携带 tools（纯文本进出）
- 强制 JSON 结构化输出 + 容错解析（容忍 markdown 围栏/裸 JSON/前后缀文本）
- 解析失败如实返回 raw（parse_ok=False），不静默丢弃
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

REVIEW_SYSTEM_PROMPT = (
    "你是资深代码评审员。对给定的变更/内容做结构化评审，只输出一个 JSON 对象。\n"
    "评审规则：\n"
    "- 每条发现标注优先级：P0=致命（数据丢失/安全/崩溃）、P1=严重（功能错误）、"
    "P2=一般（可维护性/边界）、P3=建议（风格/优化）\n"
    "- 发现必须给出代码位置（文件:行号或函数名）；没有证据的猜测不要写\n"
    "- 不评价与变更无关的内容；引用项目规范时先核对是否真实存在\n"
    "- 最终给出 overall_correctness（correct / issues_found / fundamentally_broken）与简短结论\n"
    "输出 JSON schema：\n"
    '{"findings": [{"title": str, "body": str, "priority": "P0"|"P1"|"P2"|"P3", '
    '"code_location": str}], "overall_correctness": str, "overall_explanation": str, '
    '"overall_confidence_score": number}'
)

_ALLOWED_PRIORITIES = ("P0", "P1", "P2", "P3")
_ALLOWED_OVERALL = ("correct", "issues_found", "fundamentally_broken")


def build_review_messages(review_target: str, focus: str = "") -> List[Dict[str, str]]:
    """组装 review 子会话消息（system=rubric，user=评审对象）。"""
    user_parts = ["<review_target>", str(review_target or ""), "</review_target>"]
    if focus:
        user_parts.append(f"重点关注：{focus}")
    return [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    """容错提取 JSON：剥 markdown 围栏 → 首个 { 到末个 } 的裸块。"""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", str(text)).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_review_output(text: str) -> Dict[str, Any]:
    """解析评审输出为结构化结果；解析失败返回 raw（parse_ok=False）。

    findings 规范化：priority 词表外落 P2、缺失字段补空串、非 list 丢弃。
    overall_correctness 词表外原样保留（模型自定义结论不篡改）。
    """
    parsed = _extract_json_block(text)
    if parsed is None:
        return {"parse_ok": False, "findings": [], "raw": str(text or "")}
    raw_findings = parsed.get("findings")
    findings: List[Dict[str, Any]] = []
    if isinstance(raw_findings, list):
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            priority = str(item.get("priority", "") or "").strip().upper()
            if priority not in _ALLOWED_PRIORITIES:
                priority = "P2"
            findings.append(
                {
                    "title": str(item.get("title", "") or ""),
                    "body": str(item.get("body", "") or ""),
                    "priority": priority,
                    "code_location": str(item.get("code_location", "") or ""),
                }
            )
    overall = str(parsed.get("overall_correctness", "") or "").strip().lower()
    if overall not in _ALLOWED_OVERALL:
        overall = overall or "issues_found"
    return {
        "parse_ok": True,
        "findings": findings,
        "overall_correctness": overall,
        "overall_explanation": str(parsed.get("overall_explanation", "") or ""),
        "overall_confidence_score": parsed.get("overall_confidence_score", 0),
    }


async def run_review(llm_chat: Callable, review_target: str, focus: str = "") -> Dict[str, Any]:
    """受限 review 子会话：llm_chat 由调用方注入（生产=agent.llm_client.chat，
    测试=替身）。不携带 tools/联网——纯文本进出，天然禁工具禁网。"""
    messages = build_review_messages(review_target, focus=focus)
    import asyncio

    response = await asyncio.to_thread(llm_chat, messages)
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    result = parse_review_output(str(content or ""))
    result["model"] = str(getattr(response, "model", "") or "")
    return result
