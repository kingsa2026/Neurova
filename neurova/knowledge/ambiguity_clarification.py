# -*- coding: utf-8 -*-
"""同名多口径的读侧暴露（specs/2026-10-30 W4）。

写侧早已有冲突矩阵（D6）与消解裁决（D9），但读侧从不暴露：模型对"同名多口径"
静默取 top-1，用户无感知。本模块把**既有账**翻译成命中阶段的歧义载荷：

- `multi_subject`：查询里的同一个词消解出 ≥2 个幸存主体（同名多口径）；
- `open_conflict`：命中主体在冲突账里还有未决行。

纪律三条：
- **只消费既有账**：主体别名表、冲突账；不重算冲突（教义第 6 条，不建第二冲突源）；
- **caliber_hint 只取证据字段**：事实的 qualifier 值，缺省回退命中条目标题；
  不调用 LLM、不猜；
- **off 零开销**：off 档连别名账都不碰；计算失败返回 None，检索主路照跑。

三档开关 `NEUROVA_KB_AMBIGUITY_CLARIFY=off|shadow|on`（默认 off）：
shadow 只把载荷写进 `RetrievalResult.metadata["ambiguity"]`，行为零变化；
on 再由 chat_pipeline 在注入块首加一段模型面向的受控指引。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.knowledge.query_normalization import subjectsMatchingQuery

logger = get_logger(__name__)

AMBIGUITY_ENV = "NEUROVA_KB_AMBIGUITY_CLARIFY"
_MODES = ("off", "shadow", "on")
_MAX_CANDIDATES = 5
_MAX_HINTS = 3
_ENTRY_REF_PREFIXES = ("entry:", "legacy:")


def ambiguityMode() -> str:
    raw = (os.environ.get(AMBIGUITY_ENV) or "off").strip().lower()
    return raw if raw in _MODES else "off"


@dataclass
class AmbiguityBlock:
    source: str  # multi_subject | open_conflict
    term: str
    candidates: List[Dict[str, Any]] = field(default_factory=list)

    def toMetadata(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "term": self.term,
            "candidates": [dict(candidate) for candidate in self.candidates],
        }


def _caliberHints(facts: List[Dict[str, Any]]) -> List[str]:
    """口径提示＝事实 qualifier 值去重前 N（证据字段，原样取用，不加工）。"""
    hints: List[str] = []
    for fact in facts or []:
        for value in (fact.get("qualifier") or {}).values():
            text = str(value or "").strip()
            if text and text not in hints:
                hints.append(text)
                if len(hints) >= _MAX_HINTS:
                    return hints
    return hints


def _entryRefsOf(store: Any, factId: str) -> List[str]:
    """事实 → 条目：取断言里的 `entry:`/`legacy:` 溯源串（与图走查同一口径）。"""
    refs: List[str] = []
    try:
        rows = store.lineageRows(factId) or []
    except Exception as exc:  # noqa: BLE001 - 血缘缺失只少一条证据提示
        logger.debug("歧义候选条目溯源读取失败: %s", exc)
        return refs
    for row in rows:
        ref = str(row.get("medium_ref") or "")
        for prefix in _ENTRY_REF_PREFIXES:
            if ref.startswith(prefix):
                entryId = ref[len(prefix):]
                if entryId and entryId not in refs:
                    refs.append(entryId)
                break
    return refs


def _hitsBySubject(
    store: Any, hits: List[Dict[str, Any]]
) -> tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """本轮命中 → 按主体归拢的条目 id / 标题（命中自带 lineage fact id）。"""
    factIds = [str(hit.get("lineage_id")) for hit in hits or [] if hit.get("lineage_id")]
    facts: Dict[str, Dict[str, Any]] = {}
    if factIds:
        try:
            facts = {
                str(fact["fact_id"]): fact
                for fact in store.factsByIds(list(dict.fromkeys(factIds))) or []
            }
        except Exception as exc:  # noqa: BLE001 - 归属读失败只影响提示，不改载荷形状
            logger.debug("歧义候选命中归属读取失败: %s", exc)
    entries: Dict[str, List[str]] = {}
    titles: Dict[str, List[str]] = {}
    for hit in hits or []:
        fact = facts.get(str(hit.get("lineage_id") or ""))
        entryId = str(hit.get("knowledge_id") or "")
        if not fact or not entryId:
            continue
        subjectKey = str(fact.get("subject_key") or "")
        if not subjectKey:
            continue
        entries.setdefault(subjectKey, []).append(entryId)
        title = str(hit.get("title") or "").strip()
        if title:
            titles.setdefault(subjectKey, []).append(title)
    return entries, titles


def _subjectCandidate(
    store: Any,
    match: Any,
    entriesBySubject: Dict[str, List[str]],
    titlesBySubject: Dict[str, List[str]],
) -> Dict[str, Any]:
    try:
        facts = store.factsForSubject(match.subjectKey)
    except Exception as exc:  # noqa: BLE001
        logger.debug("歧义候选口径读取失败: %s", exc)
        facts = []
    hints = _caliberHints(facts) or list(titlesBySubject.get(match.subjectKey) or [])[:_MAX_HINTS]
    return {
        "subject_key": match.subjectKey,
        "canonical_label": match.canonicalLabel,
        "caliber_hint": hints,
        "entry_ids": list(entriesBySubject.get(match.subjectKey) or []),
    }


def _conflictCandidate(store: Any, fact: Dict[str, Any], canonicalLabel: str) -> Dict[str, Any]:
    hints = _caliberHints([fact])
    if not hints:
        # 未定口径的行没有 qualifier：拿争议值本身作为可辨识的证据字段
        disputed = str(fact.get("object_term") or "").strip()
        hints = [disputed] if disputed else []
    return {
        "subject_key": str(fact.get("subject_key") or ""),
        "canonical_label": canonicalLabel,
        "caliber_hint": hints,
        "entry_ids": _entryRefsOf(store, str(fact.get("fact_id") or "")),
    }


def buildAmbiguityBlock(
    store: Any,
    query: str,
    hits: List[Dict[str, Any]],
    agentId: Optional[str],
    tenantId: str = "default",
) -> Optional[AmbiguityBlock]:
    """命中阶段的歧义载荷；无歧义 / 开关 off / 任何异常一律 None。"""
    if ambiguityMode() == "off" or not agentId:
        return None
    try:
        groups = subjectsMatchingQuery(store, query, agentId, tenantId)
        if not groups:
            return None
        entriesBySubject, titlesBySubject = _hitsBySubject(store, hits)

        for term, matches in groups:
            if len({match.subjectKey for match in matches}) >= 2:
                return AmbiguityBlock(
                    "multi_subject",
                    term,
                    [
                        _subjectCandidate(store, match, entriesBySubject, titlesBySubject)
                        for match in matches[:_MAX_CANDIDATES]
                    ],
                )

        termsByKey: Dict[str, str] = {}
        for term, matches in groups:
            for match in matches:
                termsByKey.setdefault(match.subjectKey, term)
        try:
            conflicts = [
                conflict
                for conflict in store.conflicts("pending", tenantId=str(tenantId or "default"))
                if str(conflict.get("subject_key") or "") in termsByKey
            ]
        except Exception as exc:  # noqa: BLE001 - 冲突账不可用只丢这一路触发器
            logger.debug("歧义冲突账读取跳过: %s", exc)
            conflicts = []
        if conflicts:
            conflict = conflicts[0]
            subjectKey = str(conflict.get("subject_key") or "")
            subject = store.subjectFor(subjectKey) or {}
            canonicalLabel = str(subject.get("canonical_label") or "")
            members = store.conflictMembers(conflict["conflict_id"]) or []
            candidates = [
                _conflictCandidate(store, fact, canonicalLabel)
                for fact in members[:_MAX_CANDIDATES]
            ]
            if candidates:
                return AmbiguityBlock(
                    "open_conflict", termsByKey.get(subjectKey, ""), candidates
                )
        return None
    except Exception as exc:  # noqa: BLE001 - 歧义计算绝不影响检索返回
        logger.debug("歧义载荷计算跳过: %s", exc)
        return None


def renderAmbiguityGuidance(block: Dict[str, Any]) -> str:
    """歧义载荷 → 模型面向的受控指引（块首一行，非用户文案）。"""
    candidates = block.get("candidates") or []
    labels = "；".join(
        str(candidate.get("canonical_label") or candidate.get("subject_key") or "")
        for candidate in candidates
    )
    term = str(block.get("term") or "")
    return (
        f"[检索歧义]「{term}」在知识库中有 {len(candidates)} 个口径：{labels}；"
        "用户意图不明时先澄清再作答，不得静默择一。"
    )
