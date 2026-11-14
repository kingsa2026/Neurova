"""冲突裁决的 LLM 参考意见（C2，graphiti 对照批）。

规则阶梯（源钟/断言数/置信）三项均无差异时，`KnowledgeConflictJudge.decide`
只能落 manual 待人工。本模块给审批面提供**语义参考意见**：管理员在审批面板
主动触发——不进写入路径、不自动改状态，「建议不改判」（工单 007）纪律照旧。

LLM 客户端由端点层按 agent 作用域解析注入（运行时 Agent 注册表的
`agent.llm_client`），本模块只做 prompt 构造、输出解析两个纯函数＋一个
编排入口，全部可单测；解析不合法/winner 越权一律 ValueError（端点转 502），
LLM 调用失败原样上抛（端点转 503）。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

ADVICE_PROMPT_HEADER = (
    "你是知识库治理助手。下面是同一 (主体, 谓词) 上互相矛盾的事实主张。"
    "请判断它们是否构成实质矛盾，并指出当前应采信哪一条（按内容与证据判断，"
    "不按新旧先后）。只输出 JSON："
    '{"contradicts": true/false, "winner_fact_id": "<成员 fact_id 或空串>", '
    '"reason": "<一句话依据，中文>"}'
)


def buildConflictAdvicePrompt(members: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """成员事实行 → 裁决 prompt（只喂裁决需要的字段，正文截断防长文灌入）。"""
    lines = []
    for m in members:
        lines.append(
            "- fact_id=%s | 谓词=%s | 客体=%s | 内容=%s | 证据态=%s | 记录于=%s"
            % (m.get("fact_id"), m.get("predicate_term_id"), m.get("object_term"),
               str(m.get("content") or "")[:200], m.get("evidence_state"),
               m.get("recorded_at")))
    return [
        {"role": "system", "content": ADVICE_PROMPT_HEADER},
        {"role": "user", "content": "\n".join(lines)},
    ]


def parseLlmConflictAdvice(text: str, memberIds: List[str]) -> Dict[str, Any]:
    """解析 LLM 输出为结构化意见。

    不合法 JSON / winner 不在成员内一律 ValueError（诚实拒绝，不猜）；
    ```` 代码栅栏包裹的输出剥壳后解析（LLM 常见形态）。
    """
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM 意见不是 JSON 对象")
    winner = str(data.get("winner_fact_id") or "").strip()
    if winner and winner not in set(memberIds):
        raise ValueError("LLM 意见的 winner 不在冲突成员内: %r" % winner)
    return {
        "contradicts": bool(data.get("contradicts")),
        "winner_fact_id": winner,
        "reason": str(data.get("reason") or ""),
    }


async def llmConflictAdvice(llm: Any, members: List[Dict[str, Any]]) -> Dict[str, Any]:
    """编排：prompt → LLM → 解析。成员行须含 fact_id（store.conflictMembers 产物）。

    `llm.chat` 的生产实现（AgentLLMClient）是 async——本编排随之 async，
    由端点 await。此前同步调用拿到的是 coroutine，`getattr(response, "content")`
    恒空 → 解析恒 502（P1-14 双重断链的第二处）。
    """
    memberIds = [str(m.get("fact_id") or "") for m in members]
    response = await llm.chat(buildConflictAdvicePrompt(members), temperature=0.0)
    text = getattr(response, "content", "") or ""
    advice = parseLlmConflictAdvice(text, memberIds)
    advice["members"] = memberIds
    return advice
