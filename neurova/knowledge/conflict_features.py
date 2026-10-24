"""冲突/相似特征矩阵（规则优先，NER/向量可选）。

只做可解释的确定性特征：
- 字符/词 Jaccard；
- 关键数字/日期/百分比；
- 引号/英文专名等实体词重叠（不做模型猜测）；
- 调用方可选传入向量余弦。

四象限只给判定与依据，不自动改写事实；人工/现有冲突账本仍是最终落点。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Set, Tuple

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")
_EN_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9_.-]{2,}\b")
_QUOTED_RE = re.compile(r"[“\"'「『]([^”\"'」』]{2,40})[”\"'」』]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")
_STOP = frozenset({"的", "了", "和", "与", "及", "在", "是", "为", "对", "将", "这", "那"})


def _tokens(text: str) -> Set[str]:
    raw = {token.lower() for token in _WORD_RE.findall(text or "")}
    return {token for token in raw if token not in _STOP}


def _numbers(text: str) -> Set[str]:
    return set(_NUMBER_RE.findall(text or ""))


def _entities(text: str) -> Set[str]:
    quoted = {m.group(1).strip() for m in _QUOTED_RE.finditer(text or "")}
    english = {m.group(0) for m in _EN_ENTITY_RE.finditer(text or "")}
    return {item for item in quoted | english if item}


def _jaccard(left: Set[str], right: Set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def buildConflictFeatures(
    left: str,
    right: str,
    *,
    vectorSimilarity: Optional[float] = None,
    subjectSimilarity: Optional[float] = None,
) -> Dict[str, Any]:
    leftTokens, rightTokens = _tokens(left), _tokens(right)
    leftNumbers, rightNumbers = _numbers(left), _numbers(right)
    leftEntities, rightEntities = _entities(left), _entities(right)
    lexical = _jaccard(leftTokens, rightTokens)
    entity = _jaccard(leftEntities, rightEntities)
    numbersConflict = bool(leftNumbers and rightNumbers and not (leftNumbers & rightNumbers))
    numbersMatch = (not leftNumbers and not rightNumbers) or bool(leftNumbers & rightNumbers)
    vector = float(vectorSimilarity) if vectorSimilarity is not None else 0.0
    return {
        "lexical_jaccard": round(lexical, 6),
        "entity_overlap": round(entity, 6),
        "numbers_left": sorted(leftNumbers),
        "numbers_right": sorted(rightNumbers),
        "numbers_conflict": numbersConflict,
        "numbers_match": numbersMatch,
        "vector_similarity": round(max(0.0, min(1.0, vector)), 6),
        "subject_similarity": (
            round(float(subjectSimilarity), 6)
            if subjectSimilarity is not None else None
        ),
    }


def classifyConflict(features: Dict[str, Any]) -> Tuple[str, str]:
    """返回 (decision, reason)；decision ∈ similar|conflict|different|manual。"""
    similarity = max(
        float(features.get("vector_similarity") or 0.0),
        float(features.get("lexical_jaccard") or 0.0),
    )
    entity = float(features.get("entity_overlap") or 0.0)
    subject = float(features.get("subject_similarity") or 0.0)
    high = similarity >= 0.50
    entityHigh = entity >= 0.50 or subject >= 0.90
    # 数字对冲只在「同一主题」上成立：向量相似但实体/词面无关（预算金额 vs 服务器端口）
    # 是两件事，不能仅凭数字不同就判冲突。
    sameSubject = entityHigh or float(features.get("lexical_jaccard") or 0.0) >= 0.50
    if high and sameSubject and features.get("numbers_conflict"):
        return "conflict", "high_similarity_but_numbers_conflict"
    if high and entityHigh:
        if features.get("numbers_match"):
            return "similar", "high_similarity_and_numbers_match"
        return "manual", "high_similarity_without_number_evidence"
    if high and not entityHigh:
        return "different", "high_similarity_low_entity_overlap"
    if (not high) and entityHigh:
        return "manual", "low_similarity_high_entity_overlap"
    return "different", "low_similarity_low_entity_overlap"
