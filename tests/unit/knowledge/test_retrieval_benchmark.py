"""检索评测台架（工单 002，设计文档 §8）。

主锚：改进"有效"必须由离线读数判定，读数取不到即 unevidenced，不按通过处理。
"""

from __future__ import annotations

import json

import pytest

from neurova.knowledge.evaluation.retrieval_benchmark import RetrievalBenchmark
from neurova.knowledge.repository import KnowledgeRepository

_OWNER = "bench-user"
_USER = {"user_id": _OWNER}


@pytest.fixture
def kb(tmp_path) -> KnowledgeRepository:
    """真仓库 + 真检索路，不用 mock 冒充检索对象。"""
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    repo.create_knowledge("bench", "蜂群并发成本护栏", "SwarmManager.spawn 对并发调用做限流与成本记账",
                      owner_user_id=_OWNER)
    repo.create_knowledge("bench", "时序知识图谱", "带 valid_from 与 valid_until 窗口的事实", owner_user_id=_OWNER)
    repo.create_knowledge("bench", "多模态路由", "LLMRouter 按请求类型选择模型档位", owner_user_id=_OWNER)
    repo.create_knowledge("bench", "知识条目墓碑", "删除后 superseded_by 链可复活", owner_user_id=_OWNER)
    repo.create_knowledge("bench", "渠道适配层", "飞书钉钉 telegram discord 等接入适配", owner_user_id=_OWNER)
    return repo


@pytest.fixture
def bench(tmp_path) -> RetrievalBenchmark:
    return RetrievalBenchmark(str(tmp_path / "eval" / "knowledge_evaluation.db"))


def _idOf(repo, title):
    for agent, items in repo._items.items():
        for item in items:
            if item.get("title") == title:
                return item["knowledge_id"]
    raise AssertionError("条目不存在: %s" % title)


class TestSchemaAndCases:
    def test_schemaIsIdempotent(self, bench):
        bench._ensureSchema()
        bench._ensureSchema()

        assert bench.caseCount() == 0

    def test_addCaseThenCounted(self, bench):
        bench.addCase("蜂群 限流", ["k1"], domain="swarm", createdBy="002")

        assert bench.caseCount() == 1

    def test_caseRecordsLabelingMethod(self, bench):
        bench.addCase("蜂群", ["k1"], labelingMethod="title_literal")

        assert bench.cases()[0]["labeling_method"] == "title_literal"


class TestMetrics:
    def test_recallAndMrrOnRealRetrieval(self, bench, kb):
        bench.addCase("蜂群并发成本护栏", [_idOf(kb, "蜂群并发成本护栏")])
        bench.addCase("时序知识图谱 窗口", [_idOf(kb, "时序知识图谱")])

        report = bench.run(kb, user=_USER, topK=5)

        assert report["measure_state"] == "measured"
        assert report["case_count"] == 2
        assert 0.0 <= report["recall_at_k"] <= 1.0
        assert report["recall_at_k"] > 0.0, "对真实检索路跑出 0 命中说明台架或标注有错"
        assert report["mrr"] > 0.0

    def test_rankOneGetsMrrOne(self, bench, kb):
        bench.addCase("多模态路由", [_idOf(kb, "多模态路由")])

        report = bench.run(kb, user=_USER, topK=5)

        assert report["mrr"] == 1.0
        assert report["recall_at_k"] == 1.0

    def test_caseWhoseExpectedNeverRanksInCountsAsUnhit(self, bench, kb):
        """用不存在的期望 id 确定性验"未命中"分支。

        不拿"乱码查询 + 5 条语料 + top_k=5"当反例——那样每条语料都在榜内，
        断言的其实是排序巧合而非指标数学。
        """
        bench.addCase("渠道适配层", ["no_such_knowledge_id"])

        report = bench.run(kb, user=_USER, topK=5)

        assert report["unhit_rate"] == 1.0
        assert report["recall_at_k"] == 0.0
        assert report["mrr"] == 0.0

    def test_emptyCaseSetIsUnevidencedNotZero(self, bench, kb):
        report = bench.run(kb, user=_USER, topK=5)

        assert report["measure_state"] == "unevidenced"
        assert report["recall_at_k"] is None, "无案例时不得报 0——0 会被读成'检索很差'"
        assert report["missing_reason"]


class TestBaselineFreeze:
    def test_runAppendsAndNeverOverwritesFrozenBaseline(self, bench, kb):
        bench.addCase("知识条目墓碑", [_idOf(kb, "知识条目墓碑")])
        first = bench.run(kb, user=_USER, topK=5)
        bench.freezeBaseline(first)

        bench.run(kb, user=_USER, topK=5)

        baseline = bench.baseline()
        assert baseline is not None
        assert baseline["frozen_at"]
        assert baseline["run_id"] == first["run_id"], "基线必须锚在某一次 run，不得被后续 run 覆盖"
        assert bench.runCount() == 2

    def test_findingsPersistPerCaseForRegressionDiff(self, bench, kb):
        bench.addCase("蜂群并发成本护栏", [_idOf(kb, "蜂群并发成本护栏")])
        # 同上：未命中分支用不存在的期望 id 表达，不依赖小语料上的排序巧合
        bench.addCase("时序知识图谱", ["no_such_knowledge_id"])
        report = bench.run(kb, user=_USER, topK=5)

        findings = bench.findings(report["run_id"])

        assert len(findings) == 2
        hit = {f["query"]: f for f in findings}
        assert hit["蜂群并发成本护栏"]["reciprocal_rank"] == 1.0
        assert hit["时序知识图谱"]["reciprocal_rank"] == 0.0
        assert hit["时序知识图谱"]["unhit"] == 1
        assert hit["时序知识图谱"]["is_baseline"] is False


class TestSeedFromRealData:
    """台架侧只验数学与纪律；真实基线由 `freezeBaseline` 一次性跑出，不落进单测——
    `data/` 在 .gitignore 内，CI 上生产库不存在，依赖它会造成假红。
    """

    def test_seedProducesCasesWithLabelBreakdown(self, tmp_path):
        src = KnowledgeRepository(str(tmp_path / "src"))
        for i in range(40):
            src.create_knowledge(
                "bench", "主题词%d 的知识标题" % i, "正文内容 %d" % i,
                tags=["域%d" % (i % 7)], category="cat%d" % (i % 5),
            )
        bench = RetrievalBenchmark(str(tmp_path / "eval.db"))

        n = bench.seedFromRepository(src, minCases=30)

        assert n >= 30
        breakdown = bench.labelingBreakdown()
        assert set(breakdown) <= {"title_literal", "tag", "category"}
        assert breakdown.get("title_literal", 0) < n, "不得全靠标题直取充数"

    def test_categoryCaseCarriesWholeClassAsExpected(self, tmp_path):
        """category/tag 口径的正确答案是"该类全部条目"，标成单条会把检索误判为漏报。"""
        src = KnowledgeRepository(str(tmp_path / "src"))
        for i in range(3):
            src.create_knowledge("bench", "各异标题%d" % i, "正文%d" % i,
                                 tags=["同域"], category="同分类")
        src.create_knowledge("bench", "别类标题", "别的正文", tags=["异域"], category="别分类")
        bench = RetrievalBenchmark(str(tmp_path / "eval.db"))

        # 去重后可标注 query 共 8 种（4 标题 + 2 标签 + 2 分类），取满即全覆盖
        bench.seedFromRepository(src, minCases=8)

        byQuery = {c["query"]: json.loads(c["expected_ids"]) for c in bench.cases()}
        assert len(byQuery["同分类"]) == 3, "同类目应有 3 个可接受命中"
        assert len(byQuery["同域"]) == 3
        assert len(byQuery["别分类"]) == 1

    def test_seedNeverEmitsDuplicateQuery(self, tmp_path):
        """同一 query 重复入表会把它按出现次数加权，读数就失真。"""
        src = KnowledgeRepository(str(tmp_path / "src"))
        for i in range(20):
            src.create_knowledge("bench", "标题%d" % i, "正文%d" % i, tags=["同标签"], category="同分类")
        bench = RetrievalBenchmark(str(tmp_path / "eval.db"))

        bench.seedFromRepository(src, minCases=10)

        keys = [(c["labeling_method"], c["query"]) for c in bench.cases()]
        assert len(keys) == len(set(keys))

    def test_seedAgainstSparseRepoRaisesNotSilentlyZero(self, tmp_path):
        src = KnowledgeRepository(str(tmp_path / "sparse"))
        src.create_knowledge("bench", "只有一条", "孤例")

        with pytest.raises(ValueError, match="条目不足"):
            RetrievalBenchmark(str(tmp_path / "eval.db")).seedFromRepository(src, minCases=30)
