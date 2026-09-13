# -*- coding: utf-8 -*-
"""RAG 评估数据集自动出题（P1 #5，对位 Yuxi benchmark_generation 的裁剪版）。

锚点=可见知识条目的块（`knowledge_id#chunk_index`），上下文取锚块+同条目
邻居窗口（Yuxi 的 vector/graph_enhanced 邻居扩散依赖 Milvus/Neo4j，NV 零
依赖形态用"同条目邻块窗口"作邻居源——gold_chunk_ids 因此天然落在条目内，
跨条目干扰题不生成，如实标注 limit 而非假装全覆盖）。

llm_fn 注入式（生产端点装配默认 LLM）：无注入如实报错，不伪造题目；
LLM 输出经 json_repair 风格容错（剥代码栅栏/取首个 {...}）。
"""
from __future__ import annotations

import random
import re
from typing import Any, Callable, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

PROMPT_TEMPLATE = (
    "你是知识库出题助手。基于下面给出的知识块内容，写一条**仅凭该内容即可回答**"
    "的问题和对应答案。要求：问题具体、答案简短（≤80字），不得引用块外信息。\n\n"
    "块内容（chunk_id={chunk_id}，标题《{title}》）：\n{context}\n\n"
    '仅输出 JSON：{{"question": "...", "answer": "..."}}'
)


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 回复提取首个 JSON 对象（剥 ``` 栅栏）。"""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?|```", "", text)
    m = re.search(r"\{.*\}", cleaned, re.S)
    if not m:
        return None
    try:
        import json

        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


def generate_items(
    items: List[Dict[str, Any]],
    sample_n: int = 10,
    neighbors: int = 1,
    llm_fn: Optional[Callable[[str], str]] = None,
    rng_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """从可见知识条目采样锚块并经 LLM 出题。

    Args:
        items: 知识条目列表（含 knowledge_id/title/chunks 或 content）
        sample_n: 采样锚块数（实际=min(可用块数, sample_n)）
        neighbors: 锚块上下文扩展的同条目左右邻块数（0–10）
        llm_fn: prompt→回复文本；None=如实拒绝
    Returns:
        {generated, sampled, skipped, dataset:{name, items:[{query,
        gold_chunk_ids, gold_answer}]}} 或 {error}
    """
    if llm_fn is None:
        return {"error": "自动出题需要 LLM 通道（llm_fn 未注入/模型不可用），拒绝伪造题目"}

    rng = random.Random(rng_seed)
    anchors: List[Dict[str, Any]] = []  # {chunk_id, context, title}
    for it in items:
        kid = str(it.get("knowledge_id") or "")
        if not kid:
            continue
        chunks = it.get("chunks") or []
        title = str(it.get("title") or "")
        content = str(it.get("content") or "")
        for idx in range(len(chunks)):
            ch = chunks[idx]
            chunk_text = ch.get("content") or content[ch.get("char_start", 0): ch.get("char_end", 0)]
            if not str(chunk_text).strip():
                continue
            ctx_parts = []
            lo, hi = max(0, idx - neighbors), min(len(chunks), idx + neighbors + 1)
            for j in range(lo, hi):
                cj = chunks[j]
                t = cj.get("content") or content[cj.get("char_start", 0): cj.get("char_end", 0)]
                ctx_parts.append(str(t))
            anchors.append({
                "chunk_id": f"{kid}#{idx}",
                "title": title,
                "context": "\n".join(ctx_parts)[:4000],
            })

    if not anchors:
        return {"error": "可见知识条目中没有可出题的块", "generated": 0, "sampled": 0, "skipped": 0}

    rng.shuffle(anchors)
    picked = anchors[: max(0, int(sample_n))]
    out_items: List[Dict[str, Any]] = []
    skipped = 0
    for a in picked:
        prompt = PROMPT_TEMPLATE.format(chunk_id=a["chunk_id"], title=a["title"], context=a["context"])
        try:
            reply = llm_fn(prompt)
        except Exception as e:  # noqa: BLE001 - 单题 LLM 失败不中断批次
            logger.warning("自动出题 LLM 调用失败（跳过该块）: %s", e)
            skipped += 1
            continue
        parsed = _extract_json(reply or "")
        question = str((parsed or {}).get("question") or "").strip()
        answer = str((parsed or {}).get("answer") or "").strip()
        if not question:
            skipped += 1
            continue
        out_items.append({
            "query": question,
            "gold_chunk_ids": [a["chunk_id"]],
            "gold_answer": answer or None,
        })
    return {
        "generated": len(out_items),
        "sampled": len(picked),
        "skipped": skipped,
        "dataset": {
            "name": f"自动出题 {len(out_items)} 题",
            "description": "邻居窗口=同条目 ±%d 块；gold 锚块精确标注" % neighbors,
            "items": out_items,
        },
    }
