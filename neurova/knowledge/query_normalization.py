# -*- coding: utf-8 -*-
"""查询侧别名归一（specs/2026-10-30 W1）。

主体表的别名账（knowledge_subjects.aliases_json）此前只有事实层
（resolveSubjectKey）与图锚（subjectsMentionedIn）在读，条目检索的查询侧从不
展开——用户说别名时五路混合检索天然脱靶，别名登记处于写而不读状态。

本模块把别名账映射成查询展开，纪律三条：

- **只追加不删改**：expanded = 原查询 + 命中主体的规范名（≤4 个、总长封顶），
  原始词永远参与打分，归一只提召回，不改写用户意图；
- **off 零开销**：off 档不碰别名账、不建缓存、不产生读数；
- **失败让路**：别名账任何异常返回原查询，检索主路绝不被归一层打死
  （与图谱影子路由同级纪律）。

别名唯一事实源是主体表；本模块不建第二份词典（修复教义第 6 条）。
"""
from __future__ import annotations

import os
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

QUERY_NORMALIZE_ENV = "NEUROVA_KB_QUERY_NORMALIZE"
_NORMALIZE_MODES = ("off", "shadow", "on")
_EXPANSION_MAX_TERMS = 4
_EXPANDED_QUERY_MAX_CHARS = 512
_CACHE_TTL_SECONDS = 60.0
_MERGE_CHAIN_MAX_HOPS = 16


def normalizeMode() -> str:
    raw = (os.environ.get(QUERY_NORMALIZE_ENV) or "off").strip().lower()
    return raw if raw in _NORMALIZE_MODES else "off"


def _normText(text: Any) -> str:
    """匹配用归一：normalizeLabel（去首尾空白/大小写）再叠 NFKC，全半角不挡包含匹配。"""
    return unicodedata.normalize("NFKC", str(text or "")).strip().lower()


@dataclass
class SubjectMatch:
    subjectKey: str
    canonicalLabel: str
    matchedTerm: str
    matchedVia: str  # canonical | alias


@dataclass
class NormalizedQuery:
    original: str
    expanded: str
    appendedTerms: List[str] = field(default_factory=list)
    matchedSubjects: List[SubjectMatch] = field(default_factory=list)
    changed: bool = False

    def toMetadata(self) -> Dict[str, Any]:
        return {
            "appended_terms": list(self.appendedTerms),
            "matched_subjects": [
                {
                    "subject_key": match.subjectKey,
                    "canonical_label": match.canonicalLabel,
                    "matched_term": match.matchedTerm,
                    "matched_via": match.matchedVia,
                }
                for match in self.matchedSubjects
            ],
            "changed": self.changed,
        }


# {(agentId, tenantId): (monotonic 到期, 别名词目列表)}——TTL 兜底跨进程写，
# 同进程的别名变更（脱靶审批）走 invalidateQueryNormalizationCache() 即时生效。
_aliasCache: Dict[Tuple[str, str], Tuple[float, List[Tuple[str, str, str, str, str]]]] = {}
_aliasCacheLock = threading.RLock()


def invalidateQueryNormalizationCache() -> None:
    with _aliasCacheLock:
        _aliasCache.clear()


def _loadAliasTerms(
    store: Any, agentId: str, tenantId: str
) -> List[Tuple[str, str, str, str, str]]:
    """主体表别名账 → (归一词, 原词, 幸存主体键, 幸存规范名, 来源)。

    合并链在内存消解，语义与 KnowledgeFactStore._followMerge 一致（maxHops 同值）；
    链尾不在本 agent/租户页（悬空 merged_into）的词条跳过，不猜归属。
    """
    rows = store.listSubjects(agentId, includeMerged=True, tenantId=tenantId)
    byKey = {str(row.get("subject_key")): row for row in rows or []}

    def survivor(subjectKey: str) -> Optional[Tuple[str, str]]:
        current = subjectKey
        for _ in range(_MERGE_CHAIN_MAX_HOPS):
            row = byKey.get(current)
            if row is None:
                return None
            mergedInto = row.get("merged_into")
            if not mergedInto:
                return current, str(row.get("canonical_label") or "")
            current = str(mergedInto)
        logger.debug("主体合并链超 %d 跳，跳过词条归属: %s", _MERGE_CHAIN_MAX_HOPS, subjectKey)
        return None

    terms: List[Tuple[str, str, str, str, str]] = []
    for row in rows or []:
        key = str(row.get("subject_key") or "")
        if not key:
            continue
        resolved = survivor(key)
        if resolved is None:
            continue
        targetKey, targetCanonical = resolved
        entries = [("canonical", str(row.get("canonical_label") or ""))]
        entries += [("alias", str(alias)) for alias in (row.get("aliases") or [])]
        for via, term in entries:
            normTerm = _normText(term)
            if normTerm:
                terms.append((normTerm, term, targetKey, targetCanonical, via))
    # 长词优先：包含匹配下短词先命中会让长词失去机会
    terms.sort(key=lambda item: (-len(item[0]), item[0], item[2]))
    return terms


def _cachedAliasTerms(
    store: Any, agentId: str, tenantId: str
) -> List[Tuple[str, str, str, str, str]]:
    now = time.monotonic()
    cacheKey = (agentId, tenantId)
    with _aliasCacheLock:
        cached = _aliasCache.get(cacheKey)
        if cached and cached[0] > now:
            return cached[1]
    terms = _loadAliasTerms(store, agentId, tenantId)
    with _aliasCacheLock:
        _aliasCache[cacheKey] = (now + _CACHE_TTL_SECONDS, terms)
    return terms


def subjectsMatchingQuery(
    store: Any, query: str, agentId: Optional[str], tenantId: str = "default"
) -> List[Tuple[str, List[SubjectMatch]]]:
    """查询命中的主体词 → 该词消解出的**全部**幸存主体（W4 歧义触发器）。

    与 `normalizeQueryForRetrieval` 共用同一份别名账、同一套归一与合并链语义；
    唯一的差别是**不**按"已用词"去重——同名多口径（两个主体挂同一个别名）
    正是要观察的形态，展开侧去重后只剩一个代表，这里必须都看得见。
    返回按词长降序（长词优先，与展开同序）。
    """
    original = str(query or "")
    if not original.strip() or not agentId:
        return []
    try:
        terms = _cachedAliasTerms(store, str(agentId), str(tenantId or "default"))
    except Exception as exc:  # noqa: BLE001 - 别名账不可用不让路，由调用方决定缺省
        logger.debug("歧义候选词读取跳过（别名账不可用）: %s", exc)
        return []
    normQuery = _normText(original)
    if not normQuery:
        return []
    groups: Dict[str, List[SubjectMatch]] = {}
    for normTerm, rawTerm, targetKey, targetCanonical, via in terms:
        if normTerm not in normQuery:
            continue
        bucket = groups.setdefault(normTerm, [])
        if any(match.subjectKey == targetKey for match in bucket):
            continue
        bucket.append(SubjectMatch(targetKey, targetCanonical, rawTerm, via))
    return [(matches[0].matchedTerm, matches) for matches in groups.values()]


def normalizeQueryForRetrieval(
    store: Any, query: str, agentId: Optional[str], tenantId: str = "default"
) -> NormalizedQuery:
    """把查询里的主体别名/黑话归一到规范名（off 零开销，失败让路）。"""
    original = str(query or "")
    mode = normalizeMode()
    if mode == "off" or not original.strip() or not agentId:
        return NormalizedQuery(original=original, expanded=original)
    try:
        terms = _cachedAliasTerms(store, str(agentId), str(tenantId or "default"))
    except Exception as exc:  # noqa: BLE001 - 归一失败让路，检索主路不许被打死
        logger.debug("查询侧别名归一跳过（别名账不可用）: %s", exc)
        return NormalizedQuery(original=original, expanded=original)

    normQuery = _normText(original)
    if not normQuery:
        return NormalizedQuery(original=original, expanded=original)

    matched: List[SubjectMatch] = []
    appended: List[str] = []
    seenSubjects: set = set()
    usedTerms: set = set()
    appendedSet: set = set()
    for normTerm, rawTerm, targetKey, targetCanonical, via in terms:
        if normTerm in usedTerms or normTerm not in normQuery:
            continue
        usedTerms.add(normTerm)
        if targetKey not in seenSubjects:
            seenSubjects.add(targetKey)
            matched.append(SubjectMatch(targetKey, targetCanonical, rawTerm, via))
        normCanonical = _normText(targetCanonical)
        if (
            len(appended) < _EXPANSION_MAX_TERMS
            and normCanonical
            and normCanonical not in appendedSet
            and normCanonical not in normQuery
        ):
            appendedSet.add(normCanonical)
            appended.append(targetCanonical)

    expanded = original
    changed = False
    if mode == "on" and appended:
        candidate = original
        for term in appended:
            tentative = (candidate + " " + term).strip()
            if len(tentative) > _EXPANDED_QUERY_MAX_CHARS:
                break
            candidate = tentative
        if candidate != original:
            expanded = candidate
            changed = True
    return NormalizedQuery(
        original=original, expanded=expanded,
        appendedTerms=appended, matchedSubjects=matched, changed=changed,
    )
