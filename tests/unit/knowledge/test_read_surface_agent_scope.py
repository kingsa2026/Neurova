"""底座两条读面的锚点必须落在本 agent 的域里。

病灶形状（2026-09-21 审计 §4、§5.5）：`chat_pipeline.py` 装配
`TemporalFactReader(store)` / `GraphFactWalker(store)` 时只传 store，`agentId` 走默认
`None`；两条读面的锚点查询是**守卫式**过滤（`agentId` 为空即不过滤），于是
「我先看看这句话在问谁」这一步会跨全部 agent 取主体，多跳递归段虽然锁了域，
但起点已经从别人的库里挑出来了。

判据：装配出来的读面必须带本 agent 的域；且域必须真咬合——另一个 agent 的
同名主体不得成为锚点。顺序也必须对：`agent_id` 过滤器要在参数表首位，
否则参数错位会静默读成"别人的主体 + 我的窗口"。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, agentId, subject, obj, predicate):
    gate = productionAdmissionGate(store, toolVersion="unit")
    text = "%s 的取值是 %s" % (subject, obj)
    return gate.admit(AdmissionRequest(
        agentId=agentId, subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=text, assertions=[{"actorType": "pipeline", "actorId": "unit",
                                   "mediumRef": "unit:test", "statementText": text}],
    )).factId


class TestReadersCarryTheAgentDomain:
    def test_temporalReaderFiltersAtTheAnchorNotOnlyInTheBody(self, store):
        # 谓词刻意不同：跨 agent 的同 (主体, 谓词) 分歧是设计上要成账的（G03），
        # 本用例要证的是锚点域，不是裁决口径，别让两者互相干扰。
        mine = _admit(store, "kai", "成本护栏", "0.8", "takes")
        theirs = _admit(store, "default", "成本护栏", "0.2", "holds")

        from neurova.knowledge.foundation.temporal_facts import TemporalFactReader

        hits = TemporalFactReader(store, agentId="kai").forQuery("成本护栏的取值")

        assert [h["id"] for h in hits] == [mine]
        assert theirs not in [h["id"] for h in hits]

    def test_graphWalkerAnchorsStayInDomain(self, store):
        key = store.upsertSubject("kai", "甲")
        store.upsertFact("kai", key, "links", "乙", "甲连着乙")
        other = store.upsertSubject("default", "乙")
        store.upsertFact("default", other, "links", "丙", "乙连着丙")

        from neurova.knowledge.foundation.graph_walk import GraphFactWalker

        walk = GraphFactWalker(store, agentId="kai")

        assert walk.walkFromQuery("甲") == [], "另一域的乙不得被当成本域的 乙 接着走"
        assert all(row["hop"] >= 2 for row in walk.walkFromQuery("乙"))


class TestPipelineAssemblyPassesTheDomain:
    """放大视角：装配点也必须传域，否则读面收域这件事在生产上没人用。"""

    @staticmethod
    def _pipeline(agent):
        from neurova.agent.chat_pipeline import ChatPipeline
        from neurova.agent.memory_retrieval_chain import MemoryRetrievalChain

        pipeline = ChatPipeline.__new__(ChatPipeline)
        pipeline._agent = agent
        pipeline._memory_retrieval_chain = MemoryRetrievalChain()
        pipeline._init_memory_retrieval_chain()
        return pipeline

    @staticmethod
    def _branch(pipeline, name):
        return [r for r in pipeline._memory_retrieval_chain.get_retrievers()
                if getattr(r, "name", "") == name]

    def test_bothReadersAreAssembledWithTheAgentId(self, store, monkeypatch):
        import neurova.knowledge.foundation.knowledge_facts as kf_mod

        monkeypatch.setattr(kf_mod, "get_knowledge_fact_store", lambda *a, **k: store)
        agent = SimpleNamespace(config=SimpleNamespace(agent_id="kai"))

        pipeline = self._pipeline(agent)

        assert self._branch(pipeline, "TKGRetriever")[0]._tkg._agentId == "kai"
        assert self._branch(pipeline, "GraphRetriever")[0]._walker._agentId == "kai"
