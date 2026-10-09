# -*- coding: utf-8 -*-
"""投影必须是权威的派生物，不是模型输出的副本（§6-106 复算根因 → 本批根修）。

复算把根因指到 `extract_knowledge_to_graph` 的**建边循环**：底座那一侧对关系有
两道门（`custom` 不收、被拒不入权威），投影这一侧一道都没有——`relation` 算出来是
什么就建什么边，节点也照模型给的全部实体建。于是模型幻觉出的关系、被定义域拒掉的
关系，全都进了图，而图是可视化读的那一份。§6-106 在真库上量到的
`orphan_relations 52` / 清账后 `unbacked_nodes 33` 就是这条的存量形态：
一条都没进权威的说法，在图上看起来跟真事实一模一样，还捎带条目正文摘要。

判据两类：
- **根修**：权威没接纳的关系不许进图，只出现在被拒关系里的实体也不许进图；
- **存量收口**：rebuild 的 docstring 早就写"重建即整体按权威换新"，可它过去只摘
  "碰到本域标签"的边、只摘"本域标签且无邻居"的点——两端都不在权威里的边它不动。
  文案与实做不一致，本批按文案对齐（并留 `pruned_*` 读数，不假装安静）。

另有一条防过修：有权威据的边与节点必须原样留着——把图清空不叫"按权威换新"。
"""

from __future__ import annotations

import json

import pytest

from neurova.cognitive_layers.knowledge_graph.manager import KnowledgeGraphManager
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME
from neurova.knowledge.graph_bridge import (
    extract_knowledge_to_graph,
    projectionDrift,
    rebuildProjectionFromAuthority,
)


def _store(tmp_path) -> KnowledgeFactStore:
    return KnowledgeFactStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME))


def _admitRelation(store, source, relation, target):
    gate = productionAdmissionGate(store, toolVersion="unit")
    content = "%s %s %s" % (source, relation, target)
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=source, predicateTermId=relation,
        objectTerm=target, content=content,
        activityKind="extract", activityBasis="unit:projection-follows-authority",
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:pfa", "statementText": content}],
    )).factId


class TestExtractionProjectsOnlyWhatAuthorityAccepted:
    def test_relationRejectedByAuthorityMustNotBecomeAnEdge(self, tmp_path):
        """模型给的关系若没进权威，图里就不该有它——这条边今天会被建出来。"""
        store = _store(tmp_path)
        graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "kb" / "graph"))
        try:
            item = {"knowledge_id": "kb-pfa-1", "title": "青梧对账",
                    "content": "青梧中转站的阈值取 45 秒"}

            def llm(_prompt):
                return json.dumps({
                    "entities": [{"label": "青梧甲", "type": "concept"},
                                 {"label": "青梧乙", "type": "concept"},
                                 {"label": "青梧丙", "type": "concept"}],
                    "relations": [
                        {"source": "青梧甲", "target": "青梧乙", "type": "depends_on"},
                        # 未登记的关系类型：底座那道门不收 custom，权威里不会有条
                        {"source": "青梧甲", "target": "青梧丙", "type": "telepathizes"},
                    ],
                })

            extract_knowledge_to_graph(item, repo=None, llm_call=llm,
                                       graph_manager=graph, factStore=store,
                                       agentId="default")
            labels = {n.node_id: n.label for n in graph._nodes.values()}
            edges = [(labels.get(e.source_id), e.relationTypeValue, labels.get(e.target_id))
                     for e in graph._edges.values()]

            assert ("青梧甲", "depends_on", "青梧乙") in edges, (
                "有据的那条关系反而没进图——修法把正路也堵了：%s" % edges)
            assert not any(rel in ("telepathizes", "custom") for _s, rel, _t in edges), (
                "权威没收的关系进了图（未登记类型会落成 custom 边）——它就是 §6-106 那 52 条"
                "孤儿边的新个体：%s" % edges)
            # 反向不许过修：丙的 `is_a` 落了库，它就是权威里的主体，"暂时没连上边"
            # 不是无据。第一版把"参与关系"当点据，正是这一格会拦住的那种过修。
            assert "青梧丙" in set(labels.values()), (
                "有据主体被当成无据点删了，口径又打偏了：%s" % sorted(labels.values()))
            drift = projectionDrift("default", graph, store)
            assert drift["orphan_relations"] == [], drift["orphan_relations"]
            assert drift["unbacked_nodes"] == [], drift["unbacked_nodes"]
        finally:
            store.close()

    def test_projectionEdgesAreAllBackedByAuthority(self, tmp_path):
        """一条总判据：投影里的边必须逐条能在权威里找到依据（口径与 drift 同源）。"""
        store = _store(tmp_path)
        graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "kb" / "graph"))
        try:
            _admitRelation(store, "青梧甲", "is_a", "文档集合")   # 让"青梧甲"成为主体
            item = {"knowledge_id": "kb-pfa-2", "title": "青梧索引",
                    "content": "青梧索引的版本是 v100"}

            def llm(_prompt):
                return json.dumps({
                    "entities": [{"label": "青梧索引", "type": "concept"},
                                 {"label": "青梧甲", "type": "concept"}],
                    "relations": [{"source": "青梧索引", "target": "青梧甲",
                                   "type": "part_of"},
                                  {"source": "青梧索引", "target": "青梧甲",
                                   "type": "telepathizes"}]})

            extract_knowledge_to_graph(item, repo=None, llm_call=llm,
                                       graph_manager=graph, factStore=store,
                                       agentId="default")
            drift = projectionDrift("default", graph, store)
            assert drift["orphan_relations"] == [], drift["orphan_relations"]
            assert len(drift["unbacked_nodes"]) == 0, drift["unbacked_nodes"]
        finally:
            store.close()


class TestRebuildReplacesWithAuthority:
    def test_rebuildPrunesUnbackedEdgesAndIsolatedNodes(self, tmp_path):
        """存量：手工塞一条无据边 + 一个无据孤立节点，rebuild 必须按文案"整体换新"摘掉。"""
        store = _store(tmp_path)
        graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "kb" / "graph"))
        try:
            _admitRelation(store, "青梧甲", "is_a", "文档集合")
            _admitRelation(store, "青梧乙", "is_a", "文档集合")
            _admitRelation(store, "青梧甲", "part_of", "青梧乙")
            a = graph.add_node(label="青梧甲")
            b = graph.add_node(label="青梧乙")
            graph.add_edge(source_id=a.node_id, target_id=b.node_id, relation_type="part_of")
            ghostEdgeFrom = graph.add_node(label="遗留甲")
            ghostEdgeTo = graph.add_node(label="遗留乙")
            graph.add_edge(source_id=ghostEdgeFrom.node_id, target_id=ghostEdgeTo.node_id,
                           relation_type="related_to")
            graph.add_node(label="遗留孤立",
                           properties={"description": "条目正文摘要残留"})

            # 点据 = 主体在权威里。这三个"遗留*"都没落过 is_a，所以三个都算无据；
            # 有边没边的差别在 orphan_relations 那一格，两维不许互相冒充
            before = projectionDrift("default", graph, store)
            assert len(before["orphan_relations"]) == 1, before["orphan_relations"]
            assert len(before["unbacked_nodes"]) == 3, before["unbacked_nodes"]
            outcome = rebuildProjectionFromAuthority("default", graph, store)

            assert outcome["pruned_edges"] >= 1, outcome
            assert outcome["pruned_nodes"] >= 3, outcome
            after = projectionDrift("default", graph, store)
            assert after["orphan_relations"] == [] and after["missing_relations"] == [], after
            assert after["unbacked_nodes"] == [], after["unbacked_nodes"]
        finally:
            store.close()

    def test_rebuildKeepsEverythingAuthorityBacked(self, tmp_path):
        """防过修：有据的边与节点一条都不许多删——清空不是"按权威换新"。"""
        store = _store(tmp_path)
        graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "kb" / "graph"))
        try:
            _admitRelation(store, "青梧甲", "is_a", "文档集合")
            _admitRelation(store, "青梧乙", "is_a", "文档集合")
            _admitRelation(store, "青梧甲", "part_of", "青梧乙")
            outcome = rebuildProjectionFromAuthority("default", graph, store)
            labels = {n.label for n in graph._nodes.values()}
            relations = [(e.relationTypeValue) for e in graph._edges.values()]

            assert {"青梧甲", "青梧乙"} <= labels, labels
            assert "part_of" in relations, relations
            assert outcome["drift"]["projection_relations"] == outcome["drift"]["authority_relations"]
        finally:
            store.close()
