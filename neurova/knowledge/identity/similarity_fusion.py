"""确定性实体消解 · 多因子相似度融合（工单 006）。

因子：字面（Levenshtein 与 Jaro-Winkler）、属性重叠、关系邻域重叠、向量余弦。
每一因子只在"两侧都有数据"时参与，缺侧即退出并把权重摊给其余因子——
两侧都空却白送 1.0 会让任意两个空实体被合并。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

DEFAULT_WEIGHTS: Dict[str, float] = {
    "label": 0.45,
    "attribute": 0.20,
    "neighbor": 0.15,
    "vector": 0.20,
}


class Levenshtein:
    @staticmethod
    def distance(left: str, right: str) -> int:
        if left == right:
            return 0
        if not left:
            return len(right)
        if not right:
            return len(left)
        previous = list(range(len(right) + 1))
        for i, chLeft in enumerate(left, start=1):
            current = [i]
            for j, chRight in enumerate(right, start=1):
                current.append(min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (chLeft != chRight),
                ))
            previous = current
        return previous[-1]

    @staticmethod
    def similarity(left: str, right: str) -> float:
        longest = max(len(left), len(right))
        if longest == 0:
            return 1.0
        return 1.0 - Levenshtein.distance(left, right) / longest


class JaroWinkler:
    @staticmethod
    def jaro(left: str, right: str) -> float:
        if left == right:
            return 1.0
        if not left or not right:
            return 0.0
        window = max(len(left), len(right)) // 2 - 1
        leftFlags = [False] * len(left)
        rightFlags = [False] * len(right)
        matches = 0
        for index, ch in enumerate(left):
            start = max(0, index - window)
            end = min(len(right), index + window + 1)
            for other in range(start, end):
                if not rightFlags[other] and right[other] == ch:
                    leftFlags[index] = rightFlags[other] = True
                    matches += 1
                    break
        if not matches:
            return 0.0
        transpositions = 0
        cursor = 0
        for index, flag in enumerate(leftFlags):
            if not flag:
                continue
            while not rightFlags[cursor]:
                cursor += 1
            if left[index] != right[cursor]:
                transpositions += 1
            cursor += 1
        return (matches / len(left) + matches / len(right)
                + (matches - transpositions / 2) / matches) / 3.0

    @staticmethod
    def similarity(left: str, right: str, scale: float = 0.1) -> float:
        raw = JaroWinkler.jaro(left, right)
        prefix = 0
        for a, b in zip(left, right):
            if a != b:
                break
            prefix += 1
            if prefix == 4:
                break
        return raw + prefix * scale * (1.0 - raw)


class SimilarityFusion:
    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        embeddingProvider: Optional[Callable[[str], List[float]]] = None,
    ) -> None:
        self._weights = dict(weights or DEFAULT_WEIGHTS)
        self._embedding = embeddingProvider

    def activeWeights(self, left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, float]:
        factors = self._factorScores(left, right)
        active = {name: self._weights.get(name, 0.0) for name in factors if self._weights.get(name, 0.0)}
        total = sum(active.values())
        if not total:
            return {}
        return {name: weight / total for name, weight in active.items()}

    def score(self, left: Dict[str, Any], right: Dict[str, Any]) -> float:
        factors = self._factorScores(left, right)
        weights = self.activeWeights(left, right)
        if not weights:
            raise ValueError("两个实体没有任何可比较因子，拒绝给出相似度")
        return sum(factors[name] * weight for name, weight in weights.items())

    # ── 因子 ──────────────────────────────────────────────────

    def _factorScores(self, left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, float]:
        factors: Dict[str, float] = {}
        leftLabel = str(left.get("label", "") or "").strip().casefold()
        rightLabel = str(right.get("label", "") or "").strip().casefold()
        if leftLabel and rightLabel:
            factors["label"] = (
                Levenshtein.similarity(leftLabel, rightLabel)
                + JaroWinkler.similarity(leftLabel, rightLabel)
            ) / 2.0

        leftAttrs = _attributePairs(left)
        rightAttrs = _attributePairs(right)
        if leftAttrs and rightAttrs:
            factors["attribute"] = _jaccard(leftAttrs, rightAttrs)

        leftNeighbors = {str(n) for n in (left.get("neighbors") or []) if str(n)}
        rightNeighbors = {str(n) for n in (right.get("neighbors") or []) if str(n)}
        if leftNeighbors and rightNeighbors:
            factors["neighbor"] = _jaccard(leftNeighbors, rightNeighbors)

        if self._embedding is not None and leftLabel and rightLabel:
            factors["vector"] = self._vectorSimilarity(leftLabel, rightLabel)
        return factors

    def _vectorSimilarity(self, leftLabel: str, rightLabel: str) -> float:
        leftVector = self._embedding(leftLabel)
        rightVector = self._embedding(rightLabel)
        return cosine(leftVector, rightVector)


def _attributePairs(entity: Dict[str, Any]) -> set:
    attributes = entity.get("attributes") or {}
    if not isinstance(attributes, dict):
        raise ValueError("attributes 必须是 dict，收到 %r" % type(attributes).__name__)
    return {"%s=%s" % (k, str(v).casefold()) for k, v in attributes.items()}


def _jaccard(left: set, right: set) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def cosine(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        raise ValueError("向量维度不齐，无法算余弦")
    dot = sum(a * b for a, b in zip(left, right))
    normLeft = sum(a * a for a in left) ** 0.5
    normRight = sum(b * b for b in right) ** 0.5
    if not normLeft or not normRight:
        return 0.0
    return dot / (normLeft * normRight)
