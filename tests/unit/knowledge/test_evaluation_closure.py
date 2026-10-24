# -*- coding: utf-8 -*-
"""评估闭环：NDCG、分域切片、精排增益、冲突度量、诚实 A/B。"""
from __future__ import annotations

import pytest

from neurova.experiments.ab_test_manager import (
    ABTestManager,
    ExperimentConfig,
    ExperimentGroup,
)
from neurova.knowledge.evaluation.conflict_metrics import conflictMetrics
from neurova.knowledge.evaluation.retrieval_benchmark import RetrievalBenchmark


@pytest.fixture
def bench(tmp_path) -> RetrievalBenchmark:
    b = RetrievalBenchmark(str(tmp_path / "eval.db"))
    b.addCase("q1", ["b"], domain="core")
    b.addCase("q2", ["x"], domain="other")
    return b


def _search(query):
    return (
        [{"knowledge_id": "a"}, {"knowledge_id": "b"}]
        if query == "q1" else []
    )


class TestNdcgAndRerankGain:
    def testNdcgIsComputedAndRerankGainVisible(self, bench):
        report = bench.run(
            repo=None, searchFn=_search, topK=2,
            rerank=lambda query, hits: list(reversed(hits)),
        )

        assert report["measure_state"] == "measured"
        assert report["ndcg_at_k"] == round((0.63093 + 0.0) / 2, 6)
        assert report["rerank_ndcg_at_k"] == 0.5
        assert report["rerank_gain"] == round(0.5 - report["ndcg_at_k"], 6)

    def testDomainFilterAndSlice(self, bench):
        filtered = bench.run(repo=None, searchFn=_search, topK=2, domain="core")
        assert filtered["case_count"] == 1

        full = bench.run(repo=None, searchFn=_search, topK=2)
        slices = {row["domain"]: row for row in bench.byDomain(full["run_id"])}

        assert set(slices) == {"core", "other"}
        assert slices["core"]["case_count"] == 1
        assert slices["other"]["recall_at_k"] == 0.0

    def testEmptyDomainIsUnevidenced(self, bench):
        report = bench.run(repo=None, searchFn=_search, domain="absent")

        assert report["measure_state"] == "unevidenced"
        assert "该域" in report["missing_reason"]


class TestConflictMetrics:
    def testEmptyLedgerIsUnevidenced(self):
        metrics = conflictMetrics([])

        assert metrics["measure_state"] == "unevidenced"
        assert metrics["conflict_share"] is None

    def testDistributionWithoutLabelsDoesNotFakeFalseMerges(self):
        records = [
            {"conflict_id": "c1", "decision": "conflict", "status": "pending"},
            {"conflict_id": "c2", "decision": "similar", "status": "resolved"},
            {"conflict_id": "c3", "decision": "manual", "status": "pending"},
        ]

        metrics = conflictMetrics(records)

        assert metrics["decision_counts"] == {
            "similar": 1, "conflict": 1, "different": 0, "manual": 1,
        }
        assert metrics["conflict_share"] == round(1 / 3, 6)
        assert metrics["pending_count"] == 2
        assert metrics["false_merge_rate"] is None
        assert "标签" in metrics["missing_reason"]

    def testFalseMergeRateUsesHumanLabels(self):
        records = [
            {"conflict_id": "c1", "decision": "similar"},
            {"conflict_id": "c2", "decision": "similar"},
            {"conflict_id": "c3", "decision": "conflict"},
        ]
        labels = {"c1": "similar", "c2": "conflict", "c3": "conflict"}

        metrics = conflictMetrics(records, labels)

        assert metrics["labeled_count"] == 3
        assert metrics["false_merge_rate"] == 0.5
        assert metrics["decision_accuracy"] == round(2 / 3, 6)


def _config(name, minSample):
    return ExperimentConfig(
        name=name, description="sig", groups=[ExperimentGroup.CONTROL, ExperimentGroup.TREATMENT],
        traffic_split={ExperimentGroup.CONTROL: 0.5, ExperimentGroup.TREATMENT: 0.5},
        metrics=["score"], duration_days=1, min_sample_size=minSample,
    )


class TestHonestSignificance:
    @pytest.mark.asyncio
    async def testSmallSampleIsReportedAsInsufficient(self):
        manager = ABTestManager()
        await manager.start_experiment(_config("small", 5))
        for _ in range(2):
            await manager.record_metric("small", ExperimentGroup.CONTROL, {"score": 1.0}, {})
            await manager.record_metric("small", ExperimentGroup.TREATMENT, {"score": 2.0}, {})
        await manager.end_experiment("small")

        result = await manager.get_experiment_results("small")

        assert result["statistical_significance"]["significant"] is False
        assert result["statistical_significance"]["reason"] == "insufficient_sample"

    @pytest.mark.asyncio
    async def testEnoughSampleRunsWelchTest(self):
        manager = ABTestManager()
        await manager.start_experiment(_config("full", 5))
        for index in range(6):
            await manager.record_metric(
                "full", ExperimentGroup.CONTROL, {"score": 1.0 + index * 0.01}, {})
            await manager.record_metric(
                "full", ExperimentGroup.TREATMENT, {"score": 2.0 + index * 0.01}, {})
        await manager.end_experiment("full")

        result = (await manager.get_experiment_results("full"))["statistical_significance"]

        assert result["reason"] == "welch_t_test"
        assert result["metric"] == "score"
        assert result["significant"] is True
        assert result["p_value"] < 0.05


class TestOfflineVariantAB:
    def testSmallSampleIsInsufficient(self, bench):
        verdict = bench.compareVariants(
            {"case_count": 5, "recall_at_k": 0.5, "mrr": 0.5, "ndcg_at_k": 0.5,
             "unhit_rate": 0.5},
            {"case_count": 5, "recall_at_k": 0.9, "mrr": 0.9, "ndcg_at_k": 0.9,
             "unhit_rate": 0.1},
            minCases=30,
        )

        assert verdict["verdict"] == "insufficient_sample"
        assert verdict["case_count_b"] == 5

    def testEnoughSampleReportsDirection(self, bench):
        verdict = bench.compareVariants(
            {"case_count": 40, "recall_at_k": 0.5, "mrr": 0.5, "ndcg_at_k": 0.5,
             "unhit_rate": 0.5},
            {"case_count": 40, "recall_at_k": 0.8, "mrr": 0.7, "ndcg_at_k": 0.7,
             "unhit_rate": 0.2},
            minCases=30,
        )

        assert verdict["verdict"] == "improved"
        assert verdict["deltas"]["recall_at_k"] == 0.3

    def testRegressionIsNamed(self, bench):
        verdict = bench.compareVariants(
            {"case_count": 40, "recall_at_k": 0.8, "ndcg_at_k": 0.8, "unhit_rate": 0.1},
            {"case_count": 40, "recall_at_k": 0.5, "ndcg_at_k": 0.5, "unhit_rate": 0.4},
            minCases=30,
        )

        assert verdict["verdict"] == "regressed"


class TestCIRegressionGate:
    def testGateFailsClosedOnSmallSample(self, bench):
        with pytest.raises(AssertionError, match="样本不足"):
            bench.gateNoRegression(
                {"case_count": 5, "recall_at_k": 0.8, "ndcg_at_k": 0.8},
                {"case_count": 5, "recall_at_k": 0.9, "ndcg_at_k": 0.9},
                minCases=30,
            )

    def testGateFailsOnRegression(self, bench):
        with pytest.raises(AssertionError, match="回归"):
            bench.gateNoRegression(
                {"case_count": 40, "recall_at_k": 0.8, "ndcg_at_k": 0.8},
                {"case_count": 40, "recall_at_k": 0.5, "ndcg_at_k": 0.5},
                minCases=30,
            )

    def testGatePassesImprovement(self, bench):
        verdict = bench.gateNoRegression(
            {"case_count": 40, "recall_at_k": 0.5, "ndcg_at_k": 0.5},
            {"case_count": 40, "recall_at_k": 0.8, "ndcg_at_k": 0.8},
            minCases=30,
        )

        assert verdict["verdict"] == "improved"
