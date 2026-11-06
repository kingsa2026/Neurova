"""约束推理推荐器（B-L-F F-3–F-8，升级计划 §3.5 L-F）。

偏好画像 → 硬约束过滤（违反即排除）→ 软偏好排序（满足多者靠前）→
理由生成（每条推荐附 matched/violated 说明）。确定性逻辑，零 ML 零依赖。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Constraint:
    attribute: str
    operator: str  # == != > < >= <=
    value: str
    priority: str  # hard / soft


@dataclass
class ProductFact:
    """产品结构化事实集：attributes 是 {本体关系术语: 值} 映射。"""
    productId: str
    attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class CustomerPreferenceProfile:
    customerId: str
    hardConstraints: List[Constraint] = field(default_factory=list)
    softPreferences: List[Constraint] = field(default_factory=list)
    validFrom: str = ""


@dataclass
class ProductRecommendation:
    productId: str
    score: float
    rank: int
    matchedConstraints: List[str]
    violatedSoftPreferences: List[str]
    rationale: str


def _compare(actual: str, operator: str, expected: str) -> bool:
    """两个字符串值按 operator 语义比较；数值可转则按数值比，不可转按文本比。"""
    a, e = str(actual or "").strip(), str(expected or "").strip()
    try:
        av, ev = float(a), float(e)
    except ValueError:
        av, ev = a, e
    if operator == "==":
        return av == ev
    if operator == "!=":
        return av != ev
    if operator == ">":
        return av > ev
    if operator == "<":
        return av < ev
    if operator == ">=":
        return av >= ev
    if operator == "<=":
        return av <= ev
    return False


class OntologyRecommender:
    """基于本体事实的约束推理推荐器：确定性逻辑，零 ML 零依赖。"""

    def recommend(self, profile: CustomerPreferenceProfile,
                  products: List[ProductFact]) -> List[ProductRecommendation]:
        """三步推荐：硬约束过滤 → 软偏好打分 → 排序＋理由。"""
        candidates: List[Dict[str, Any]] = []

        for product in products:
            attrs = product.attributes
            # 硬约束过滤
            violatedHard = [
                c for c in profile.hardConstraints
                if not self._satisfies(attrs, c)
            ]
            if violatedHard:
                continue
            # 软偏好打分
            softScore = sum(
                1 for c in profile.softPreferences
                if self._satisfies(attrs, c)
            )
            matchedSoft = [c for c in profile.softPreferences
                           if self._satisfies(attrs, c)]
            violatedSoft = [c for c in profile.softPreferences
                            if not self._satisfies(attrs, c)]
            candidates.append({
                "product": product,
                "softScore": softScore,
                "matchedSoft": matchedSoft,
                "violatedSoft": violatedSoft,
            })

        candidates.sort(key=lambda c: (-c["softScore"], c["product"].productId))

        results: List[ProductRecommendation] = []
        for rank, candidate in enumerate(candidates, 1):
            product = candidate["product"]
            matched = ["%s %s %s" % (c.attribute, c.operator, c.value)
                       for c in candidate["matchedSoft"]]
            violated = ["%s %s %s" % (c.attribute, c.operator, c.value)
                        for c in candidate["violatedSoft"]]
            rationale = self._generateRationale(profile, product, candidate)
            results.append(ProductRecommendation(
                productId=product.productId,
                score=float(candidate["softScore"]),
                rank=rank,
                matchedConstraints=matched,
                violatedSoftPreferences=violated,
                rationale=rationale,
            ))
        return results

    def _satisfies(self, attrs: Dict[str, str], c: Constraint) -> bool:
        """检查产品属性是否满足约束；属性缺失视为不满足（不猜）。"""
        actual = attrs.get(c.attribute)
        if actual is None:
            return False
        return _compare(actual, c.operator, c.value)

    def _generateRationale(self, profile: CustomerPreferenceProfile,
                           product: ProductFact,
                           candidate: Dict[str, Any]) -> str:
        parts: List[str] = []
        attrs = product.attributes
        for c in profile.hardConstraints:
            actual = attrs.get(c.attribute)
            if actual is not None:
                if c.attribute == "has_seafood" and actual == "false":
                    parts.append("无海鲜")
                elif c.attribute == "has_seafood" and actual != "false":
                    parts.append("含海鲜")
        for c in candidate.get("matchedSoft", []):
            if c.attribute == "price":
                price = attrs.get("price", "")
                parts.append("价格 %s 元" % price)
        if not parts:
            parts.append("满足基本条件")
        rationale = "，".join(parts)
        violatedSoft = candidate.get("violatedSoft", [])
        if violatedSoft:
            violatedStrs = ["%s %s %s" % (c.attribute, c.operator, c.value)
                            for c in violatedSoft]
            rationale += "（部分偏好未完全满足：%s）" % "；".join(violatedStrs)
        return rationale
