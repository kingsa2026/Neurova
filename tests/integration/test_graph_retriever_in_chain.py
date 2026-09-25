"""多跳图检索入链（工单 013，灭 B04）。

B04 的形状：属性图（`knowledge_graph/manager.py`，JSON 文件 + Python BFS）从未进过对话
检索链，26% 覆盖率的图结构在答题时完全不被利用。本票不把它当权威读面——多跳走底座
三元组的递归 CTE（`knowledge_subjects` + `knowledge_facts`），所以图检索与时效事实读的是
同一份真相，不会出现"图上说一套、事实库里说一套"。

判据重点：2 跳链能带出终点事实、环不吊死、深度有界、只供三元组、装配可关且缺席可见。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, subject, predicate, obj, content=None, *, agentId="default",
           mediumRef="unit:test"):
    """正文默认按 SPO 生成：内容身份相同 ⇒ 咽喉折成同一行（004/§5 段1 的口径），
    共用一句"事实正文"会让第二条三元组凭空消失，测出来的 0 命中是假的。"""
    gate = productionAdmissionGate(store, toolVersion="unit")
    content = content or "%s %s %s" % (subject, predicate, obj)
    return gate.admit(AdmissionRequest(
        agentId=agentId, subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": mediumRef, "statementText": content}],
    ), allowPendingSegments=True).factId


class TestMultiHopWalk:
    def test_twoHopChainReachesTheTerminalFact(self, store):
        _admit(store, "神经瓦", "uses", "记忆层")
        _admit(store, "记忆层", "runs_on", "ONNX")

        hops = GraphFactWalker(store).walkFromQuery("神经瓦的存储最终跑在什么上")

        assert [(h["predicate"], h["object"], h["hop"]) for h in hops] == [("runs_on", "ONNX", 2)]
        assert "神经瓦" in hops[0]["path"] and "记忆层" in hops[0]["path"], "路径要能读出为什么被带进来"

    def test_firstHopIsNotRepeatedHere(self, store):
        """一跳事实是时效分支（012）的活；两路都给就是同一说法占两个槽。"""
        _admit(store, "神经瓦", "uses", "记忆层")
        _admit(store, "记忆层", "runs_on", "ONNX")

        assert [h["hop"] for h in GraphFactWalker(store).walkFromQuery("神经瓦")] == [2]

    def test_threeHopsAreReachableWhenAsked(self, store):
        _admit(store, "甲部", "relates_to", "乙部")
        _admit(store, "乙部", "relates_to", "丙部")
        _admit(store, "丙部", "relates_to", "丁部")

        assert [(h["object"], h["hop"]) for h in
                GraphFactWalker(store).walkFromQuery("甲部", maxHops=3)] == [("丙部", 2), ("丁部", 3)]
        assert [h["object"] for h in GraphFactWalker(store).walkFromQuery("甲部")] == ["丙部"]

    def test_cyclesTerminateWithoutDuplicates(self, store):
        """环必须走到就停：递归 CTE 用 UNION ALL 不去重，放任就会组合爆炸。"""
        _admit(store, "甲部", "relates_to", "乙部")
        _admit(store, "乙部", "relates_to", "甲部")
        _admit(store, "乙部", "relates_to", "乙部")
        _admit(store, "乙部", "relates_to", "丙部")

        hops = GraphFactWalker(store).walkFromQuery("甲部", maxHops=4)

        assert [(h["object"], h["hop"]) for h in hops] == [("丙部", 2)], "回环与自环都不许产出"
        for hop in hops:
            labels = [p for p in hop["visited"].split("|") if p]
            assert len(labels) == len(set(labels)), "路径里不许第二次经过同一个主体"

    def test_narrativeRowsAreNeitherEdgesNorBridges(self, store):
        """叙述行的客体是内容键：把它当边，终点事实就是凭空推出来的。"""
        _admit(store, "甲部", "relates_to", "乙部")
        store.upsertFact("default", store.upsertSubject("default", "乙部"), "documented_as",
                         "丙部", "", relationKind="document", recordKind="narrative")
        _admit(store, "丙部", "relates_to", "丁部")

        assert GraphFactWalker(store).walkFromQuery("甲部", maxHops=3) == []

    def test_walkDoesNotBridgeAgentDomains(self, store):
        """身份是 agent 域内的（`ux_subject_label` 就按 (agent, label) 建唯一索引），
        走图跨域等于把两个 agent 的说法拼成一条链。"""
        _admit(store, "甲部", "relates_to", "乙部", agentId="default")
        _admit(store, "乙部", "relates_to", "丙部", agentId="kai")

        assert GraphFactWalker(store).walkFromQuery("甲部", maxHops=3) == []
        assert GraphFactWalker(store, agentId="kai").walkFromQuery("甲部") == []

    def test_singleCharLabelsAreNotMatched(self, store):
        """单字标签不进匹配范围——一个"的"字就能把整张图拽进上下文。"""
        _admit(store, "甲", "relates_to", "乙")

        assert GraphFactWalker(store).walkFromQuery("甲乙丙") == []

    def test_unmatchedQueryWalksNowhere(self, store):
        _admit(store, "甲部", "relates_to", "乙部")

        assert GraphFactWalker(store).walkFromQuery("完全无关的一句话") == []


class TestRetrieverAndAssembly:
    def test_adapterShapeAndInjectionFeedback(self, store):
        from neurova.agent.graph_retriever_adapter import GraphRetrieverAdapter
        from neurova.agent.memory_retrieval_chain import RetrievalContext

        _admit(store, "神经瓦", "uses", "记忆层")
        _admit(store, "记忆层", "runs_on", "ONNX")
        terminal = store._conn.execute(
            "SELECT fact_id FROM knowledge_facts WHERE object_term = 'ONNX'").fetchone()[0]
        adapter = GraphRetrieverAdapter(GraphFactWalker(store))

        result = asyncio.run(adapter.retrieve(RetrievalContext(query="神经瓦跑在什么上", limit=5)))

        assert result.metadata["hits"] == 1
        assert result.memories[0]["type"] == "graph_fact"
        assert result.memories[0]["hops"] == 2
        assert "记忆层" in result.memories[0]["content"]
        assert store.fact(terminal)["injected_count"] == 1, "图命中也要回流，否则用量账缺一条路"

    def _pipeline(self, agent=None, monkeypatch=None, store=None):
        """用真对象而不是 MagicMock：MagicMock 对任何属性都返回真值，会把
        "agent 上还没挂 walker"这一分支整体短路掉——那正是要测的分支。"""
        import neurova.knowledge.foundation.knowledge_facts as kf_mod
        from neurova.agent.chat_pipeline import ChatPipeline
        from neurova.agent.memory_retrieval_chain import MemoryRetrievalChain

        if monkeypatch is not None:
            monkeypatch.setattr(kf_mod, "get_knowledge_fact_store", lambda *a, **k: store)
        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = agent if agent is not None else SimpleNamespace()
        pipeline._memory_retrieval_chain = MemoryRetrievalChain()
        pipeline._init_memory_retrieval_chain()
        return pipeline._memory_retrieval_chain.get_retrievers()

    def test_registeredOnceAtItsOwnSlotAndChainStaysOrdered(self, store, monkeypatch):
        monkeypatch.delenv("NEUROVA_KB_GRAPH_RETRIEVER", raising=False)

        retrievers = self._pipeline(SimpleNamespace(), monkeypatch, store)
        graph = [r for r in retrievers if getattr(r, "name", "") == "GraphRetriever"]

        assert len(graph) == 1 and graph[0].priority == 27
        priorities = [r.priority for r in retrievers]
        assert priorities == sorted(priorities), "责任链按优先级走，装配序不能乱"
        names = [r.name for r in retrievers]
        assert names.index("TKGRetriever") < names.index("GraphRetriever") < names.index("CacheRetriever")

    def test_gateOffRemovesTheBranchAndIsVisible(self, store, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("NEUROVA_KB_GRAPH_RETRIEVER", "off")

        retrievers = self._pipeline(SimpleNamespace(), monkeypatch, store)

        assert [r for r in retrievers if getattr(r, "name", "") == "GraphRetriever"] == []
        assert not any(rec.levelno >= logging.ERROR and "图检索" in rec.getMessage()
                       for rec in caplog.records), "关闸是有意的，不该报成故障"

    def test_brokenStoreDegradesLoudly(self, monkeypatch, caplog):
        import logging

        import neurova.knowledge.foundation.knowledge_facts as kf_mod

        def _unavailable(*a, **k):
            raise RuntimeError("底座库打不开")

        monkeypatch.setattr(kf_mod, "get_knowledge_fact_store", _unavailable)

        retrievers = self._pipeline(SimpleNamespace(), None, None)

        assert [r for r in retrievers if getattr(r, "name", "") == "GraphRetriever"] == []
        assert any(rec.levelno >= logging.ERROR and "图检索" in rec.getMessage()
                   for rec in caplog.records), "缺席必须是 ERROR 级读数，别再养一个 B01"
