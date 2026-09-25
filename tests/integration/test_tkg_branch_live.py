"""时效事实分支接活（工单 012，灭 B01）。

B01 的形状：`chat_pipeline.py` 无参构造 `TemporalKnowledgeGraph()`，其 `db_path` 默认
`":memory:"` ⇒ priority 26 的检索器每轮扫自己那张空表。修法是让这条分支读**底座库**，
不复制不新建；所以本文件的判据全部围绕"命中来自权威、且只来自权威"。

B02（没有三元组进底座）不在本票修：抽取写面退役由咽喉取代，E4 的推导事实才是这条分支
的真数据源。本票因此不断言"生产命中 > 0"，只断言"命中数等于权威中的时效三元组数"。
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from types import SimpleNamespace

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader


def _iso(moment: datetime.datetime) -> str:
    return moment.isoformat()


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, subject, predicate, obj, content, *, mediumRef="unit:test",
           agentId="default", extraAssertions=0):
    gate = productionAdmissionGate(store, toolVersion="unit")
    assertions = [{"actorType": "pipeline", "actorId": "unit", "mediumRef": mediumRef,
                   "statementText": content}]
    for n in range(extraAssertions):
        assertions.append({"actorType": "user", "actorId": "u%d" % n,
                           "mediumRef": "import:twin%d.md" % n, "statementText": content})
    return gate.admit(AdmissionRequest(
        agentId=agentId, subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content, assertions=assertions,
    ), allowPendingSegments=True).factId


class TestBranchReadsTheFoundation:
    def test_admittedTripleIsHit(self, store):
        factId = _admit(store, "神经瓦", "uses", "SQLite",
                        "神经瓦的存储用 SQLite，不引外部服务")

        hits = TemporalFactReader(store).forQuery("神经瓦用什么存储")

        assert [h["id"] for h in hits] == [factId]
        assert hits[0]["subject"] == "神经瓦"
        assert hits[0]["predicate"] == "uses"
        assert hits[0]["object"] == "SQLite"
        assert hits[0]["source"] == "unit:test", "来源取断言 medium_ref，不编造"

    def test_narrativeRowsStayOutOfThisBranch(self, store):
        """条目正文由 KnowledgeRetriever 那一路给；这条分支只供三元组，否则同一篇正文进两次槽。"""
        _admit(store, "同一篇笔记", "mentions", "笔记", "完全一样的正文内容")
        store.upsertFact("default", store.upsertSubject("default", "某条目"), "documented_as",
                         "abc", "", recordKind="narrative", relationKind="document")

        hits = TemporalFactReader(store).forQuery("同一篇笔记里提到了什么")

        assert [h["predicate"] for h in hits] == ["mentions"]
        assert [h["subject"] for h in hits] == ["同一篇笔记"]

    def test_cjkSubjectContainedInQueryMatches(self, store):
        """旧桥用 `[^\\w\\s]` 切词，中文整句成一个 token，只能全句相等才命中。"""
        _admit(store, "记忆层", "runs_on", "onnx", "记忆层默认走 onnx 后端")

        assert TemporalFactReader(store).forQuery("请介绍一下记忆层的后端选型"), \
            "主体名出现在查询里就该命中，与分词无关"

    def test_aliasOfTheResolvedSubjectMatches(self, store):
        key = store.upsertSubject("default", "神经瓦", aliases=["Neurova"])
        store.upsertFact("default", key, "version", "2.0", "神经瓦 2.0 发布")

        assert [h["object"] for h in TemporalFactReader(store).forQuery("Neurova 现在什么版本")] == ["2.0"]

    def test_agentScopeIsHonoured(self, store):
        _admit(store, "神经瓦", "uses", "SQLite", "default 域的事实", agentId="default")
        _admit(store, "神经瓦", "uses", "faiss", "kai 域的事实", agentId="kai")

        hits = TemporalFactReader(store, agentId="kai").forQuery("神经瓦用什么")

        assert [h["object"] for h in hits] == ["faiss"]

    def test_noQueryTextMatchesNothing(self, store):
        _admit(store, "神经瓦", "uses", "SQLite", "事实")

        assert TemporalFactReader(store).forQuery("") == []
        assert TemporalFactReader(store).forQuery("完全无关的一句话") == []


class TestTemporalSemantics:
    def _add(self, store, obj, *, confidence=None, recordedAt=None):
        key = store.upsertSubject("default", "成本护栏")
        return store.upsertFact("default", key, "governs", obj, "正文 %s" % obj,
                                confidence=confidence, recordedAt=recordedAt)

    def test_confidenceLeadsThenRecency(self, store):
        now = datetime.datetime.now(datetime.timezone.utc)
        low = self._add(store, "低置信", confidence=0.45)
        high = self._add(store, "高置信", confidence=0.9)
        store._conn.execute("UPDATE knowledge_facts SET recorded_at = ? WHERE fact_id = ?",
                            (_iso(now - datetime.timedelta(hours=1)), low))
        store._conn.commit()

        assert [h["id"] for h in TemporalFactReader(store).forQuery("成本护栏")] == [high, low]

    def test_expiredAndOutOfWindowAreDropped(self, store):
        now = datetime.datetime.now(datetime.timezone.utc)
        stale = self._add(store, "很久以前", confidence=0.9,
                          recordedAt=_iso(now - datetime.timedelta(days=90)))
        closed = self._add(store, "已失效", confidence=0.9)
        fresh = self._add(store, "此刻有效", confidence=0.9)
        store.setValidUntil(closed, _iso(now - datetime.timedelta(days=1)))

        hits = TemporalFactReader(store).forQuery("成本护栏")

        assert [h["object"] for h in hits] == ["此刻有效"]
        assert stale not in [h["id"] for h in hits], "超出时效窗口的旧说法不再进上下文"
        assert closed not in [h["id"] for h in hits], "已失效说法不得进上下文"

    def test_windowIsWidenableAndDefaultMatchesTheRetrieverContract(self, store):
        now = datetime.datetime.now(datetime.timezone.utc)
        old = self._add(store, "半年前", confidence=0.9,
                        recordedAt=_iso(now - datetime.timedelta(days=200)))

        assert TemporalFactReader(store).forQuery("成本护栏") == []
        assert [h["id"] for h in TemporalFactReader(store).forQuery(
            "成本护栏", windowDays=400)] == [old]


class TestRetrieverContractAndAssembly:
    def test_adapterShapeIsUnchanged(self, store):
        from neurova.agent.memory_retrieval_chain import RetrievalContext
        from neurova.agent.tkg_retriever_adapter import TKGRetrieverAdapter

        _admit(store, "神经瓦", "uses", "SQLite", "事实正文")
        adapter = TKGRetrieverAdapter(TemporalFactReader(store))
        context = RetrievalContext(query="神经瓦用什么", limit=5)

        result = asyncio.run(adapter.retrieve(context))

        assert result.metadata["hits"] == 1
        assert result.memories[0]["type"] == "tkg_fact"
        assert "神经瓦" in result.memories[0]["content"]

    def _pipeline(self, agent=None):
        """用真对象而不是 MagicMock：MagicMock 对任何属性都返回真值，
        会把"agent 上还没挂 reader"这一分支整体短路掉——那正是要测的分支。"""
        from neurova.agent.chat_pipeline import ChatPipeline
        from neurova.agent.memory_retrieval_chain import MemoryRetrievalChain

        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = agent if agent is not None else SimpleNamespace()
        pipeline._memory_retrieval_chain = MemoryRetrievalChain()
        pipeline._init_memory_retrieval_chain()
        return pipeline

    @staticmethod
    def _branch(pipeline):
        return [r for r in pipeline._memory_retrieval_chain.get_retrievers()
                if getattr(r, "name", "") == "TKGRetriever"]

    def test_assemblyNeverBuildsThePrivateEmptyTable(self, store, monkeypatch):
        """装配必须读底座；再出现无参 TemporalKnowledgeGraph() 就是 B01 原地复活。"""
        import neurova.cognitive_layers.memory_layer.temporal_knowledge_graph as tkg_mod
        import neurova.knowledge.foundation.knowledge_facts as kf_mod

        def _boom(*a, **k):
            raise AssertionError("012 之后装配不得再构造私有 TKG 表")

        monkeypatch.setattr(tkg_mod, "TemporalKnowledgeGraph", _boom)
        monkeypatch.setattr(kf_mod, "get_knowledge_fact_store", lambda *a, **k: store)

        branch = self._branch(self._pipeline())

        assert len(branch) == 1 and branch[0].priority == 26
        assert isinstance(branch[0]._tkg, TemporalFactReader)

    def test_readerIsBuiltOncePerAgentNotPerTurn(self, store, monkeypatch):
        import neurova.knowledge.foundation.knowledge_facts as kf_mod

        monkeypatch.setattr(kf_mod, "get_knowledge_fact_store", lambda *a, **k: store)
        agent = SimpleNamespace()

        left = self._branch(self._pipeline(agent))[0]
        right = self._branch(self._pipeline(agent))[0]

        assert left._tkg is right._tkg, "每轮重造实例就是每轮重开一条连接"

    def test_missingFactStoreDegradesLoudlyButDoesNotBlockTheChain(self, monkeypatch, caplog):
        import neurova.knowledge.foundation.knowledge_facts as kf_mod

        def _unavailable(*a, **k):
            raise RuntimeError("底座库打不开")

        monkeypatch.setattr(kf_mod, "get_knowledge_fact_store", _unavailable)

        pipeline = self._pipeline()

        assert self._branch(pipeline) == []
        assert any(rec.levelno >= logging.ERROR and "时效事实" in rec.getMessage()
                   for rec in caplog.records), \
            "分支缺席必须是 ERROR 级读数，不能又是一条 warning 混过去"
