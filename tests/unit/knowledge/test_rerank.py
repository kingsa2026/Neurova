"""rerank 双模模块（TDD — Dify 对标 P0-3）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §2.6 RerankRunnerFactory）：
- WeightRerankRunner（加权分融合）：多路分数加权求和后重排，无外部依赖
- ModelRerankRunner（模型重排）：调 rerank_provider callable（注入式，便于
  接 bge-reranker/cohere），provider 失败时可选退化到加权模式
- rerank(query, docs, method) 工厂双模入口；空输入恒返回 []
- 输出按 score 降序，保留原始 doc 引用
- trec 式小样本：hybrid+rerank 应胜过单路 BM25（验收标准）

RerankResult 数据形状：{"index": int, "score": float, "doc": 原条目}
"""

import pytest

from neurova.knowledge.rerank import (
    ModelRerankRunner,
    WeightRerankRunner,
    rerank,
)


@pytest.fixture
def candidate_docs():
    """模拟 hybrid 召回的候选集：带多路分数明细"""
    return [
        {"index": 0, "id": "d0", "bm25": 0.9, "vector": 0.1},
        {"index": 1, "id": "d1", "bm25": 0.5, "vector": 0.8},
        {"index": 2, "id": "d2", "bm25": 0.3, "vector": 0.4},
    ]


class TestWeightRerankRunner:
    def test_weighted_sum_resort(self, candidate_docs):
        runner = WeightRerankRunner(weights={"bm25": 0.6, "vector": 0.4})
        results = runner.rerank("q", candidate_docs)
        # d0: 0.6*0.9+0.4*0.1=0.58；d1: 0.6*0.5+0.4*0.8=0.62 → d1 第一
        assert results[0]["doc"]["id"] == "d1"
        assert results[0]["score"] == pytest.approx(0.62, abs=1e-6)
        assert results[1]["doc"]["id"] == "d0"
        assert results[2]["doc"]["id"] == "d2"

    def test_keeps_original_doc_reference(self, candidate_docs):
        runner = WeightRerankRunner(weights={"bm25": 1.0, "vector": 0.0})
        results = runner.rerank("q", candidate_docs)
        assert results[0]["doc"] is candidate_docs[0]
        assert results[0]["index"] == 0

    def test_empty_candidates(self):
        runner = WeightRerankRunner(weights={"bm25": 1.0})
        assert runner.rerank("q", []) == []

    def test_missing_score_key_treated_as_zero(self, candidate_docs):
        docs = [{"index": 0, "id": "x", "bm25": 0.7}]  # 无 vector 键
        runner = WeightRerankRunner(weights={"bm25": 0.5, "vector": 0.5})
        results = runner.rerank("q", docs)
        assert results[0]["score"] == pytest.approx(0.35, abs=1e-6)

    def test_single_weight_ignores_query(self, candidate_docs):
        runner = WeightRerankRunner(weights={"bm25": 1.0})
        r1 = runner.rerank("query A", candidate_docs)
        r2 = runner.rerank("完全不同的查询 B", candidate_docs)
        assert [r["doc"]["id"] for r in r1] == [r["doc"]["id"] for r in r2]


class TestModelRerankRunner:
    def test_model_scores_take_priority(self, candidate_docs):
        """模型重排：provider 给出的分数决定次序，多路分数仅作退化兜底"""
        provider = lambda q, docs: [0.1, 0.95, 0.3]  # noqa: E731  d1 最高
        runner = ModelRerankRunner(rerank_provider=provider)
        results = runner.rerank("q", candidate_docs)
        assert results[0]["doc"]["id"] == "d1"
        assert results[0]["score"] == pytest.approx(0.95, abs=1e-6)

    def test_fallback_on_provider_failure(self, candidate_docs):
        """provider 抛异常 → 退化加权融合（fallback=True 默认）"""

        def broken_provider(q, docs):
            raise RuntimeError("rerank model unavailable")

        runner = ModelRerankRunner(
            rerank_provider=broken_provider,
            fallback_weights={"bm25": 0.6, "vector": 0.4},
        )
        results = runner.rerank("q", candidate_docs)
        # 退化后 d1 仍第一（0.62 > 0.58），但分数来自加权而非模型
        assert results[0]["doc"]["id"] == "d1"
        assert results[0]["score"] == pytest.approx(0.62, abs=1e-6)

    def test_no_fallback_raises(self, candidate_docs):
        runner = ModelRerankRunner(
            rerank_provider=lambda q, docs: (_ for _ in ()).throw(RuntimeError("x")),
            fallback_weights=None,
        )
        with pytest.raises(RuntimeError):
            runner.rerank("q", candidate_docs)

    def test_length_mismatch_raises(self, candidate_docs):
        """provider 返回分数数量与候选数不符 → 视为坏契约走退化"""
        runner = ModelRerankRunner(
            rerank_provider=lambda q, docs: [0.5],
            fallback_weights={"bm25": 1.0},
        )
        results = runner.rerank("q", candidate_docs)
        assert len(results) == 3  # 走了退化，不崩


class TestRerankFactory:
    def test_factory_weight_mode(self, candidate_docs):
        results = rerank("q", candidate_docs, method="weight", weights={"bm25": 1.0})
        assert results[0]["doc"]["id"] == "d0"

    def test_factory_model_mode(self, candidate_docs):
        results = rerank(
            "q", candidate_docs, method="model",
            rerank_provider=lambda q, docs: [0.2, 0.9, 0.1],
        )
        assert results[0]["doc"]["id"] == "d1"

    def test_factory_invalid_method(self, candidate_docs):
        with pytest.raises(ValueError):
            rerank("q", candidate_docs, method="no_such")

    def test_trec_style_hybrid_rerank_beats_single_bm25(self):
        """验收标准（trec 式小样本）：hybrid+rerank 胜过单路 BM25。

        场景：d_correct 在 BM25 里排第 3（关键词弱命中），但向量强命中；
        单路 BM25 把它排后，加权 rerank 应把它拉到第一。
        """
        docs = [
            {"index": 0, "id": "noise", "bm25": 0.95, "vector": 0.05},
            {"index": 1, "id": "partial", "bm25": 0.75, "vector": 0.30},
            {"index": 2, "id": "correct", "bm25": 0.40, "vector": 0.92},
        ]
        # 单路 BM25 的次序
        bm25_order = sorted(docs, key=lambda d: d["bm25"], reverse=True)
        assert bm25_order[0]["id"] == "noise"

        results = rerank("q", docs, method="weight", weights={"bm25": 0.4, "vector": 0.6})
        assert results[0]["doc"]["id"] == "correct", "hybrid+rerank 应把多路一致的文档拉到第一"
