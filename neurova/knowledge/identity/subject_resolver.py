"""确定性实体消解 · 主体解析决策（工单 006）。

纯决策：吃"新标签 + 既有主体清单"，吐"并入谁 / 另开一个 / 交人工"。
不直连存储——底座方法由调用方注入，这样决策逻辑可以单独被重放验证。

高于 autoThreshold 才自动合并；落在 [reviewThreshold, autoThreshold) 一律不合并并标
needsHumanReview：置信不足时宁可多一个待审项，也不自动合错身份。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .entity_blocking import EntityBlockingResolver, normalizeLabel
from .identity_merger import IdentityMerger
from .similarity_fusion import SimilarityFusion

DEFAULT_AUTO_THRESHOLD = 0.92
DEFAULT_REVIEW_THRESHOLD = 0.80


class SubjectResolution:
    def __init__(self, subjectKey: Optional[str], createdNew: bool, needsHumanReview: bool,
                 nearest: Optional[Tuple[str, float]] = None) -> None:
        self.subjectKey = subjectKey
        self.createdNew = createdNew
        self.needsHumanReview = needsHumanReview
        self.nearest = nearest


def _asEntity(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "key": str(row.get("subject_key", row.get("key", ""))),
        "label": str(row.get("canonical_label", row.get("label", "") or "")),
        "type": str(row.get("type_term_id") or row.get("type") or ""),
        "attributes": row.get("attributes") or {},
        "neighbors": row.get("aliases") or [],
    }


class SubjectResolver:
    def __init__(
        self,
        fusion: Optional[SimilarityFusion] = None,
        autoThreshold: float = DEFAULT_AUTO_THRESHOLD,
        reviewThreshold: float = DEFAULT_REVIEW_THRESHOLD,
    ) -> None:
        if not 0.0 < reviewThreshold <= autoThreshold <= 1.0:
            raise ValueError(
                "阈值需满足 0 < reviewThreshold <= autoThreshold <= 1，收到 review=%r auto=%r"
                % (reviewThreshold, autoThreshold)
            )
        self._fusion = fusion or SimilarityFusion()
        self._blocking = EntityBlockingResolver()
        self._merger = IdentityMerger(threshold=autoThreshold)
        self._auto = autoThreshold
        self._review = reviewThreshold

    def bestMatch(self, label: str, subjects: Sequence[Dict[str, Any]]) -> Optional[Tuple[str, float]]:
        probe = _asEntity({"key": "__probe__", "label": label})
        scored: List[Tuple[str, float]] = []
        for row in subjects:
            entity = _asEntity(row)
            if not entity["key"]:
                raise ValueError("既有主体缺 subject_key，无法参与身份判定")
            score = self._fusion.score(probe, entity)
            if score >= self._review:
                scored.append((entity["key"], score))
        if not scored:
            return None
        # 先分数后键：并列时也不给遍历顺序留下影响结果的余地
        return sorted(scored, key=lambda row: (-row[1], row[0]))[0]

    def resolve(
        self, label: str, subjects: Sequence[Dict[str, Any]], aliases: Optional[List[str]] = None
    ) -> SubjectResolution:
        for row in subjects:
            names = [row.get("canonical_label", "")] + list(row.get("aliases") or [])
            if any(_same(name, candidate) for name in names for candidate in [label, *(aliases or [])]):
                return SubjectResolution(str(row["subject_key"]), createdNew=False, needsHumanReview=False)

        nearest = self.bestMatch(label, subjects)
        if nearest and nearest[1] >= self._auto:
            return SubjectResolution(nearest[0], createdNew=False, needsHumanReview=False, nearest=nearest)
        return SubjectResolution(
            None, createdNew=True,
            needsHumanReview=bool(nearest and nearest[1] >= self._review),
            nearest=nearest,
        )

    def auditCollisions(self, subjects: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """对既有主体跑一遍当前口径，给出"应当合并"的清单（只报告，不动手）。"""
        entities = [_asEntity(row) for row in subjects]
        byKey = {entity["key"]: entity for entity in entities}
        proposals = [
            {"left": left, "right": right, "score": self._fusion.score(byKey[left], byKey[right])}
            for left, right in self._blocking.candidatePairs(entities)
        ]
        return self._merger.cluster(proposals)


def _same(left: Any, right: Any) -> bool:
    return bool(left) and bool(right) and normalizeLabel(str(left)) == normalizeLabel(str(right))
