# -*- coding: utf-8 -*-
"""本地 bge rerank provider 与影子对照——可选依赖诚实失败、影子不改主路。"""
from __future__ import annotations

import pytest

from neurova.knowledge.rerank import rerank_factory
from neurova.knowledge.rerank.local_rerank_provider import buildLocalBgeProvider
from neurova.knowledge.rerank.main_path import (
    MainPathRerankConfig,
    refineMainPathResults,
)
from neurova.llm.rerank_client import RerankConfigError


class _FakeModel:
    def predict(self, pairs):
        return [float(len(text)) for _query, text in pairs]


class _ReverseRunner:
    def __init__(self):
        self.last_error = None

    def rerank(self, query, docs):
        rows = [
            {"index": int(doc["index"]), "score": float(int(doc["index"])), "doc": doc}
            for doc in docs
        ]
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows


class _BrokenRunner:
    last_error = None

    def rerank(self, query, docs):
        raise RuntimeError("provider down")


def _pool():
    return [
        {"knowledge_id": "k1", "content": "alpha", "confidence_breakdown": {"bm25": 0.9}},
        {"knowledge_id": "k2", "content": "beta", "confidence_breakdown": {"bm25": 0.8}},
        {"knowledge_id": "k3", "content": "gamma", "confidence_breakdown": {"bm25": 0.7}},
    ]


class TestLocalProvider:
    def testReturnsScoresWithInjectedLoader(self, tmp_path):
        provider = buildLocalBgeProvider(
            modelPath=str(tmp_path), loader=lambda _path: _FakeModel()
        )

        assert provider("q", ["ab", "abcd"]) == [2.0, 4.0]

    def testMissingModelIsHonestConfigError(self, tmp_path):
        with pytest.raises(RerankConfigError) as exc:
            buildLocalBgeProvider(modelPath=str(tmp_path / "absent"))

        assert exc.value.reason.startswith("local_model_missing:")

    def testFactoryFallsBackWithReasonWhenModelMissing(self, tmp_path):
        runner, label, note = rerank_factory.buildRunner({
            "method": "model",
            "rerank_provider_kind": "local_bge",
            "rerank_model_path": str(tmp_path / "absent"),
        })

        assert label == "weight"
        assert note["requested"] == "model"
        assert note["reason"].startswith("local_model_missing:")


class TestShadow:
    def testShadowDoesNotChangePrimaryOrder(self):
        base = refineMainPathResults(
            "alpha", _pool(), limit=3,
            config=MainPathRerankConfig(enabled=True, method="weight"),
        )[0]
        shadowed, note = refineMainPathResults(
            "alpha", _pool(), limit=3,
            config=MainPathRerankConfig(
                enabled=True, method="weight", shadow=True, shadowMethod="model"
            ),
            shadowRunner=_ReverseRunner(),
        )

        assert [r["knowledge_id"] for r in shadowed] == [
            r["knowledge_id"] for r in base
        ]
        assert note["shadow"]["applied"] is True
        assert note["shadow"]["rank_overlap"] == 1.0
        assert note["shadow"]["mean_abs_rank_shift"] is not None

    def testShadowFailureLeavesPrimaryUntouched(self):
        base = refineMainPathResults(
            "alpha", _pool(), limit=3,
            config=MainPathRerankConfig(enabled=True, method="weight"),
        )[0]
        shadowed, note = refineMainPathResults(
            "alpha", _pool(), limit=3,
            config=MainPathRerankConfig(
                enabled=True, method="weight", shadow=True, shadowMethod="model"
            ),
            shadowRunner=_BrokenRunner(),
        )

        assert [r["knowledge_id"] for r in shadowed] == [
            r["knowledge_id"] for r in base
        ]
        assert note["shadow"]["applied"] is False
        assert note["shadow"]["reason"].startswith("shadow_error:")


class TestLlmRerankProvider:
    def testScoresAreParsedAndOrderedByModel(self):
        from neurova.knowledge.rerank.llm_rerank_provider import buildLlmRerankProvider

        def fakeLlm(prompt):
            assert "候选" in prompt
            return '{"scores":[{"index":0,"score":0.1},{"index":1,"score":0.9}]}'

        provider = buildLlmRerankProvider(fakeLlm)

        assert provider("q", ["a", "b"]) == [0.1, 0.9]

    def testMissingIndexIsContractError(self):
        from neurova.knowledge.rerank.llm_rerank_provider import buildLlmRerankProvider
        from neurova.llm.rerank_client import RerankBackendError

        provider = buildLlmRerankProvider(lambda prompt: '{"scores":[{"index":0,"score":1}]}')

        with pytest.raises(RerankBackendError) as exc:
            provider("q", ["a", "b"])

        assert exc.value.kind == "contract"

    def testFactoryWithoutCallableFallsBackHonestly(self):
        runner, label, note = rerank_factory.buildRunner({
            "method": "model", "rerank_provider_kind": "llm",
        })

        assert label == "weight"
        assert note["reason"] == "llm_call_missing"


def testFactoryBuildsLlmProviderWhenCallableInjected():
    runner, label, note = rerank_factory.buildRunner({
        "method": "model",
        "rerank_provider_kind": "llm",
        "llm_call": lambda prompt: '{"scores":[{"index":0,"score":0.2},{"index":1,"score":0.8}]}',
    })

    assert label == "model" and note is None
    assert [row["index"] for row in runner.rerank("q", [
        {"index": 0, "content": "a"}, {"index": 1, "content": "b"},
    ])] == [1, 0]
