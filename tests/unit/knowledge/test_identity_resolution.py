"""确定性实体消解（工单 006，设计文档 §5 段2、G05）。

要灭的病：`resolution.py` 是全对遍历 + 单一 difflib 阈值 + 逐对 LLM 裁决——
O(n²)、有成本、且同一批数据重跑结果可能不同。这里换成 blocking + 多因子加权
+ 并查集聚类，全程确定性、零模型调用、可重放。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from neurova.knowledge.identity.entity_blocking import EntityBlockingResolver
from neurova.knowledge.identity.identity_merger import IdentityMerger
from neurova.knowledge.identity.subject_resolver import SubjectResolver
from neurova.knowledge.identity.similarity_fusion import (
    JaroWinkler,
    Levenshtein,
    SimilarityFusion,
)


def _entity(key, label, etype="concept", attrs=None, neighbors=None):
    return {
        "key": key, "label": label, "type": etype,
        "attributes": attrs or {}, "neighbors": neighbors or [],
    }


class TestBlocking:
    def test_candidatesStayInsideTheirBlock(self):
        entities = [
            _entity("a1", "神经瓦记忆层", etype="concept"),
            _entity("a2", "神经瓦记忆层备份", etype="concept"),
            _entity("b1", "神经瓦记忆层", etype="tool"),   # 类型不同，永不该比
        ]

        pairs = EntityBlockingResolver().candidatePairs(entities)

        assert ("a1", "a2") in pairs
        assert ("a1", "b1") not in pairs and ("b1", "a1") not in pairs

    def test_candidateCountIsFarBelowAllPairs(self):
        entities = [_entity("e%d" % i, "标题%d" % i, etype="cat%d" % (i % 5)) for i in range(200)]

        pairs = EntityBlockingResolver().candidatePairs(entities)

        assert len(pairs) < len(entities) * 3, "分块失效会退化成全对遍历"

    def test_candidatePairsAreOrderedAndDeduplicated(self):
        entities = [_entity("x", "同一名字"), _entity("y", "同一名字"), _entity("z", "同一名字")]

        pairs = EntityBlockingResolver().candidatePairs(entities)

        assert all(left < right for left, right in pairs)
        assert len(pairs) == len(set(pairs))

    def test_tokenBlockCatchesWordOrderSwaps(self):
        entities = [
            _entity("p", "记忆 层 检索"),
            _entity("q", "检索 层 记忆"),
        ]

        pairs = EntityBlockingResolver().candidatePairs(entities)

        assert ("p", "q") in pairs


class TestStringMetrics:
    @pytest.mark.parametrize("left,right,expected", [
        ("kitten", "sitting", 1 - 3 / 7),
        ("", "", 1.0),
        ("abc", "abc", 1.0),
    ])
    def test_levenshteinSimilarity(self, left, right, expected):
        assert Levenshtein.similarity(left, right) == pytest.approx(expected, abs=1e-6)

    def test_jaroWinklerOnCanonicalPair(self):
        # 学术口径下的标准样例：MARTHA / MARHTA → Jaro 0.9444、Winkler ≈ 0.9611
        raw = JaroWinkler.jaro("MARTHA", "MARHTA")
        assert raw == pytest.approx(0.9444, abs=1e-3)
        assert JaroWinkler.similarity("martha", "marhta") == pytest.approx(0.9611, abs=1e-3)

    def test_metricsAreInRangeAndCaseFoldsAtTheFusionLayer(self):
        """大小写归一只做一处：字面度量保持纯字符级，归一在融合层负责。

        若两层各归一，将来改口径会只改到一半。
        """
        assert 0.0 <= Levenshtein.similarity("甲乙丙", "乙丙丁") <= 1.0
        assert 0.0 <= JaroWinkler.similarity("Neurova", "NEUROVA") <= 1.0
        assert JaroWinkler.similarity("Neurova", "neurova") < 1.0, "字面度量本身区分大小写"

        fused = SimilarityFusion().score(_entity("l", "Neurova"), _entity("r", "NEUROVA"))
        assert fused == pytest.approx(1.0, abs=1e-9), "融合后大小写不再影响身份判定"


class TestSimilarityFusion:
    def test_identicalEntitiesScoreOne(self):
        left = _entity("l", "神经瓦", attrs={"v": "1"}, neighbors=["m"])
        right = _entity("r", "神经瓦", attrs={"v": "1"}, neighbors=["m"])

        assert SimilarityFusion().score(left, right) == pytest.approx(1.0, abs=1e-6)

    def test_weightsRenormalizeWhenAProviderIsAbsent(self):
        fusion = SimilarityFusion(weights={"label": 0.5, "attribute": 0.3, "neighbor": 0.2})
        left, right = _entity("l", "同一标签"), _entity("r", "同一标签")

        assert fusion.score(left, right) == pytest.approx(1.0, abs=1e-6)
        assert sum(fusion.activeWeights(left, right).values()) == pytest.approx(1.0)

    def test_disjointEntitiesDoNotInheritPerfectScore(self):
        """两侧都缺属性时该因子不得白送满分——否则任意两个空实体都会合并。"""
        left = _entity("l", "记忆层与反思机制")
        right = _entity("r", "飞书渠道接入协议")

        assert SimilarityFusion().score(left, right) < 0.5

    def test_vectorFactorUsesInjectedProviderOnly(self):
        calls = []

        def provider(text):
            calls.append(text)
            return [1.0, 0.0]

        fusion = SimilarityFusion(embeddingProvider=provider)
        fusion.score(_entity("l", "甲"), _entity("r", "乙"))

        assert calls, "注入了 provider 才用向量因子，构造期不得偷偷加载模型"


class TestUnionFindClustering:
    def test_transitivePairsFormOneCluster(self):
        proposals = [
            {"left": "a", "right": "b", "score": 0.95},
            {"left": "b", "right": "c", "score": 0.93},
        ]

        clusters = IdentityMerger(threshold=0.9).cluster(proposals)

        assert len(clusters) == 1
        assert sorted(clusters[0]["members"]) == ["a", "b", "c"]

    def test_belowThresholdStaysSplit(self):
        proposals = [{"left": "a", "right": "b", "score": 0.8}]

        clusters = IdentityMerger(threshold=0.9).cluster(proposals)

        assert clusters == []

    def test_canonicalMemberIsDeterministic(self):
        proposals = [
            {"left": "zz", "right": "mm", "score": 0.95},
            {"left": "aa", "right": "zz", "score": 0.95},
        ]

        clusters = IdentityMerger(threshold=0.9).cluster(proposals)

        assert clusters[0]["canonical"] == "aa", "代表元必须可由输入推出，不得依赖遍历顺序"


class TestReplayDeterminism:
    def test_shuffledInputProducesIdenticalClusters(self):
        entities = [
            _entity("e%d" % i, ["神经瓦记忆层", "神经瓦记忆层备份", "别的主题", "记忆层 神经瓦"][i % 4],
                   etype="concept")
            for i in range(40)
        ]
        resolver, fusion, merger = EntityBlockingResolver(), SimilarityFusion(), IdentityMerger(0.85)

        def pipeline(batch):
            return merger.cluster([
                {"left": a, "right": b, "score": fusion.score(byKey[a], byKey[b])}
                for a, b in resolver.candidatePairs(batch)
            ])

        byKey = {e["key"]: e for e in entities}
        forward = pipeline(entities)
        backward = pipeline(list(reversed(entities)))

        assert sorted(tuple(c["members"]) for c in forward) == \
               sorted(tuple(c["members"]) for c in backward)

    def test_identityPackageCallsNoLanguageModel(self):
        """G05 的可证伪判据：消解层零 LLM。静态扫导入面，比约定更难被绕过。"""
        packageDir = Path("neurova/knowledge/identity")
        offenders = []
        for path in packageDir.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in ("llm_client", "MultiModelLLMClient", "track_llm_call", "agent_ref", "chat("):
                if token in text:
                    offenders.append("%s → %s" % (path.name, token))

        assert not offenders, "消解段引入了模型调用，重放不再确定: " + ", ".join(offenders)


def _subject(key, label, aliases=None):
    return {"subject_key": key, "canonical_label": label, "type_term_id": "concept",
            "aliases": aliases or []}


class TestSubjectResolver:
    def test_exactLabelReusesExistingKey(self):
        subjects = [_subject("s1", "神经瓦记忆层")]

        outcome = SubjectResolver().resolve("神经瓦记忆层", subjects)

        assert outcome.subjectKey == "s1" and not outcome.createdNew

    def test_aliasReusesExistingKey(self):
        subjects = [_subject("s1", "神经瓦", aliases=["Neurova"])]

        assert SubjectResolver().resolve("Neurova", subjects).subjectKey == "s1"

    def test_nearIdenticalAboveAutoThresholdReusesWithoutCreating(self):
        subjects = [_subject("s1", "神经瓦记忆层")]

        outcome = SubjectResolver(autoThreshold=0.5, reviewThreshold=0.3).resolve(
            "神经瓦记忆层备份", subjects)

        assert outcome.subjectKey == "s1" and not outcome.createdNew
        assert outcome.nearest and outcome.nearest[1] >= 0.5

    def test_midSimilarityCreatesSeparateSubjectFlaggedForReview(self):
        """置信不足：另开一行 + 标待审，不自动合身份。"""
        subjects = [_subject("s1", "记忆层检索通道")]

        outcome = SubjectResolver(autoThreshold=0.99, reviewThreshold=0.2).resolve(
            "记忆层检索", subjects)

        assert outcome.subjectKey is None and outcome.createdNew
        assert outcome.needsHumanReview

    def test_dissimilarLabelCreatesSubjectWithoutReview(self):
        subjects = [_subject("s1", "飞书渠道协议")]

        outcome = SubjectResolver().resolve("完全不相干的量子拓扑", subjects)

        assert outcome.createdNew and not outcome.needsHumanReview

    def test_thresholdOrderIsEnforced(self):
        with pytest.raises(ValueError, match="reviewThreshold"):
            SubjectResolver(autoThreshold=0.5, reviewThreshold=0.8)

    def test_collisionAuditIsDeterministic(self):
        subjects = [_subject("s%d" % i, "神经瓦记忆层" if i % 2 else "神经瓦记忆层备份") for i in range(6)]

        first = SubjectResolver(autoThreshold=0.8, reviewThreshold=0.5).auditCollisions(subjects)
        second = SubjectResolver(autoThreshold=0.8, reviewThreshold=0.5).auditCollisions(list(reversed(subjects)))

        assert first and sorted(c["members"] for c in first) == sorted(c["members"] for c in second)
