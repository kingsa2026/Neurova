"""主路末端 rerank（工单 014，灭 B05）。

B05 的形状：精修能力早就写好了，但只有旁路 API 用得到（`semantic_search_api.py:35`），
主链排序停在 RRF 秩融合——`hybrid.py` 与知识检索适配器对 `knowledge/rerank/` 零引用。
本票把它接进主路末端，并且**只装一个装配口**：API 与主路共用同一个 runner 工厂，
不出现第二份排序逻辑（这条本身就是判据）。

开关 `NEUROVA_KB_MAIN_RERANK`：默认态由真数据读数决定（见工单"完成状态"），
但判据固定为——关闸态与开闸前的行为逐条一致，开闸态 002 读数不降。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.rerank.main_path import (
    MAIN_RERANK_ENV,
    MainPathRerankConfig,
    refineMainPathResults,
)


def _row(kid, *, tfidf=0.0, bm25=0.0, fts=0.0, vector=0.0, rrf=0.0):
    return {
        "knowledge_id": kid, "title": kid, "content": "正文 " + kid,
        "score": rrf, "rrf_score": rrf,
        "confidence_breakdown": {"tfidf": tfidf, "bm25": bm25, "fts": fts,
                                 "vector": vector, "rrf": rrf},
    }


@pytest.fixture
def rows():
    """RRF 秩序与加权和序**故意相反**：a 靠 tfidf 拿了好秩但词法/语义分数都低。"""
    return [
        _row("a", tfidf=0.90, bm25=0.05, fts=0.05, vector=0.05, rrf=0.048),
        _row("b", tfidf=0.10, bm25=0.80, fts=0.60, vector=0.75, rrf=0.040),
        _row("c", tfidf=0.20, bm25=0.40, fts=0.30, vector=0.35, rrf=0.035),
    ]


class SpyRunner:
    """替身 runner：记录被交来重排的文档数（成本上限要能被断言，不能只在嘴上）。"""

    def __init__(self, order=None):
        self.seen = None
        self._order = order

    def rerank(self, query, docs):
        self.seen = list(docs)
        scored = [{"index": d["index"], "score": float(d.get("bm25", 0.0)), "doc": d}
                  for d in docs]
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored


class TestConfig:
    def test_defaultIsOnBecauseB05IsABreakpointNotACapability(self, monkeypatch):
        """默认开。要把默认翻回关，先给出冻结锚点上的读数——空接的段比关掉的段更糟。"""
        monkeypatch.delenv(MAIN_RERANK_ENV, raising=False)

        cfg = MainPathRerankConfig.fromEnv()

        assert cfg.enabled is True and cfg.method == "weight"

    def test_explicitValuesAreHonoured(self, monkeypatch):
        monkeypatch.setenv(MAIN_RERANK_ENV, "on")
        assert MainPathRerankConfig.fromEnv().enabled is True
        monkeypatch.setenv(MAIN_RERANK_ENV, "off")
        assert MainPathRerankConfig.fromEnv().enabled is False

    def test_poolFactorIsAtLeastOne(self, monkeypatch):
        monkeypatch.setenv(MAIN_RERANK_ENV, "off")
        assert MainPathRerankConfig.fromEnv().poolFactor >= 1


class TestMainPathRefine:
    def test_disabledReturnsInputUntouched(self, rows, monkeypatch):
        monkeypatch.setenv(MAIN_RERANK_ENV, "off")

        out, note = refineMainPathResults("查询", rows, limit=3)

        assert [r["knowledge_id"] for r in out] == ["a", "b", "c"]
        assert note is None
        assert all("rerank_score" not in r for r in out), "关闸就是逐字旧行为，不盖新字段"

    def test_weightRerankReordersAndStampsProvenance(self, rows, monkeypatch):
        monkeypatch.setenv(MAIN_RERANK_ENV, "on")

        out, note = refineMainPathResults("查询", rows, limit=3)

        assert [r["knowledge_id"] for r in out] == ["b", "c", "a"], "加权和应把词法/语义双高的排前"
        assert all(r["rerank_method"] == "weight" for r in out)
        assert [round(r["rerank_score"], 4) for r in out] == sorted(
            [round(r["rerank_score"], 4) for r in out], reverse=True)
        assert note is None

    def test_truncationHappensAfterRerank(self, rows, monkeypatch):
        monkeypatch.setenv(MAIN_RERANK_ENV, "on")

        out, _ = refineMainPathResults("查询", rows, limit=2)

        assert [r["knowledge_id"] for r in out] == ["b", "c"], "先精排再截断，否则被顶上去的排不进来"

    def test_onlyThePoolIsReRanked(self, rows, monkeypatch):
        """成本上限是可断言的事实：整池重排会随语料线性放大，尤其是模型通道。"""
        monkeypatch.setenv(MAIN_RERANK_ENV, "on")
        big = [_row("k%d" % i, bm25=i / 100.0, rrf=1.0 / (i + 1)) for i in range(30)]
        spy = SpyRunner()

        out, _ = refineMainPathResults("查询", big, limit=3, runner=spy,
                                       config=MainPathRerankConfig(enabled=True, poolFactor=3))

        assert len(spy.seen) == 9
        assert len(out) == 3
        assert {d["id"] for d in spy.seen} <= {r["knowledge_id"] for r in big}

    def test_scoresComeFromBreakdownNotRecomputation(self, rows, monkeypatch):
        monkeypatch.setenv(MAIN_RERANK_ENV, "on")
        spy = SpyRunner()

        refineMainPathResults("查询", rows, limit=3, runner=spy,
                              config=MainPathRerankConfig(enabled=True))

        byId = {d["id"]: d for d in spy.seen}
        assert byId["b"]["bm25"] == 0.80 and byId["b"]["vector"] == 0.75
        assert byId["b"]["fts"] == 0.60


class TestModelChannelDegradesHonestly:
    def test_missingProviderFallsBackAndSaysSo(self, rows, monkeypatch):
        from neurova.llm import rerank_client as rc
        from neurova.knowledge.rerank.rerank_factory import buildRunner

        def _boom(name):
            raise rc.RerankConfigError("没有配 rerank provider", reason="not_configured:test")

        monkeypatch.setattr(rc, "build_rerank_provider", _boom)
        runner, label, note = buildRunner({"method": "model"}, providerResolver=_boom)

        assert label == "weight" and note and note["requested"] == "model"
        assert runner is not None

    def test_mainPathCarriesTheEffectiveMethodNotTheRequestedOne(self, rows, monkeypatch):
        """请求 model、实际 weight ⇒ 结果上的 method 必须是 weight：标成 model 就是冒充已生效。"""
        monkeypatch.setenv(MAIN_RERANK_ENV, "on")

        out, note = refineMainPathResults(
            "查询", rows, limit=3,
            config=MainPathRerankConfig(enabled=True, method="model"),
            providerResolver=lambda name: None)

        assert {r["rerank_method"] for r in out} == {"weight"}
        assert note and note["requested"] == "model"


class TestOneAssemblyOnly:
    def test_apiDelegatesToTheSharedFactory(self):
        """旁路 API 不许再自己装 runner——两份装配就是两套口径。"""
        from neurova.api.endpoints import semantic_search_api as api
        from neurova.knowledge.rerank import rerank_factory

        assert api._build_rerank_runner is rerank_factory.buildRunner

    def test_docsShapeMatchesWhatRunnersExpect(self, rows, monkeypatch):
        """交给 runner 的文档必须带 index/id/content 与各通道分——与 API 侧同一形状。"""
        monkeypatch.setenv(MAIN_RERANK_ENV, "on")
        spy = SpyRunner()

        refineMainPathResults("查询", rows, limit=3, runner=spy,
                              config=MainPathRerankConfig(enabled=True))

        for d in spy.seen:
            assert {"index", "id", "content", "bm25", "vector", "fts"} <= set(d)
