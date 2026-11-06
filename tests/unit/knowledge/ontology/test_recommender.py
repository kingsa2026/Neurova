# -*- coding: utf-8 -*-
"""B-L-F 约束推理与推荐（升级计划 §3.5 L-F）：偏好提取＋约束过滤＋排序＋理由。

餐饮场景判据：差评"海鲜过敏＋价格偏高"→ 推荐套餐C（无海鲜¥300）→ 排除A。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.preference_extractor import extractPreferences
from neurova.knowledge.ontology.recommender import (
    Constraint,
    CustomerPreferenceProfile,
    OntologyRecommender,
    ProductFact,
)


class TestPreferenceExtraction:
    def test_allergyExtractedAsHardConstraint(self):
        prefs = extractPreferences("A套餐中有海鲜，自己海鲜过敏")
        assert any(c.attribute == "has_seafood" and c.value == "false"
                   and c.priority == "hard" for c in prefs)

    def test_priceSensitivityExtractedAsSoft(self):
        prefs = extractPreferences("套餐A价格偏高")
        assert any(c.attribute == "price" and c.priority == "soft"
                   for c in prefs)

    def test_combinedFeedbackExtractsBoth(self):
        prefs = extractPreferences("A套餐中有海鲜，自己海鲜过敏，而且套餐A价格偏高")
        assert len(prefs) >= 2

    def test_positiveFeedbackProducesNoConstraint(self):
        prefs = extractPreferences("很好吃，下次再来")
        assert len(prefs) == 0


class TestConstraintRecommender:
    """餐饮场景全流程：偏好画像＋产品目录→推荐C排除A。"""

    @pytest.fixture
    def products(self):
        return [
            ProductFact(productId="套餐A",
                        attributes={"has_seafood": "true", "price": "400",
                                    "cuisine_type": "中式"}),
            ProductFact(productId="套餐B",
                        attributes={"has_seafood": "false", "price": "400"}),
            ProductFact(productId="套餐C",
                        attributes={"has_seafood": "false", "price": "300"}),
        ]

    @pytest.fixture
    def profile(self):
        return CustomerPreferenceProfile(
            customerId="客户X",
            hardConstraints=[
                Constraint(attribute="has_seafood", operator="!=", value="true",
                           priority="hard"),
            ],
            softPreferences=[
                Constraint(attribute="price", operator="<", value="400",
                           priority="soft"),
            ],
            validFrom="2026-08-15")

    def test_hardConstraintFiltersOutSeafood(self, products, profile):
        recommender = OntologyRecommender()
        results = recommender.recommend(profile, products)

        ids = [r.productId for r in results]
        assert "套餐A" not in ids, "含海鲜的套餐A被硬约束排除"
        assert "套餐C" in ids and "套餐B" in ids

    def test_softPreferenceRanksCheaperFirst(self, products, profile):
        recommender = OntologyRecommender()
        results = recommender.recommend(profile, products)

        assert results[0].productId == "套餐C", "价格300 < 400 → C 排第一"
        assert results[0].rank == 1

    def test_rationaleExplainsRecommendation(self, products, profile):
        recommender = OntologyRecommender()
        results = recommender.recommend(profile, products)

        top = results[0]
        assert "无海鲜" in top.rationale or "海鲜" in top.rationale
        assert "价格" in top.rationale or "300" in top.rationale

    def test_noMatchingProductReturnsEmpty(self, products):
        """全部产品都违反硬约束时返回空——不假装有推荐。"""
        profile = CustomerPreferenceProfile(
            customerId="客户X",
            hardConstraints=[
                Constraint(attribute="has_seafood", operator="==", value="maybe",
                           priority="hard"),
            ],
            softPreferences=[],
            validFrom="2026-08-15")
        recommender = OntologyRecommender()
        results = recommender.recommend(profile, products)
        assert results == []
