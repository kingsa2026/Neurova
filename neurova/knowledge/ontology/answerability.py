# -*- coding: utf-8 -*-
"""answerability 实体覆盖预检（对照研究 P1-3，2026-11-15）。

问题进来先回答「这个数据面答得了吗」：抽问题实体 → 对本体术语/事实主体
做覆盖匹配 → 命中占比即 coverage。不写 SQL、不跑推理——给代理一个廉价的
预检，coverage 低就反问澄清，而不是花大钱生成一个必然落空的答案
（对方 README 示例：问广告 ROI，coverage 0.5、无 term 覆盖 "ad spend"）。

批次边界（如实登记）：
- 实体抽取：llmCall 给了用 LLM（JSON）；没给用确定性分词（CJK 串＋拉丁词）；
- 匹配是**词面**的（精确/前缀/包含，归一后比对）；向量召回属后续升级，
  不在本批冒充；
- 判据单一：本模块是唯一覆盖度计算处，端点与 MCP 工具都转交它。
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}")
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)

#: 通用停用词（问句骨架词；不做语言全覆盖，命中不足时宁可低报 coverage）
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "for", "to", "in", "on", "at", "by", "with",
    "is", "are", "was", "were", "be", "been", "do", "does", "did", "what",
    "which", "who", "whom", "how", "when", "where", "why", "and", "or",
    "not", "no", "yes", "it", "its", "this", "that", "these", "those",
    "please", "can", "could", "would", "should", "tell", "show", "give",
    "me", "my", "our", "us", "we", "you", "your", "there", "here",
    # 中文骨架词（jieba 切出的连接/语气成分不进实体）
    "和", "的", "了", "吗", "呢", "吧", "啊", "在", "是", "有", "与", "及",
    "对", "从", "被", "把", "给", "向", "往", "于", "之", "或", "且", "但",
    "而", "不", "没", "无", "本", "该", "各", "每", "约", "近", "超", "请",
    "告诉", "看看", "查询", "统计", "多少", "怎么", "如何", "什么", "哪些",
})

_LLM_ENTITY_PROMPT = """从问题中抽取提问所依赖的业务实体/概念词（不要动词、不要纯修饰词）。
输出严格 JSON（不要解释）：{{"entities": ["...", "..."]}}
问题：{question}"""


def _parseLlmEntities(text: str) -> List[str]:
    match = _FENCE_RE.search(text)
    raw = match.group(1) if match else text
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(raw[start:end + 1])
    except Exception:  # noqa: BLE001 - LLM 输出不可信
        return []
    entities = data.get("entities") if isinstance(data, dict) else None
    if not isinstance(entities, list):
        return []
    return [str(e).strip() for e in entities if str(e).strip()]


def extractEntities(question: str, llmCall: Optional[Callable[[str], str]] = None,
                    maxEntities: int = 8) -> List[str]:
    """问题 → 实体词清单。LLM 优先，失败/缺席回退确定性分词（诚实降级）。

    CJK 段用 jieba 切词（仓内既有依赖，惰性 import；缺席退回整段 CJK 串），
    拉丁词直接取 token；骨架停用词过滤。"""
    question = str(question or "").strip()
    if not question:
        return []
    if llmCall is not None:
        try:
            entities = _parseLlmEntities(llmCall(_LLM_ENTITY_PROMPT.format(
                question=question[:500])))
            if entities:
                return entities[:maxEntities]
        except Exception:  # noqa: BLE001 - 抽取失败回退分词
            pass
    entities: List[str] = []
    for run in _CJK_RUN.findall(question):
        cut = _segmentCjk(run)
        entities.extend(cut if cut else [run])
    for word in _LATIN_WORD.findall(question):
        if word.lower() not in _STOPWORDS:
            entities.append(word)
    return entities[:maxEntities]


def _segmentCjk(run: str) -> List[str]:
    """CJK 串 → 词清单（jieba 惰性；切不出/全停用词时回空由调用方兜底整段）。"""
    try:
        import jieba

        words = [w.strip() for w in jieba.lcut(run)]
    except Exception:  # noqa: BLE001 - 分词器缺席回退不切
        return [run]
    return [w for w in words
            if len(w) >= 2 and w not in _STOPWORDS and _CJK_RUN.search(w)]


def _normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", str(text or "")).lower()


def assessAnswerability(store: Any, question: str, tenantId: str = "default",
                        agentId: str = "default",
                        llmCall: Optional[Callable[[str], str]] = None,
                        threshold: float = 0.5, maxEntities: int = 8) -> Dict[str, Any]:
    """覆盖度预检（只读）：{"coverage", "answerable", "entities", "threshold"}。

    匹配源两路：本体术语（term_id/label/别名，租户分区）＋事实主体
    （canonical/normalized label/别名，agent 分区）。都不命中即 uncovered。
    """
    from .term_registry import OntologyTermRegistry

    tenant = str(tenantId or "default")
    entities = extractEntities(question, llmCall=llmCall, maxEntities=maxEntities)
    if not entities:
        return {"coverage": 0.0, "answerable": False, "threshold": threshold,
                "entities": [], "note": "未抽到实体——问题过短或全为骨架词"}

    registry = OntologyTermRegistry(store)
    termCandidates: List[Dict[str, Any]] = []
    for term in registry.terms(tenantId=tenant):
        names = [str(term.get("term_id") or ""), str(term.get("label") or "")]
        names += [str(a) for a in (term.get("aliases") or [])]
        termCandidates.append({"names": [n for n in names if n],
                               "term_id": str(term.get("term_id") or "")})

    subjectCandidates: List[Dict[str, Any]] = []
    try:
        for subject in store.listSubjects(agentId, tenantId=tenant):
            names = [str(subject.get("canonical_label") or ""),
                     str(subject.get("normalized_label") or "")]
            names += [str(a) for a in (subject.get("aliases") or [])]
            subjectCandidates.append({"names": [n for n in names if n],
                                      "subject_key": str(subject.get("subject_key") or "")})
    except Exception:  # noqa: BLE001 - 主体面不可用不挡术语覆盖判定
        pass

    rows: List[Dict[str, Any]] = []
    matched = 0
    for entity in entities:
        needle = _normalize(entity)
        hit = None
        if needle:
            for candidate in termCandidates:
                for name in candidate["names"]:
                    normalized = _normalize(name)
                    if normalized and (normalized == needle
                                       or normalized.startswith(needle)
                                       or needle in normalized):
                        hit = {"entity": entity, "matched": True,
                               "via": "term", "term_id": candidate["term_id"]}
                        break
                if hit:
                    break
            if hit is None:
                for candidate in subjectCandidates:
                    for name in candidate["names"]:
                        normalized = _normalize(name)
                        if normalized and (normalized == needle
                                           or needle in normalized):
                            hit = {"entity": entity, "matched": True,
                                   "via": "subject",
                                   "subject_key": candidate["subject_key"]}
                            break
                    if hit:
                        break
        if hit is None:
            hit = {"entity": entity, "matched": False, "via": "none"}
        else:
            matched += 1
        rows.append(hit)
    coverage = round(matched / len(entities), 4) if entities else 0.0
    return {"coverage": coverage,
            "answerable": bool(coverage >= float(threshold)),
            "threshold": float(threshold),
            "entities": rows}
