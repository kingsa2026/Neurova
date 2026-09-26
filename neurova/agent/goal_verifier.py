# -*- coding: utf-8 -*-
"""目标达成判定子会话（G2 验收执行器）。

纪律与 /review 的受限子会话同族：
- **禁工具**：不携带 `tools`。判定"是否完成"不能产生副作用——否则判据会去
  推进它要衡量的那件事（判据自我污染）。
- **强制 JSON + 容错解析**，解析失败如实返回 `parse_ok=False`，不静默丢弃，
  也绝不因判据坏掉而阻断正常回复。
- **通道由调用方注入**：生产注入 `agent.llm_client.chat`，与正文生成走同一张
  路由与同一本 token 账（`MultiModelLLMClient.chat` 内每次调用都经
  `usage_accounting.record` 入账），判定调用因此不游离于账本外。
- **成本可见**：本模块**不新建第二个客户端**，全链只有调用方这一条通道。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

from neurova.agent.sub_session import callSubSessionChannel
from neurova.core.logger import get_logger

logger = get_logger(__name__)

GOAL_VERIFY_SYSTEM_PROMPT = (
    "你是目标验收判定员。依据给定的目标与证据，判断目标是否**已完成**，只输出一个 JSON 对象。\n"
    "判定规则：\n"
    "- 只依据证据里出现的事实判定，不推测证据之外的工作；证据没提到的内容一律记为未完成\n"
    "- 目标条目多于一条时，任一条没有证据支持即为未完成\n"
    "- achieved 为 false 时，missing 必须逐条点名缺什么（可执行、可核对），不得只写“未完成”\n"
    "- confidence 用 0~1 表示判定把握；把握不足时如实给低分\n"
    "输出 JSON schema：\n"
    '{"achieved": bool, "confidence": number, "missing": [str], "explanation": str}'
)


def _extractJsonBlock(text: str) -> Optional[Dict[str, Any]]:
    """容错提取 JSON：剥 markdown 围栏 → 首个 `{` 到末个 `}` 的裸块。"""
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


def parseGoalVerdict(text: str) -> Dict[str, Any]:
    """解析判定输出；解析失败返回 `parse_ok=False` 与原样正文（不静默丢弃）。"""
    parsed = _extractJsonBlock(text)
    if parsed is None:
        return {"parse_ok": False, "raw": str(text or "")}
    achieved = parsed.get("achieved")
    if not isinstance(achieved, bool):
        # `achieved` 缺失或非布尔即判据不可用：不猜成 True（那等于放行假完成），
        # 也不猜成 False（那会凭空多续跑一轮）。
        return {"parse_ok": False, "raw": str(text or "")}
    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    missing = parsed.get("missing")
    return {
        "parse_ok": True,
        "achieved": achieved,
        "confidence": max(0.0, min(1.0, confidence)),
        "missing": [str(item) for item in missing if str(item or "").strip()]
        if isinstance(missing, list)
        else [],
        "explanation": str(parsed.get("explanation") or ""),
    }


def buildGoalVerifyMessages(goal: Any, evidence: str) -> List[Dict[str, str]]:
    """组装判定子会话消息：system=rubric，user=目标 + 本轮证据。"""
    criteria = list(getattr(goal, "successCriteria", ()) or ())
    goalLines = [f"目标：{getattr(goal, 'statement', '')}"]
    if criteria:
        goalLines.append("成功条目：")
        goalLines.extend(f"- {item}" for item in criteria)
    return [
        {"role": "system", "content": GOAL_VERIFY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "\n".join(
                ["<goal>", *goalLines, "</goal>", "<evidence>", str(evidence or ""), "</evidence>"]
            ),
        },
    ]


async def verifyGoalCompletion(
    llmChat: Callable, goal: Any, evidence: str
) -> Dict[str, Any]:
    """受限目标验收子会话。

    `llmChat` 由调用方注入（生产 = `agent.llm_client.chat`，测试 = 替身）。
    不携带 tools；通道形态由 `callSubSessionChannel` 单源兼容。
    """
    messages = buildGoalVerifyMessages(goal, evidence)
    try:
        response = await callSubSessionChannel(llmChat, messages)
    except Exception as e:  # noqa: BLE001 - 判定不可用不阻断回复
        logger.warning("目标验收子会话调用失败（按未判定处理）: %s", e)
        return {"parse_ok": False, "raw": f"channel_error: {e}"}
    content = getattr(response, "content", None)
    if content is None and isinstance(response, dict):
        content = response.get("content")
    verdict = parseGoalVerdict(str(content or ""))
    verdict["model"] = str(getattr(response, "model", "") or "")
    return verdict
